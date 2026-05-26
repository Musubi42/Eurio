"""Importe les traductions LLM de commemorated_topic (DE/IT/ES/NL) dans
``coin_topics`` (source=numista_api ou bce_official selon JSONL).

Pendant les traductions inline par Claude Code (Opus 4.7), on append
à ``state/i18n_llm_topics.jsonl`` au format :

    {"eurio_id": "fi-2017-...", "source": "numista_api", "lang": "de",
     "topic": "100 Jahre Unabhängigkeit", "confidence": "assisted"}

`source` ∈ {numista_api, bce_official}. `confidence` ∈ {assisted, uncertain}.
Idempotent — ré-importer le JSONL complet est sûr (INSERT OR REPLACE
+ skip FK orphans pour les renames passés).

Usage::

    .venv/bin/python -m scripts.import_llm_topics
    .venv/bin/python -m scripts.import_llm_topics --dry-run
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "claude-opus-4-7"
RESULTS = ROOT / "state" / "i18n_llm_topics.jsonl"
DB_PATH = ROOT / "state" / "eurio.db"

VALID_LANGS = {"de", "it", "es", "nl"}
VALID_SOURCES = {"numista_api", "bce_official"}
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

    rows: list[tuple[str, str, str, str, str]] = []  # eurio_id, source, lang, topic, confidence
    errors = 0
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            eurio_id = d["eurio_id"]
            source = d["source"]
            lang = d["lang"]
            topic = d["topic"].strip()
            confidence = d.get("confidence", "assisted")
        except (json.JSONDecodeError, KeyError, AttributeError) as exc:
            print(f"  !! ligne {n} invalide: {exc}", file=sys.stderr)
            errors += 1
            continue
        if lang not in VALID_LANGS:
            print(f"  !! ligne {n}: lang {lang!r} hors {VALID_LANGS}", file=sys.stderr)
            errors += 1
            continue
        if source not in VALID_SOURCES:
            print(f"  !! ligne {n}: source {source!r} hors {VALID_SOURCES}", file=sys.stderr)
            errors += 1
            continue
        if confidence not in VALID_CONFIDENCE:
            confidence = "uncertain"
        if not topic:
            print(f"  !! ligne {n}: topic vide ({eurio_id}/{source}/{lang})", file=sys.stderr)
            errors += 1
            continue
        rows.append((eurio_id, source, lang, topic, confidence))

    print(f"{len(rows)} traductions topics lues depuis {path.name} ({errors} erreurs)")
    if args.dry_run:
        for r in rows[:10]:
            print(f"  [dry] {r[0]} [{r[1]}/{r[2]}] → {r[3]!r} ({r[4]})")
        if len(rows) > 10:
            print(f"  … +{len(rows) - 10}")
        return 0

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    n_inserted = 0
    n_orphan = 0
    for eurio_id, source, lang, topic, confidence in rows:
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO coin_topics
                  (eurio_id, source, lang, topic, method, model, confidence)
                VALUES (?, ?, ?, ?, 'llm_v1', ?, ?)
                """,
                (eurio_id, source, lang, topic, MODEL, confidence),
            )
            n_inserted += 1
        except sqlite3.IntegrityError as e:
            if "FOREIGN KEY" in str(e):
                n_orphan += 1
                continue
            raise
    conn.commit()

    cov = dict(conn.execute(
        "SELECT lang, count(*) FROM coin_topics "
        "WHERE method='llm_v1' GROUP BY lang"
    ).fetchall())
    conn.close()
    print(f"upserted {n_inserted} rows. Couverture method='llm_v1' par lang: {cov}")
    if n_orphan:
        print(f"  ⏭  {n_orphan} entries skipped (orphan eurio_id)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
