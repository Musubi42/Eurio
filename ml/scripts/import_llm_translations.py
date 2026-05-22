"""Importe les traductions LLM (DE/IT/ES/NL) dans ``coin_names_i18n``.

Les traductions sont produites par Claude Code lui-même, batch par
batch (cf. runbook ``docs/sources-refacto/ebay-multi-marketplace/
i18n-llm-translation.md``), et appendées à ``state/i18n_llm_results.jsonl``
au format :

    {"eurio_id": "...", "lang": "de", "title": "...", "confidence": "assisted"}

`confidence` ∈ {assisted, uncertain}. Ce script lit le JSONL et upsert
dans ``coin_names_i18n`` avec ``source='llm_v1'`` + ``model``.

Idempotent (``INSERT OR REPLACE``) — ré-importer le JSONL complet à
chaque session est sûr.

Usage::

    python -m scripts.import_llm_translations
    python -m scripts.import_llm_translations --dry-run
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "claude-opus-4-7"
RESULTS = ROOT / "state" / "i18n_llm_results.jsonl"
DB_PATH = ROOT / "state" / "eurio.db"

VALID_LANGS = {"de", "it", "es", "nl"}
VALID_CONFIDENCE = {"assisted", "uncertain"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(RESULTS))
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.results)
    if not path.exists():
        print(f"Aucun fichier {path} — rien à importer.")
        return 0

    rows: list[tuple[str, str, str, str]] = []
    errors = 0
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            eurio_id, lang = d["eurio_id"], d["lang"]
            title = d["title"].strip()
            confidence = d.get("confidence", "assisted")
        except (json.JSONDecodeError, KeyError, AttributeError) as exc:
            print(f"  !! ligne {n} invalide: {exc}", file=sys.stderr)
            errors += 1
            continue
        if lang not in VALID_LANGS:
            print(f"  !! ligne {n}: lang {lang!r} hors {VALID_LANGS}", file=sys.stderr)
            errors += 1
            continue
        if confidence not in VALID_CONFIDENCE:
            confidence = "uncertain"
        if not title:
            print(f"  !! ligne {n}: titre vide ({eurio_id}/{lang})", file=sys.stderr)
            errors += 1
            continue
        rows.append((eurio_id, lang, title, confidence))

    print(f"{len(rows)} traductions lues depuis {path.name} ({errors} erreurs)")
    if args.dry_run:
        for r in rows[:10]:
            print(f"  [dry] {r[0]} [{r[1]}] → {r[2]!r} ({r[3]})")
        if len(rows) > 10:
            print(f"  … +{len(rows) - 10}")
        return 0

    conn = sqlite3.connect(args.db)
    for eurio_id, lang, title, confidence in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO coin_names_i18n
                (eurio_id, lang, title, source, confidence, model)
            VALUES (?, ?, ?, 'llm_v1', ?, ?)
            """,
            (eurio_id, lang, title, confidence, MODEL),
        )
    conn.commit()

    cov = dict(conn.execute(
        "SELECT lang, count(*) FROM coin_names_i18n "
        "WHERE source='llm_v1' GROUP BY lang"
    ).fetchall())
    conn.close()
    print(f"upserted {len(rows)} rows. Couverture llm_v1 par lang: {cov}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
