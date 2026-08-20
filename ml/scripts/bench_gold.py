"""CLI du gold de banc d'encodeurs (P4) — figer, inspecter, differ.

    .venv/bin/python -m scripts.bench_gold build [--db PATH] [--out PATH] [--force]
    .venv/bin/python -m scripts.bench_gold show  [--gold PATH]
    .venv/bin/python -m scripts.bench_gold diff  [--db PATH] [--gold PATH]

`build` REFUSE d'écraser un gold existant sans `--force`, et affiche d'abord le
diff base↔gold : écraser un jeu figé sans savoir ce qui change, c'est perdre la
comparabilité qu'on essaie justement de gagner.

Le défaut de `--db` vient de `store.resolve_db_path`, jamais d'un littéral. La
banque `2eur_all` servie aujourd'hui a été bâtie sur `state/eurio.db` (base de
travail périmée : 6 205 `image_assets` contre 12 454 dans la réplique) parce
qu'un script avait ce chemin en dur — 57 classes de review déjà tranchée
invisibles de la banque, sans le moindre message d'erreur. Cf. l'en-tête de
`ml/scripts/build_dino_anchors.py`.

Ce CLI n'écrit **jamais en base** : il lit (`mode=ro`) et pose un fichier.
Aucune interaction avec le flip Direction A.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from review.bench_gold import (  # noqa: E402
    DEFAULT_GOLD,
    build_gold,
    diff_gold,
    load_gold,
    load_meta,
    meta_path,
    save_gold,
)
from store import resolve_db_path  # noqa: E402

# Défaut de `--db` : la base que le RESTE de la machine lit (`EURIO_DB_PATH`,
# la réplique sous Direction A) — pas `state/eurio.db` codé en dur.
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _print_diff(d: dict, stream=None) -> None:
    # `stream` explicite : le refus d'écrasement parle sur stderr, et mélanger
    # les deux flux fait apparaître le diff APRÈS le message qui l'annonce.
    # Résolu à l'APPEL (pas en défaut d'argument) : pytest remplace `sys.stdout`
    # après l'import, un défaut lié à la définition capturerait un flux mort.
    out = stream if stream is not None else sys.stdout
    p = lambda s: print(s, file=out)  # noqa: E731
    p(f"  + {len(d['added'])} ajoutés   "
      f"- {len(d['removed'])} retirés   "
      f"~ {len(d['truth_changed'])} vérités changées   "
      f"# {len(d['class_changed'])} classes de banque changées   "
      f"= {d['n_stable']} stables")
    # Les deux listes sont imprimées : une classe de banque qui bouge sans que
    # la vérité bouge change ce que le banc mesure, et c'était muet.
    for marque, cle in (("~", "truth_changed"), ("#", "class_changed")):
        for c in d[cle][:20]:
            p(f"    {marque} {c['asset_id']}  {c['was']} → {c['now']}")
        if len(d[cle]) > 20:
            p(f"    … et {len(d[cle]) - 20} autres ({cle})")
    p(f"  version figée : {d['gold_version_frozen']}   "
      f"version base : {d['gold_version_current']}")


def cmd_build(args: argparse.Namespace) -> int:
    out = Path(args.out)
    conn = _connect(Path(args.db))
    try:
        rows = build_gold(conn)
        if out.exists():
            # Un gold d'un AUTRE schéma (champ ajouté ou retiré) ne se charge
            # pas — `load_gold` refuse bruyamment. Ce n'est pas une raison de
            # rendre une traceback : on le dit, et on garde le même contrat
            # (refus sans --force, écrasement avec).
            try:
                ancien = load_gold(out)
            except ValueError as exc:
                ancien = None
                print(f"!! {out} n'a pas le schéma courant de GoldCrop : {exc}",
                      file=sys.stderr)
            if not args.force:
                print(f"!! {out} existe déjà. Diff base↔gold :", file=sys.stderr)
                if ancien is None:
                    print("   (diff impossible : schéma incomparable)", file=sys.stderr)
                else:
                    _print_diff(diff_gold(conn, ancien), sys.stderr)
                print("   Relance avec --force pour l'écraser.", file=sys.stderr)
                return 2
            print(f"-- écrasement de {out}. Diff base↔gold :")
            if ancien is None:
                print("   (diff impossible : schéma incomparable)")
            else:
                _print_diff(diff_gold(conn, ancien))
    finally:
        conn.close()

    meta = save_gold(rows, out, meta_extra={"db_path": str(args.db)})
    print(f"→ {out}  ({meta['n_crops']} crops · {meta['n_classes']} classes de "
          f"banque · {meta['n_truth_eurio_ids']} eurio_id · "
          f"{meta['n_training_eligible']} training_eligible)")
    print(f"→ {meta_path(out)}  gold_version={meta['gold_version']}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    gold = Path(args.gold)
    if not gold.exists():
        print(f"!! {gold} absent — lance `build` d'abord.", file=sys.stderr)
        return 2
    rows = load_gold(gold)
    meta = load_meta(gold) if meta_path(gold).exists() else {}
    print(json.dumps(
        {k: v for k, v in meta.items() if k != "selection_sql"},
        ensure_ascii=False, indent=2, sort_keys=True,
    ))
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r.review_kind or "?"] = kinds.get(r.review_kind or "?", 0) + 1
    print(f"\n{len(rows)} crops · par kind : {kinds}")
    print(f"training_eligible=1 : {sum(1 for r in rows if r.training_eligible)}")
    remapped = sum(1 for r in rows if r.class_id != r.truth_eurio_id)
    print(f"class_id ≠ truth_eurio_id (groupes de dessin) : {remapped} crops")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    gold = Path(args.gold)
    if not gold.exists():
        print(f"!! {gold} absent — lance `build` d'abord.", file=sys.stderr)
        return 2
    conn = _connect(Path(args.db))
    try:
        d = diff_gold(conn, load_gold(gold))
    finally:
        conn.close()
    _print_diff(d)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bench_gold", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="fige le gold depuis la base")
    b.add_argument("--db", default=str(DB_PATH))
    b.add_argument("--out", default=str(DEFAULT_GOLD))
    b.add_argument("--force", action="store_true",
                   help="écrase un gold existant (affiche le diff avant)")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("show", help="résume le gold figé")
    s.add_argument("--gold", default=str(DEFAULT_GOLD))
    s.set_defaults(func=cmd_show)

    d = sub.add_parser("diff", help="compare le gold figé à la base")
    d.add_argument("--db", default=str(DB_PATH))
    d.add_argument("--gold", default=str(DEFAULT_GOLD))
    d.set_defaults(func=cmd_diff)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
