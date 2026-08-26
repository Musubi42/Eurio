"""CLI du manifeste d'un CORPUS D'ÉVALUATION — figer, inspecter.

    .venv/bin/python -m scripts.eval_corpus_gold build [--corpus C] [--out P] [--force]
    .venv/bin/python -m scripts.eval_corpus_gold show  [--out P]

``build`` REFUSE d'écraser un manifeste existant sans ``--force``, et affiche
d'abord ce qui changerait. Écraser un jeu figé sans savoir ce qu'on écrase,
c'est perdre la comparabilité qu'on essaie de gagner — même contrat que
``scripts/bench_gold.py``.

Le défaut de ``--db`` vient de ``store.resolve_db_path``, jamais d'un littéral :
la banque servie a été bâtie une fois sur ``state/eurio.db`` (base de travail
périmée, 6 205 ``image_assets`` contre 12 454 dans la réplique) parce qu'un
script avait ce chemin en dur — 57 classes déjà tranchées invisibles de la
banque, sans le moindre message d'erreur.

Ce CLI n'écrit **jamais en base** : il lit (``mode=ro``) et pose deux fichiers.
Aucune interaction avec le flip Direction A.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from review.bench_gold import (  # noqa: E402
    load_gold,
    load_meta,
    meta_path,
    save_gold,
)
from review.eval_corpus_gold import (  # noqa: E402
    MESHES,
    build_eval_gold,
    eval_gold_extra,
)
from store import resolve_db_path  # noqa: E402

#: Le corpus prélevé par ``scripts/select_eval_holdout.py`` (D1/D2).
DEFAULT_CORPUS = "matrice-encodeurs-2026-08"

DEFAULT_OUT = ML_DIR / "state" / "validation_gold" / "matrice_eval_gold.jsonl"


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _resume(rows, extra: dict) -> None:
    print(f"  crops              : {len(rows)}")
    print(f"  classes ({extra['mesh']}) : {len({r.class_id for r in rows})}")
    print(f"  eurio_id distincts : {len({r.truth_eurio_id for r in rows})}")
    print(f"  crops par classe   : {extra['n_crops_par_classe']}")
    if extra["classes_hors_quota"]:
        print(f"  ⚠️  hors quota      : {len(extra['classes_hors_quota'])} — "
              f"{extra['classes_hors_quota'][:5]}")
    # Ces deux-là ne sont jamais tus, même à zéro : leur absence de l'écran
    # serait indiscernable de « je n'ai pas regardé ».
    print(f"  sans décision review : {extra['n_sans_decision_review']}"
          f"{'  ⚠️ plancher de bruit à annoncer avec le chiffre' if extra['n_sans_decision_review'] else ''}")
    print(f"  non training_eligible: {extra['n_non_training_eligible']}"
          f"{'  ⚠️ la review a dégradé un crop APRÈS son entrée' if extra['n_non_training_eligible'] else ''}")


def _diff_contre_fige(rows, ancien) -> None:
    """Ce qui changerait, ligne à ligne. Le pendant minimal de ``diff_gold``."""
    a = {r.asset_id: r for r in ancien}
    n = {r.asset_id: r for r in rows}
    ajoutes = sorted(set(n) - set(a))
    retires = sorted(set(a) - set(n))
    verites = [(k, a[k].truth_eurio_id, n[k].truth_eurio_id)
               for k in sorted(set(a) & set(n))
               if a[k].truth_eurio_id != n[k].truth_eurio_id]
    classes = [(k, a[k].class_id, n[k].class_id)
               for k in sorted(set(a) & set(n))
               if a[k].class_id != n[k].class_id]
    print(f"  + {len(ajoutes)} ajoutés   - {len(retires)} retirés   "
          f"~ {len(verites)} vérités changées   "
          f"# {len(classes)} classes de banque changées   "
          f"= {len(set(a) & set(n)) - len(verites) - len(classes)} stables")
    # Une classe de banque qui bouge SANS que la vérité bouge change ce que le
    # banc mesure, et c'est le genre d'écart qui passe inaperçu.
    for marque, lot in (("~", verites), ("#", classes)):
        for k, avant, apres in lot[:20]:
            print(f"    {marque} {k}  {avant} → {apres}")
        if len(lot) > 20:
            print(f"    … et {len(lot) - 20} autres")


def cmd_build(args: argparse.Namespace) -> int:
    out = Path(args.out)
    conn = _connect(Path(args.db))
    try:
        rows = build_eval_gold(conn, args.corpus, mesh=args.mesh)
    finally:
        conn.close()

    if not rows:
        print(f"!! aucun crop marqué `eval_corpus = {args.corpus!r}` dans "
              f"{args.db}. Le prélèvement a-t-il été appliqué "
              f"(`scripts.select_eval_holdout --apply`) et la réplique tirée ?",
              file=sys.stderr)
        return 2

    extra = eval_gold_extra(rows, args.corpus, mesh=args.mesh, db_path=str(args.db))
    print(f"corpus {args.corpus} — maille {args.mesh} — depuis {args.db}")
    _resume(rows, extra)

    if out.exists():
        try:
            ancien = load_gold(out)
        except ValueError as exc:
            ancien = None
            print(f"!! {out} n'a pas le schéma courant de GoldCrop : {exc}",
                  file=sys.stderr)
        if not args.force:
            print(f"\n!! {out} existe déjà. Ce qui changerait :", file=sys.stderr)
            if ancien is None:
                print("   (diff impossible : schéma incomparable)", file=sys.stderr)
            else:
                _diff_contre_fige(rows, ancien)
            print("   Relance avec --force pour l'écraser.", file=sys.stderr)
            return 2
        print(f"\n-- écrasement de {out}. Ce qui change :")
        if ancien is not None:
            _diff_contre_fige(rows, ancien)

    meta = save_gold(rows, out, meta_extra=extra)
    print(f"\n→ {out}")
    print(f"→ {meta_path(out)}  gold_version={meta['gold_version']}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if not out.exists():
        print(f"!! {out} absent — lance `build` d'abord.", file=sys.stderr)
        return 2
    print(json.dumps(load_meta(out), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="fige le manifeste du corpus")
    b.add_argument("--corpus", default=DEFAULT_CORPUS)
    b.add_argument("--mesh", choices=MESHES, default="design_group",
                   help="la maille de `class_id` — donc ce que le banc "
                        "comparera. `design_group` (défaut) est la maille du "
                        "produit et celle d'ArcFace ; `bank` est celle de la "
                        "banque d'ancres, qui éclate les émissions communes "
                        "européennes par pays (jusqu'à 21 classes pour un seul "
                        "dessin) et fabriquerait un handicap.")
    b.add_argument("--db", type=Path,
                   default=resolve_db_path(ML_DIR / "state" / "eurio.replica.db"))
    b.add_argument("--out", type=Path, default=DEFAULT_OUT)
    b.add_argument("--force", action="store_true",
                   help="écrase un manifeste existant (affiche le diff avant)")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("show", help="affiche le sidecar du manifeste")
    s.add_argument("--out", type=Path, default=DEFAULT_OUT)
    s.set_defaults(func=cmd_show)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
