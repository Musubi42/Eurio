"""Patch i18n + aliases du coin Ghent (BE 2017) — suite Chunk 2b.

Le split BE 2017 a laissé deux trous côté theme-matcher :

  1. La pièce `…-of-ghent` (générée depuis Numista 124813) n'a aucune
     entrée `coin_names_i18n` ni `coin_aliases` → le matcher ne peut pas
     l'attribuer, tout retombe sur `…-of-liege`.
  2. Les 4 alias de `…-of-liege` sont en réalité les variantes du nom de
     Ghent (`gent`/`ghent`/`gand`/`gante`) — héritées de l'ancien slug
     `…-ghent-university`. Elles polluent Liège (une annonce « Gent »
     matchait Liège). Elles doivent migrer vers Ghent.

Ce patch est **ciblé sur cette pièce**. La génération i18n des 147 autres
pièces créées au Chunk 2b sera un chantier séparé (multi-agent).

Idempotent : `INSERT OR IGNORE` côté i18n, `UPDATE … WHERE` côté aliases.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from state.store import Store  # noqa: E402

GHENT = "be-2017-2eur-200-years-of-the-university-of-ghent"
LIEGE = "be-2017-2eur-200-years-of-the-university-of-liege"

# Titres Numista-style — fr/en miroitent le format des titres canoniques
# Numista déjà présents sur Liège ; de/it/es/nl sont les traductions standards
# acceptées (LLM-assisted, même pattern que les 2026 autres lignes assisted).
GHENT_I18N = [
    # (lang, title, source, method, confidence, model)
    # P.3b : split source/method. Source = registry id (manual ou numista_api),
    # method capture le pipeline ('llm_v1' pour les traductions LLM).
    ("fr", "2 euros Université de Gand",                              "manual",      None,    "manual",   None),
    ("en", "2 Euros - Philippe 200 years of the University of Ghent", "numista_api", None,    "canon",    None),
    ("de", "2 Euro Universität Gent",                                  "numista_api", "llm_v1", "assisted", "claude-opus-4-7"),
    ("es", "2 Euros Universidad de Gante",                             "numista_api", "llm_v1", "assisted", "claude-opus-4-7"),
    ("it", "2 Euro Università di Gand",                                "numista_api", "llm_v1", "assisted", "claude-opus-4-7"),
    ("nl", "2 Euro Universiteit Gent",                                 "numista_api", "llm_v1", "assisted", "claude-opus-4-7"),
]


def patch(store: Store, *, dry_run: bool) -> dict:
    conn = store._connection()  # noqa: SLF001
    before_ghent_i18n = conn.execute(
        "SELECT count(*) FROM coin_names_i18n WHERE eurio_id=?", (GHENT,)
    ).fetchone()[0]
    before_liege_aliases = conn.execute(
        "SELECT count(*) FROM coin_aliases WHERE eurio_id=?", (LIEGE,)
    ).fetchone()[0]

    summary = {
        "dry_run": dry_run,
        "before": {"ghent_i18n": before_ghent_i18n, "liege_aliases": before_liege_aliases},
        "actions": [
            f"INSERT {len(GHENT_I18N)} i18n rows on {GHENT}",
            f"MOVE aliases ({before_liege_aliases}) from {LIEGE} to {GHENT}",
        ],
    }
    if dry_run:
        return summary

    conn.execute("BEGIN")
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO coin_names_i18n "
            "(eurio_id, lang, title, source, method, confidence, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(GHENT, lang, title, src, method, conf, model)
             for lang, title, src, method, conf, model in GHENT_I18N],
        )
        # Les aliases gent/ghent/gand/gante sont des surface forms du NOM GHENT
        # → migrent du coin Liège (où elles étaient mal posées) vers le coin Ghent.
        # PK est (eurio_id, lang, alias) — pas de collision puisque Ghent en a 0.
        conn.execute(
            "UPDATE coin_aliases SET eurio_id=? WHERE eurio_id=?", (GHENT, LIEGE)
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    summary["after"] = {
        "ghent_i18n": conn.execute(
            "SELECT count(*) FROM coin_names_i18n WHERE eurio_id=?", (GHENT,)
        ).fetchone()[0],
        "ghent_aliases": conn.execute(
            "SELECT count(*) FROM coin_aliases WHERE eurio_id=?", (GHENT,)
        ).fetchone()[0],
        "liege_aliases": conn.execute(
            "SELECT count(*) FROM coin_aliases WHERE eurio_id=?", (LIEGE,)
        ).fetchone()[0],
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", type=Path, default=ROOT / "state" / "eurio.db")
    args = ap.parse_args(argv)
    import json as _json
    print(_json.dumps(patch(Store(args.db), dry_run=args.dry_run), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
