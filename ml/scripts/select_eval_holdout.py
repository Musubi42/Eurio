"""Prélève le JEU D'ÉVALUATION de la matrice d'encodeurs, et le marque.

Chantier ``juge-et-banc``, étape 2. Départager ArcFace et DINO exige des images
que **ni l'un ni l'autre** n'a vues. Ce script les choisit, puis pousse le
marquage ``image_assets.eval_corpus`` au canonique (``POST
/ingest/eval-corpus``) — le calcul reste où sont les mesures, seules les lignes
voyagent (même doctrine que ``backfill_quality_score``).

Le critère — décision **D5** du suivi, et le point le plus important du fichier
==============================================================================

🔴 **Le critère est INDÉPENDANT des deux modèles jugés.** Il n'utilise ni
distance DINO à la canonique, ni score ArcFace, ni aucun embedding appris. La
raison est que « le plus loin de la canonique selon DINO » **est le critère du
farthest-point sampling** qui a bâti la banque d'ancres : le prendre pour
critère d'éval sélectionnerait préférentiellement des crops qui **sont déjà des
ancres** (46,8 % du pool éligible en est une — 1391/2969), que DINO
reconnaîtrait à similarité 1,0 ; et exclure les ancres pour l'éviter ne fait que
retourner le biais — on obtiendrait *les cas durs de DINO choisis par DINO*,
imposés à ArcFace qui n'a pas voix au chapitre.

L'intention du PO, elle, est gardée : il veut des images qui **ressemblent à ce
qu'un utilisateur photographierait**, donc dégradées. La dégradation visée est
**géométrique**, et elle se mesure **sans aucun modèle appris** — ``tilt_deg``,
l'angle d'inclinaison de la pièce déduit de l'ellipse ajustée sur ses bords
(``acos(axis_ratio)``). C'est ce que l'étape 1 vient de rendre disponible sur
tout le parc.

La règle, en toutes lettres
---------------------------

Pour chaque classe (maille ``COALESCE(design_group_id, eurio_id)``) :

1. **pool candidat** = crops eBay, ``training_eligible = 1``, présents en
   stockage, non-revers, ``eval_corpus IS NULL``, ``tilt_deg`` **mesuré**, et
   **qui ne sont pas des ancres de la banque servie** ``2eur_all`` (les noter
   contre elle mesurerait une similarité de 1,0 avec eux-mêmes) ;
2. on ordonne par ``(tilt_deg DÉCROISSANT, id CROISSANT)`` — l'``id`` est le
   bris d'égalité, il rend l'ordre total et donc rejouable ;
3. on retient la **moitié la plus inclinée** (``m = ceil(n/2)`` premiers) ;
4. on y prend **5 positions régulièrement espacées** :
   ``idx_k = floor((2k+1) × m / 10)`` pour ``k = 0…4``.

**Aucun aléatoire n'intervient — il n'y a donc pas de graine à fixer.** Deux
exécutions sur la même base rendent exactement la même liste ; c'est vérifié par
``tests/test_eval_holdout.py``.

Pourquoi la moitié la plus inclinée et pas simplement les 5 pires : un jeu fait
des 5 crops les plus tiltés de chaque classe serait un jeu d'extrêmes, où la
moindre valeur aberrante de l'ellipse (arc partiel, reflet) pèserait autant
qu'une vraie photo de biais. Les quantiles gardent le biais « dégradé » **et**
balaient toute l'étendue de la moitié visée.

Les biais que cette règle introduit — il y en a toujours
--------------------------------------------------------

À dire avec le résultat, jamais après :

* **le jeu est plus dur que la population.** Par construction. Les taux absolus
  des deux modèles seront pessimistes ; seule leur COMPARAISON est lisible ;
* ``tilt_deg`` **ne mesure pas que l'inclinaison.** Un fort tilt apparent peut
  venir d'une pièce partiellement occultée, d'un arc incomplet ou d'un reflet
  qui déforme l'ellipse. Le jeu contient donc aussi des crops *mal détourés*,
  pas seulement des prises de vue obliques ;
* ``tilt_trustworthy`` **n'est pas exigé** (cf. ``--require-trustworthy``) : le
  restreindre couperait le pool et, surtout, les mesures « non fiables » sont
  précisément celles des crops difficiles — les écarter ramènerait le jeu vers
  le facile, à rebours de l'intention ;
* **exclure les ancres appauvrit le pool de sa diversité d'apparence** (le FPS
  les a choisies pour ça). Le jeu est donc un peu plus « typique » en apparence
  que le pool complet. C'est le prix, assumé, de ne pas mesurer DINO contre
  lui-même ;
* ``quality_score`` **n'entre pas dans le classement** : l'oracle Otsu est muet
  sur ~1/3 du parc, et une règle qui imputerait une valeur aux muets choisirait
  en fait *l'imputation*. Il est reporté à titre descriptif.

Usage ::

    python -m scripts.select_eval_holdout                    # dry-run (défaut)
    python -m scripts.select_eval_holdout --plan out.json    # dry-run + plan
    python -m scripts.select_eval_holdout --apply            # marque et pousse
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parent.parent
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from store import resolve_db_path  # noqa: E402
from store.funnel_constants import MIN_REAL  # noqa: E402

#: Nom du corpus posé dans ``image_assets.eval_corpus``. Il NOMME la mesure :
#: une scorecard qui dit « mesuré sur matrice-encodeurs-2026-08 » est relisible
#: dans six mois, « mesuré sur le hold-out » ne l'est pas.
DEFAULT_CORPUS = "matrice-encodeurs-2026-08"

#: Version de la RÈGLE de sélection. La bumper signifie « le jeu n'est plus le
#: même » — donc les mesures d'avant ne se comparent plus à celles d'après.
SELECTION_RULE_VERSION = 1

DEFAULT_QUOTA = 5

#: La banque SERVIE. Ses ancres sont exclues du prélèvement : les noter contre
#: elle mesurerait une similarité de 1,0 avec elles-mêmes.
SERVED_ANCHORS_KIND = "2eur_all"

_POOL_SQL = """
    SELECT COALESCE(co.design_group_id, co.eurio_id) AS class_id,
           a.id                                      AS asset_id,
           a.eurio_id                                AS eurio_id,
           a.tilt_deg                                AS tilt_deg,
           a.tilt_trustworthy                        AS tilt_trustworthy,
           a.quality_score                           AS quality_score,
           a.storage_path                            AS storage_path,
           (a.id IN (SELECT asset_id FROM dino_class_references
                      WHERE anchors_kind = :kind AND asset_id IS NOT NULL))
                                                     AS est_ancre,
           (a.tilt_deg IS NOT NULL)                  AS tilt_mesure
      FROM image_assets a
      JOIN source_images si ON si.id = a.source_image_id
      JOIN coins co         ON co.eurio_id = a.eurio_id
     WHERE si.source = 'ebay'
       AND a.training_eligible = 1
       AND a.storage_status = 'present'
       AND (a.face IS NULL OR a.face != 'reverse')
       AND a.eval_corpus IS NULL
     ORDER BY class_id, a.id
