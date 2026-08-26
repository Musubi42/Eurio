"""Prélève le JEU D'ÉVALUATION de la matrice d'encodeurs, et le marque.

Chantier ``juge-et-banc``, étape 2. Départager ArcFace et DINO exige des images
que **ni l'un ni l'autre** n'a vues. Ce script les choisit, puis pousse le
marquage ``image_assets.eval_corpus`` au canonique (``POST
/ingest/eval-corpus``) — le calcul reste où sont les mesures, seules les lignes
voyagent (même doctrine que ``backfill_quality_score``).

La règle, en une phrase — version 3, 2026-08-26
================================================

**5 crops au hasard par classe, graine fixe, parmi ceux dont ni la photo brute
ni le vendeur ne portent d'ancre de cette classe.** C'est tout.

Pourquoi la v1 (quantiles de tilt) a été jetée
-----------------------------------------------

Elle prétendait sélectionner des images **plus dures** — « la dégradation
visée est géométrique, et elle se mesure sans aucun modèle appris,
``tilt_deg`` ». Mesuré le 2026-08-26 sur ``dinov2_vitb14``, à contamination
vendeur contrôlée :

====================================================== ===== =======
population                                                 n     r@1
====================================================== ===== =======
jeu d'éval — la moitié la plus inclinée, choisie par v1   178   94,9 %
reste du pool — ce que la v1 n'a PAS pris                 792   91,2 %
====================================================== ===== =======

Le jeu « dur » était **3,7 points plus FACILE** que ce qu'il écartait. Et à
l'intérieur du jeu, le quartile le plus incliné était le MEILLEUR (98,7 %
contre 94,7 %). Aucun des trois signaux disponibles (``tilt_deg``,
``tilt_trustworthy``, ``quality_score``) ne prédit la difficulté ; le seul qui
s'en approche est **inversé** (``quality_score`` haut = 87,8 %, bas = 93,1 %).

Une règle qui trie sur un signal qui ne trie rien n'est pas neutre : elle
introduit un biais qu'on ne sait pas nommer, tout en donnant l'impression du
contrôle. **Le tirage au hasard, lui, ne ment pas** — il est le seul estimateur
non biaisé de la population dont il sort. On y revient tant qu'aucun signal de
difficulté n'est démontré.

Les deux gardes conservés, et ils sont mesurés
-----------------------------------------------

**Le vendeur.** Un crop dont le ``seller_id`` porte aussi une ancre de sa
classe partage le fond, la lumière et la session avec la référence contre
laquelle il est noté :

====================================================== ===== =======
population (60 classes, hors ancres)                       n     r@1
====================================================== ===== =======
vendeur portant aussi une ancre de la classe              364   96,2 %
vendeur n'apparaissant nulle part                         791   91,2 %
====================================================== ===== =======

**+5,0 points, z ≈ 3,05, p ≈ 0,002** — le seul effet franchement significatif
mesuré ce jour-là. Et il était exigé depuis des mois :
``docs/research/ml-scalability-phases/phase-4-subcenter-evalbench.md:40`` —
*« des photos du même vendeur/lot eBay partagent du contexte… split par
lot/seller, pas par photo individuelle. »*

Ce que ce garde coûte, mesuré : à 5/classe, **52 des 60 classes** tiennent
(3 classes n'ont AUCUN crop non contaminé). ``--no-seller-guard`` le retire et
rend les 60 classes, au prix d'un chiffre gonflé d'environ 5 points.
``--no-dup-guard`` retire le garde photo, au prix d'environ 0,5 point.

**La photo brute** — le quasi-doublon. Un crop dont le ``source_image_id``
porte aussi une ancre de sa classe n'est pas « une autre photo du même
vendeur » : c'est *presque la même image*, recadrée ailleurs dans le même
fichier. Mesuré le 2026-08-26 sur les 300 crops du corpus v1 : **36/300
(12 %)**, tous justes sous ``vitb14`` (100 % contre 95,8 % pour les autres),
soit **+0,5 pt** d'inflation sur le total.

⚠️ **Ce garde n'est pas un doublon du précédent, et c'est mesurable.** Deux
crops issus du même ``source_image_id`` partagent forcément leur
``seller_id`` — donc le garde vendeur les attrape *quand ce vendeur est
connu*. Il ne l'est pas toujours : ``_ANCHOR_SELLERS_SQL`` exige
``si.seller_id IS NOT NULL``, et un listing sans vendeur renseigné passe
entre les mailles. Le garde photo, lui, joint sur une clé ``NOT NULL``. Il
reste donc actif sous ``--no-seller-guard``, et c'est voulu : les deux
répondent à deux questions (« même séance ? » / « même fichier ? ») dont
seule la seconde a une réponse certaine.

Le hasard est REJOUABLE, et par classe
---------------------------------------

La graine est ``f"{seed}:{class_id}"``, pas ``seed`` seul. Conséquence voulue :
quand le pool d'une classe grossit, **seule cette classe re-tire**. Une graine
globale ferait bouger les 60 tirages à chaque nouveau crop scrapé, et deux
prélèvements à deux semaines d'écart n'auraient plus rien en commun sans que
personne ne l'ait décidé.

Les biais qui restent — il y en a toujours
-------------------------------------------

* le jeu est **représentatif du pool eBay éligible**, pas de ce que
  photographie un utilisateur. Personne n'a démontré que les deux coïncident ;
* les ancres de la banque servie sont exclues (les noter contre elles-mêmes
  donnerait 1,0), ce qui retire au pool une partie de sa diversité d'apparence
  — le FPS les avait choisies pour ça ;
* le garde vendeur ne couvre pas le cas « deux vendeurs, une même photo
  volée », qui existe sur eBay et que rien ici ne détecte.

Usage ::

    python -m scripts.select_eval_holdout                    # dry-run (défaut)
    python -m scripts.select_eval_holdout --plan out.json    # dry-run + plan
    python -m scripts.select_eval_holdout --apply            # marque et pousse
"""

