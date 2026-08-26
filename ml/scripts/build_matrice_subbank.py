"""La SOUS-BANQUE d'ancres de la matrice d'encodeurs — décision D3.

Chantier ``juge-et-banc``, étape 4. Restreint la banque **servie** ``2eur_all``
aux classes du corpus d'évaluation, et replie ses ancres sur la **maille du
manifeste**. Rien n'est ré-encodé, rien n'est recalculé : on filtre et on
ré-étiquette des lignes qui existent déjà.

🔴 **La banque servie n'est jamais touchée** (D3). On écrit un artefact scopé
``state/foundation_anchors_<kind>__<encodeur>.npz`` via
``save_anchors(write_legacy=False)`` ; la review continue de lire
``foundation_anchors_2eur_all.npz`` sans savoir que ce script existe.

POURQUOI UNE SOUS-BANQUE, ET PAS LA BANQUE ENTIÈRE
---------------------------------------------------
``score_crops`` écarte les crops dont la classe n'est pas dans la banque
(``n_out_of_scope``), donc la banque entière **noterait** bien les 300 crops —
mais contre **671 distracteurs**, là où ArcFace n'en affronte que 60. On
mesurerait la taille des espaces de recherche, pas la qualité des encodeurs.

POURQUOI UNE FUSION, ET PAS UN SIMPLE FILTRE
----------------------------------------------
Parce que les deux mailles ne coïncident pas. ``bank_class_ids`` rend
``[eurio_id]`` pour toute **commémorative**, même membre d'un groupe de dessin
— or les **émissions communes européennes** sont exactement ça. Mesuré le
2026-08-26 sur la banque servie :

===================== ==========================
classe du manifeste    classes dans la banque
===================== ==========================
``eu-eu-flag-2015``    21
``eu-erasmus-2022``    19
``eu-euro-cash-2012``  18
``eu-emu-2009``        16
``eu-rome-2007``       13
===================== ==========================

Sans la fusion, DINO devrait désigner le bon **pays** parmi 21 dessins quasi
identiques, pendant qu'ArcFace — entraîné à la maille du produit — a raison
quoi qu'il dise. Fusionner n'appauvrit rien : une classe de banque porte
PLUSIEURS ancres par construction, et réunir 21 variantes nationales du même
dessin lui en donne simplement plus.

CE QUE CE SCRIPT REFUSE DE FAIRE
---------------------------------
Chacun de ces refus a une raison mesurée, et aucun n'est un avertissement :

* **une ancre qui est un crop d'éval** → le noter contre elle-même donnerait
  une similarité de 1,0. Vérifié à la construction ; la banque servie en
  contient **0** aujourd'hui (D5 les avait exclus du prélèvement), et ce garde
  existe pour que ça reste vrai après un rebuild ;
* **une classe du manifeste sans aucune ancre** → ses crops partiraient en
  ``n_out_of_scope`` et disparaîtraient du dénominateur. Un recall calculé sur
  55 classes présenté comme couvrant les 60 est un chiffre faux, pas partiel ;
* **un ``source_path`` absent du disque** → ``encode_paths`` le laisse tomber
  et l'ancre disparaît **en silence**. On préfère refuser avant ;
* **une maille de manifeste différente** de celle demandée → le garde d'espace
  de labels refuserait plus tard, après le calcul.

⚠️ **Les ``source_paths`` ne sont pas portables.** 751 des 893 ancres retenues
pointent le cache local (``~/.cache/eurio/enrichment-crops/…``). Cet artefact
est donc utilisable sur la machine qui l'a bâti ; ailleurs — et après une
éviction de cache — les chemins ne résolvent plus. C'est pourquoi l'existence
est vérifiée à la construction plutôt que supposée.

Usage ::

    python -m scripts.build_matrice_subbank            # dry-run (défaut)
    python -m scripts.build_matrice_subbank --apply
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parent.parent
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from review.bench_gold import load_gold, load_meta  # noqa: E402
from store import resolve_db_path  # noqa: E402

#: La banque SERVIE, source des lignes. Jamais réécrite.
SOURCE_KIND = "2eur_all"

#: Le ``kind`` de la sous-banque. Distinct de ``SOURCE_KIND`` : c'est ce qui
#: garantit que ``save_anchors`` ne peut pas viser le fichier servi.
SUBBANK_KIND = "matrice60"

DEFAULT_GOLD = _ML_DIR / "state" / "validation_gold" / "matrice_eval_gold.jsonl"


def _mesh_map(conn: sqlite3.Connection) -> dict[str, str]:
    """``{eurio_id: COALESCE(design_group_id, eurio_id)}`` — la maille produit."""
    return {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT eurio_id, COALESCE(design_group_id, eurio_id) FROM coins"
        )
    }


def restreindre(bank, *, classes: set[str], mesh: dict[str, str],
                eval_asset_ids: set[str]) -> dict:
    """Le plan de restriction, sans rien écrire.

    Rend ``{"garde": [indices], "par_classe": {...}, "fuites": [...],
    "sans_ancre": [...], "chemins_absents": [...]}``.
    """
    garde: list[int] = []
    fuites: list[str] = []
    chemins_absents: list[str] = []
    par_classe: collections.Counter = collections.Counter()

    for i, eid in enumerate(bank.eurio_ids):
        classe = mesh.get(eid, eid)
        if classe not in classes:
            continue
        aid = (bank.asset_ids[i] if i < len(bank.asset_ids) else None) or None
        if aid and aid in eval_asset_ids:
            # Une ancre qui EST un crop d'éval : similarité 1,0 avec elle-même.
            fuites.append(aid)
            continue
        sp = bank.source_paths[i] if i < len(bank.source_paths) else ""
        if not sp or not Path(sp).exists():
            chemins_absents.append(sp or f"<vide, ligne {i}>")
            continue
        garde.append(i)
        par_classe[classe] += 1

    return {
        "garde": garde,
        "par_classe": dict(par_classe),
        "fuites": fuites,
        "sans_ancre": sorted(classes - set(par_classe)),
        "chemins_absents": chemins_absents,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD,
                    help="le manifeste qui DÉFINIT les classes et la maille")
    ap.add_argument("--db", type=Path,
                    default=resolve_db_path(_ML_DIR / "state" / "eurio.replica.db"))
    ap.add_argument("--kind", default=SUBBANK_KIND)
    ap.add_argument("--apply", action="store_true",
                    help="écrit l'artefact (défaut = dry-run)")
    args = ap.parse_args(argv)

    if args.kind == SOURCE_KIND:
        print(f"!! --kind {SOURCE_KIND} écrirait sur la banque SERVIE. Refusé "
              f"(D3 : elle n'est pas touchée).", file=sys.stderr)
        return 2

    # ── Les classes viennent du MANIFESTE, jamais d'une seconde requête ──
    #
    # Le manifeste EST la définition figée du jeu et de sa maille. La
    # recalculer ici donnerait deux définitions concurrentes de « les 60
    # classes » — exactement le défaut que `bench_gold` a été écrit pour
    # supprimer, et qui avait fait diverger deux runs sans un mot.
    if not args.gold.exists():
        print(f"!! {args.gold} absent — lance d'abord "
              f"`python -m scripts.eval_corpus_gold build`.", file=sys.stderr)
        return 2
    gold = load_gold(args.gold)
    meta = load_meta(args.gold)
    classes = {r.class_id for r in gold}
    maille_gold = meta.get("mesh")
    if maille_gold != "design_group":
        print(f"!! le manifeste est à la maille {maille_gold!r} ; cette "
              f"sous-banque replie sur `design_group`. Les deux doivent "
              f"coïncider, sinon le garde d'espace de labels refusera APRÈS le "
              f"calcul. Rebâtis le manifeste avec --mesh design_group.",
              file=sys.stderr)
        return 2

    from training.foundation.anchors import AnchorBank, load_anchors, save_anchors

    base = load_anchors(SOURCE_KIND)
    if base is None:
        print(f"!! banque {SOURCE_KIND} introuvable — "
              f"`go-task ml:dino-anchors:build` d'abord.", file=sys.stderr)
        return 2

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        mesh = _mesh_map(conn)
        eval_asset_ids = {
            r[0] for r in conn.execute(
                "SELECT id FROM image_assets WHERE eval_corpus IS NOT NULL")
        }
    finally:
        conn.close()

    plan = restreindre(base, classes=classes, mesh=mesh,
                       eval_asset_ids=eval_asset_ids)
    garde = plan["garde"]
    n = sorted(plan["par_classe"].values())

    print(f"manifeste     : {args.gold.name}  "
          f"(gold_version={meta.get('gold_version')}, maille={maille_gold})")
    print(f"banque source : {SOURCE_KIND}  {base.count} ancres · "
          f"encoder={base.encoder_version} · bank_id={(base.bank_id or '?')[:12]}")
    print(f"classes visées: {len(classes)}")
    print(f"ancres gardées: {len(garde)} · classes couvertes : "
          f"{len(plan['par_classe'])}")
    if n:
        canon = sum(1 for i in garde
                    if not (base.asset_ids[i] if i < len(base.asset_ids) else None))
        print(f"ancres/classe : min {n[0]} · médiane {n[len(n) // 2]} · max {n[-1]}"
              f"  (canoniques {canon} · exemplaires réels {len(garde) - canon})")

    refus: list[str] = []
    if plan["fuites"]:
        refus.append(
            f"{len(plan['fuites'])} ancre(s) SONT des crops d'éval — elles se "
            f"noteraient elles-mêmes à similarité 1,0 : "
            f"{sorted(plan['fuites'])[:5]}"
        )
    if plan["sans_ancre"]:
        refus.append(
            f"{len(plan['sans_ancre'])} classe(s) du manifeste sans aucune "
            f"ancre — leurs crops partiraient en `out_of_scope` et "
            f"disparaîtraient du dénominateur : {plan['sans_ancre'][:5]}"
        )
    if plan["chemins_absents"]:
        refus.append(
            f"{len(plan['chemins_absents'])} source_path absent(s) du disque — "
            f"`encode_paths` les laisserait tomber EN SILENCE : "
            f"{plan['chemins_absents'][:3]}"
        )
    if refus:
        print("\n⛔ REFUS — rien n'a été écrit :", file=sys.stderr)
        for r in refus:
            print(f"   · {r}", file=sys.stderr)
        return 1

    print("✅ 0 fuite · 0 classe sans ancre · 0 chemin absent")

    if not args.apply:
        print("\nDRY-RUN — rien écrit. Relancer avec --apply.")
        print(json.dumps({"ancres": len(garde), "classes": len(plan["par_classe"]),
                          "dry_run": True}))
        return 0

    sous = AnchorBank(
        eurio_ids=[mesh.get(base.eurio_ids[i], base.eurio_ids[i]) for i in garde],
        matrix=base.matrix[garde],
        encoder_version=base.encoder_version,
        anchors_kind=args.kind,
        # `built_at` dit d'où ça vient : sans le bank_id de la source, on ne
        # saurait pas plus tard CONTRE QUELLE banque cette sous-banque a été
        # taillée, ni si celle-ci a été rebâtie depuis.
        built_at=f"{base.built_at} (sous-banque de {SOURCE_KIND} "
                 f"bank_id={(base.bank_id or '?')[:12]}, "
                 f"gold={meta.get('gold_version')})",
        source_paths=[base.source_paths[i] for i in garde],
        asset_ids=[(base.asset_ids[i] if i < len(base.asset_ids) else None)
                   for i in garde],
    )
    chemin = save_anchors(sous, write_legacy=False)
    print(f"\n→ {chemin}")
    print(json.dumps({"ancres": sous.count, "classes": len(plan["par_classe"]),
                      "dim": sous.dim, "kind": args.kind}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