"""


def quantiles_moitie_haute(n: int, quota: int) -> list[int]:
    """Les ``quota`` rangs prélevés dans la moitié haute d'un pool de ``n``.

    Rangs 0-indexés sur l'ordre « le plus dégradé d'abord ». Déterministe,
    sans aléatoire. Si la moitié haute est trop courte pour donner ``quota``
    rangs distincts, on déborde sur la suite du classement plutôt que de rendre
    des doublons — un doublon serait une image comptée deux fois.
    """
    if n <= 0 or quota <= 0:
        return []
    m = math.ceil(n / 2)
    rangs: list[int] = []
    for k in range(quota):
        idx = (2 * k + 1) * m // (2 * quota)
        # Débordement anti-doublon : borné par `n`. Sans la borne, un pool trop
        # court ferait tourner cette boucle indéfiniment — et un script qui ne
        # rend jamais la main ressemble à un calcul long, pas à une panne.
        while idx < n and idx in rangs:
            idx += 1
        if idx >= n:  # pool épuisé — on rend moins que le quota, jamais un doublon
            continue
        rangs.append(idx)
    return sorted(rangs)


def _open_ro(db: Path) -> sqlite3.Connection:
    """Lecture seule explicite. ``mode=ro`` et non ``immutable=1`` : la réplique
    est en WAL et un écrivain peut tourner — ``immutable=1`` rendrait alors un
    instantané périmé, **en silence** (cf. skill ``eurio-verify``, fiche WAL)."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def selectionner(
    conn: sqlite3.Connection,
    *,
    quota: int = DEFAULT_QUOTA,
    min_real: int = MIN_REAL,
    require_trustworthy: bool = False,
    anchors_kind: str = SERVED_ANCHORS_KIND,
) -> dict:
    """Rend le plan de prélèvement, sans rien écrire.

    ``{"classes": [...], "picks": [...], "rejets": {...}}``. Une classe n'est
    prélevée que si **ce qui reste** au train tient le plancher :
    ``n_train − quota >= min_real``. Le quota se raisonne sur le reste, jamais
    sur ce qu'on prend (``real_training_sources`` est partagé par le bake ET le
    préflight).
    """
    par_classe: dict[str, list[sqlite3.Row]] = {}
    for r in conn.execute(_POOL_SQL, {"kind": anchors_kind}):
        par_classe.setdefault(r["class_id"], []).append(r)

    classes: list[dict] = []
    picks: list[dict] = []
    rejets: dict[str, list[str]] = {"plancher": [], "pool_candidat_court": []}

    for class_id in sorted(par_classe):
        rows = par_classe[class_id]
        n_train = len(rows)  # ce que le préflight compte AVANT prélèvement
        if n_train - quota < min_real:
            rejets["plancher"].append(class_id)
            continue

        cands = [r for r in rows if r["tilt_mesure"] and not r["est_ancre"]]
        if require_trustworthy:
            fiables = [r for r in cands if r["tilt_trustworthy"]]
            if len(fiables) >= quota:
                cands = fiables
        # Ordre TOTAL : le plus incliné d'abord, `id` en bris d'égalité.
        cands.sort(key=lambda r: (-float(r["tilt_deg"]), r["asset_id"]))

        rangs = quantiles_moitie_haute(len(cands), quota)
        if len(rangs) < quota:
            rejets["pool_candidat_court"].append(class_id)
            continue

        choisis = [cands[i] for i in rangs]
        classes.append({
            "class_id": class_id,
            "n_train_avant": n_train,
            "n_train_apres": n_train - quota,
            "n_candidats": len(cands),
            "n_ancres_ecartees": sum(1 for r in rows if r["est_ancre"]),
            "n_sans_tilt": sum(1 for r in rows if not r["tilt_mesure"]),
            "tilt_min": round(min(float(r["tilt_deg"]) for r in choisis), 2),
            "tilt_max": round(max(float(r["tilt_deg"]) for r in choisis), 2),
        })
        for rang, r in zip(rangs, choisis):
            picks.append({
                "asset_id": r["asset_id"],
                "class_id": class_id,
                "eurio_id": r["eurio_id"],
                "storage_path": r["storage_path"],
                "rang": rang,
                "tilt_deg": round(float(r["tilt_deg"]), 3),
                "tilt_trustworthy": int(r["tilt_trustworthy"] or 0),
                "quality_score": r["quality_score"],
            })
    return {"classes": classes, "picks": picks, "rejets": rejets}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path,
                    default=resolve_db_path(_ML_DIR / "state" / "eurio.replica.db"))
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--quota", type=int, default=DEFAULT_QUOTA)
    ap.add_argument("--min-real", type=int, default=MIN_REAL)
    ap.add_argument("--require-trustworthy", action="store_true",
                    help="restreint aux tilts marqués fiables quand la classe "
                         "en a assez (change le jeu : cf. §biais)")
    ap.add_argument("--apply", action="store_true",
                    help="marque ET pousse au canonique (défaut = dry-run)")
    ap.add_argument("--plan", type=Path, default=None,
                    help="écrit le plan complet (JSON) — à committer avec la mesure")
    ap.add_argument("--batch", type=int, default=200)
    args = ap.parse_args(argv)

    conn = _open_ro(args.db)
    plan = selectionner(
        conn,
        quota=args.quota,
        min_real=args.min_real,
        require_trustworthy=args.require_trustworthy,
    )
    conn.close()

    plan["corpus"] = args.corpus
    plan["quota"] = args.quota
    plan["min_real"] = args.min_real
    plan["selection_rule_version"] = SELECTION_RULE_VERSION
    plan["require_trustworthy"] = bool(args.require_trustworthy)

    print(f"DB (lecture seule) : {args.db}")
    print(f"corpus             : {args.corpus} (règle v{SELECTION_RULE_VERSION})")
    print(f"classes retenues   : {len(plan['classes'])}")
    print(f"crops prélevés     : {len(plan['picks'])}")
    for motif, ids in plan["rejets"].items():
        if ids:
            print(f"écartées ({motif}) : {len(ids)} — {ids[:8]}"
                  f"{' …' if len(ids) > 8 else ''}")
    if plan["picks"]:
        tilts = sorted(p["tilt_deg"] for p in plan["picks"])
        print(f"tilt des prélevés  : min {tilts[0]:.1f}° · "
              f"médiane {tilts[len(tilts) // 2]:.1f}° · max {tilts[-1]:.1f}°")
        n_fiable = sum(p["tilt_trustworthy"] for p in plan["picks"])
        print(f"tilt fiable        : {n_fiable}/{len(plan['picks'])}")

    if args.plan:
        args.plan.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
        print(f"plan écrit         : {args.plan}")

    if not args.apply:
        print("\nDRY-RUN — rien marqué, rien poussé. Relancer avec --apply.")
        print(json.dumps({"updated": 0, "skipped": 0, "conflict": 0,
                          "missing": 0, "dry_run": True,
                          "a_marquer": len(plan["picks"])}))
        return 0

    from client.http import sync_enabled

    if not sync_enabled():
        print("EURIO_API_URL absent : impossible de pousser au canonique. "
              "Charge le devShell.", file=sys.stderr)
        return 2

    from client.ingest import push_eval_corpus

    totaux = {"updated": 0, "skipped": 0}
    conflits: list[str] = []
    manquants: list[str] = []
    rows = [{"asset_id": p["asset_id"], "eval_corpus": args.corpus}
            for p in plan["picks"]]
    for i in range(0, len(rows), args.batch):
        lot = rows[i:i + args.batch]
        res = push_eval_corpus(lot) or {}
        totaux["updated"] += int(res.get("updated") or 0)
        totaux["skipped"] += int(res.get("skipped") or 0)
        conflits.extend(res.get("conflict") or [])
        manquants.extend(res.get("missing") or [])
        print(f"  … marqué {res.get('updated')}/{len(lot)} "
              f"(skipped={res.get('skipped')}, "
              f"conflict={len(res.get('conflict') or [])}, "
              f"missing={len(res.get('missing') or [])})", flush=True)

    print("\ndestination : canonique (POST /ingest/eval-corpus)")
    if conflits:
        print(f"⚠️  CONFLITS (déjà dans un AUTRE corpus) : {len(conflits)} — "
              f"{conflits[:5]}")
    if manquants:
        print(f"⚠️  REFUSÉS (assets inconnus du canonique) : {len(manquants)} — "
              f"{manquants[:5]}")
    print(json.dumps({"updated": totaux["updated"], "skipped": totaux["skipped"],
                      "conflict": len(conflits), "missing": len(manquants)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