from __future__ import annotations

import argparse
import json
import random
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
#: v1 = quantiles de tilt (jetée, cf. en-tête). v2 = 5 au hasard + garde
#: vendeur. v3 = v2 + garde photo brute (quasi-doublons, +0,5 pt mesuré).
SELECTION_RULE_VERSION = 3

#: La graine du tirage. Elle est COMBINÉE au class_id, jamais utilisée seule.
DEFAULT_SEED = 20260826

DEFAULT_QUOTA = 5

#: La banque SERVIE. Ses ancres sont exclues du prélèvement : les noter contre
#: elle mesurerait une similarité de 1,0 avec elles-mêmes.
SERVED_ANCHORS_KIND = "2eur_all"

_POOL_SQL = """
    SELECT COALESCE(co.design_group_id, co.eurio_id) AS class_id,
           a.id                                      AS asset_id,
           a.eurio_id                                AS eurio_id,
           a.storage_path                            AS storage_path,
           a.source_image_id                         AS source_image_id,
           si.seller_id                              AS seller_id,
           (a.id IN (SELECT asset_id FROM dino_class_references
                      WHERE anchors_kind = :kind AND asset_id IS NOT NULL))
                                                     AS est_ancre
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

#: Les photos BRUTES qui portent une ancre, PAR CLASSE. C'est le garde de la
#: v3 — et il joint sur `image_assets.source_image_id`, qui est `NOT NULL` :
#: contrairement au garde vendeur, il n'a pas de maille par laquelle fuir.
_ANCHOR_SOURCE_IMAGES_SQL = """
    SELECT COALESCE(co.design_group_id, co.eurio_id) AS class_id,
           a.source_image_id                         AS source_image_id
      FROM dino_class_references r
      JOIN image_assets a   ON a.id = r.asset_id
      JOIN coins co         ON co.eurio_id = a.eurio_id
     WHERE r.anchors_kind = :kind
       AND r.asset_id IS NOT NULL
"""

#: Les vendeurs qui portent une ancre, PAR CLASSE. C'est le garde de D5 v2.
_ANCHOR_SELLERS_SQL = """
    SELECT COALESCE(co.design_group_id, co.eurio_id) AS class_id,
           si.seller_id                              AS seller_id
      FROM dino_class_references r
      JOIN image_assets a   ON a.id = r.asset_id
      JOIN source_images si ON si.id = a.source_image_id
      JOIN coins co         ON co.eurio_id = a.eurio_id
     WHERE r.anchors_kind = :kind
       AND r.asset_id IS NOT NULL
       AND si.seller_id IS NOT NULL
"""


def tirage(candidats: list, quota: int, *, seed: int, class_id: str) -> list:
    """``quota`` candidats tirés au hasard, de façon REJOUABLE.

    La graine est ``f"{seed}:{class_id}"`` et non ``seed`` seul : quand le pool
    d'une classe grossit, seule cette classe re-tire. Une graine globale ferait
    bouger les 60 tirages à chaque crop scrapé.

    ``candidats`` doit être trié (ordre total) avant l'appel — sinon l'ordre de
    la liste dépend de celui du curseur SQL et le « rejouable » est un mot.
    """
    if len(candidats) <= quota:
        return list(candidats)
    rng = random.Random(f"{seed}:{class_id}")
    return rng.sample(candidats, quota)


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
    seed: int = DEFAULT_SEED,
    seller_guard: bool = True,
    dup_guard: bool = True,
    anchors_kind: str = SERVED_ANCHORS_KIND,
) -> dict:
    """Rend le plan de prélèvement, sans rien écrire.

    ``{"classes": [...], "picks": [...], "rejets": {...}}``.

    Deux refus, et ils ne disent pas la même chose :

    * ``plancher`` — prélever ferait passer ce qui RESTE au train sous
      ``min_real``. Le quota se raisonne sur le reste, jamais sur ce qu'on prend
      (``real_training_sources`` est partagé par le bake ET le préflight) ;
    * ``pool_candidat_court`` — après retrait des ancres et, si les gardes sont
      actifs, des crops issus de la photo brute d'une ancre puis de ceux du
      vendeur d'une ancre, il ne reste pas ``quota`` candidats. Mesuré le
      2026-08-26 (garde vendeur seul) : 8 classes sur 60, dont 3 à ZÉRO
      candidat propre.

    Les deux gardes sont indépendants — cf. l'en-tête du module : le garde
    photo tient là où le garde vendeur fuit (``seller_id`` nullable).
    """
    vendeurs_ancres: dict[str, set[str]] = {}
    if seller_guard:
        for r in conn.execute(_ANCHOR_SELLERS_SQL, {"kind": anchors_kind}):
            vendeurs_ancres.setdefault(r["class_id"], set()).add(r["seller_id"])

    photos_ancres: dict[str, set[str]] = {}
    if dup_guard:
        for r in conn.execute(_ANCHOR_SOURCE_IMAGES_SQL, {"kind": anchors_kind}):
            photos_ancres.setdefault(r["class_id"], set()).add(r["source_image_id"])

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

        cands = [r for r in rows if not r["est_ancre"]]
        n_hors_ancres = len(cands)

        # Garde photo brute d'abord : il joint sur une clé NOT NULL, donc son
        # verdict ne dépend d'aucun champ optionnel. Le compter en premier rend
        # aussi les deux compteurs lisibles — `n_ecartes_vendeur` ne dit alors
        # que ce que le vendeur a écarté EN PLUS du quasi-doublon.
        photos_interdites = photos_ancres.get(class_id, set())
        if dup_guard:
            cands = [r for r in cands
                     if r["source_image_id"] not in photos_interdites]
        n_hors_doublons = len(cands)

        interdits = vendeurs_ancres.get(class_id, set())
        if seller_guard:
            cands = [r for r in cands if r["seller_id"] not in interdits]

        # Ordre TOTAL avant tirage : sans lui, l'ordre vient du curseur SQL et
        # « rejouable » n'est qu'un mot.
        cands.sort(key=lambda r: r["asset_id"])
        if len(cands) < quota:
            rejets["pool_candidat_court"].append(class_id)
            continue

        choisis = tirage(cands, quota, seed=seed, class_id=class_id)
        choisis.sort(key=lambda r: r["asset_id"])

        classes.append({
            "class_id": class_id,
            "n_train_avant": n_train,
            "n_train_apres": n_train - quota,
            "n_candidats": len(cands),
            "n_ancres_ecartees": n_train - n_hors_ancres,
            "n_ecartes_doublon": n_hors_ancres - n_hors_doublons,
            "n_ecartes_vendeur": n_hors_doublons - len(cands),
        })
        for r in choisis:
            picks.append({
                "asset_id": r["asset_id"],
                "class_id": class_id,
                "eurio_id": r["eurio_id"],
                "storage_path": r["storage_path"],
                "seller_id": r["seller_id"],
            })
    return {"classes": classes, "picks": picks, "rejets": rejets}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path,
                    default=resolve_db_path(_ML_DIR / "state" / "eurio.replica.db"))
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--quota", type=int, default=DEFAULT_QUOTA)
    ap.add_argument("--min-real", type=int, default=MIN_REAL)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help="graine du tirage ; combinée au class_id, jamais "
                         "utilisée seule (cf. §Le hasard est rejouable)")
    ap.add_argument("--no-seller-guard", action="store_true",
                    help="retire le garde vendeur. Rend les 60 classes au lieu "
                         "de 52, au prix d'un chiffre gonflé d'environ 5 points "
                         "(mesuré : +5,0 pts, p ≈ 0,002)")
    ap.add_argument("--no-dup-guard", action="store_true",
                    help="retire le garde quasi-doublon (crop issu de la MÊME "
                         "photo brute qu'une ancre de sa classe), au prix "
                         "d'environ +0,5 pt (mesuré : 36/300, tous justes)")
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
        seed=args.seed,
        seller_guard=not args.no_seller_guard,
        dup_guard=not args.no_dup_guard,
    )
    conn.close()

    plan["corpus"] = args.corpus
    plan["quota"] = args.quota
    plan["min_real"] = args.min_real
    plan["selection_rule_version"] = SELECTION_RULE_VERSION
    plan["seed"] = args.seed
    plan["seller_guard"] = not args.no_seller_guard
    plan["dup_guard"] = not args.no_dup_guard

    print(f"DB (lecture seule) : {args.db}")
    print(f"corpus             : {args.corpus} (règle v{SELECTION_RULE_VERSION})")
    print(f"classes retenues   : {len(plan['classes'])}")
    print(f"crops prélevés     : {len(plan['picks'])}")
    for motif, ids in plan["rejets"].items():
        if ids:
            print(f"écartées ({motif}) : {len(ids)} — {ids[:8]}"
                  f"{' …' if len(ids) > 8 else ''}")
    print(f"garde vendeur      : {'ACTIF' if plan['seller_guard'] else '⚠️ RETIRÉ'}"
          f" · garde doublon : {'ACTIF' if plan['dup_guard'] else '⚠️ RETIRÉ'}"
          f" · graine {args.seed}")
    if plan["classes"]:
        ecartes = sum(c["n_ecartes_vendeur"] for c in plan["classes"])
        doublons = sum(c["n_ecartes_doublon"] for c in plan["classes"])
        ancres = sum(c["n_ancres_ecartees"] for c in plan["classes"])
        print(f"écartés du tirage  : {ancres} ancres · {doublons} quasi-doublons "
              f"· {ecartes} par le vendeur")

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
