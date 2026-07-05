"""Enrichit ``coins.raw_payload_json`` pour les pièces sans payload.

Contexte : ``docs/operations/j0-gap-analysis.md``. Le dashboard ``/operations``
montre 72 classes commémoratives 2 € sans aucune image canonique. 58 de ces
classes (148 coins au total) ont ``raw_payload_json`` vide parce que le step
*per-coin Numista detail* n'a jamais été exécuté pour elles — l'endpoint
``catalog list`` qui alimente ``referential_catalog`` ne renvoie pas les
URLs d'images.

Ce script comble ce trou :

  1. Sélectionne les ``coins`` à ``raw_payload_json`` vide ET ``numista_id`` non nul.
  2. Pour chacun, appelle ``GET /v3/types/{numista_id}?lang=en``.
  3. Construit un payload au format Eurio (``identity, cross_refs, images,
     provenance, numista_raw``) en alignant la clé ``images`` avec ce que
     ``migrate_canonical_schema.py`` attend (``{obverse, obverse_source,
     reverse, reverse_source}``).
  4. UPDATE la row ``coins`` (raw_payload_json + updated_at), commit par row
     pour être resume-friendly.

Une fois ce script terminé, lancer ``scripts/migrate_canonical_schema.py``
pour propager les nouvelles ``images`` vers ``coin_canonical_images``.

Idempotent : un coin déjà à payload rempli est skip. Re-jouable.

Usage::

    python -m scripts.enrich_missing_payloads --dry-run
    python -m scripts.enrich_missing_payloads --limit 5      # sample
    python -m scripts.enrich_missing_payloads                # full run
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from referential.numista_keys import KeyManager  # noqa: E402
from store import resolve_db_path  # noqa: E402

logger = logging.getLogger("enrich_missing_payloads")

DEFAULT_DB = resolve_db_path(ROOT / "state" / "eurio.db")
API_BASE = "https://api.numista.com/v3"
THROTTLE_SECONDS = 0.5  # courtesy delay between calls


def _fetch_type(api_key: str, nid: int) -> dict:
    resp = httpx.get(
        f"{API_BASE}/types/{nid}",
        params={"lang": "en"},
        headers={"Numista-API-Key": api_key},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _build_payload(coin_row: sqlite3.Row, numista_data: dict) -> dict:
    """Construit un payload Eurio-format à partir d'une row coins + réponse Numista.

    Aligne la clé ``images`` avec le contrat attendu par
    ``migrate_canonical_schema._child_rows`` : ``{obverse, obverse_source,
    reverse, reverse_source}``.
    """
    obverse = numista_data.get("obverse") or {}
    reverse = numista_data.get("reverse") or {}

    images: dict[str, Any] = {}
    if isinstance(obverse, dict) and obverse.get("picture"):
        images["obverse"] = obverse["picture"]
        images["obverse_source"] = "numista"
    if isinstance(reverse, dict) and reverse.get("picture"):
        images["reverse"] = reverse["picture"]
        images["reverse_source"] = "numista"

    return {
        "eurio_id": coin_row["eurio_id"],
        "identity": {
            "country": coin_row["country"],
            "country_name": coin_row["country_name"],
            "year": coin_row["year"],
            "face_value": coin_row["face_value"],
            "currency": coin_row["currency"],
            "is_commemorative": bool(coin_row["is_commemorative"]),
            "theme": coin_row["theme"],
            "design_description": coin_row["design_description"],
            "collector_only": bool(coin_row["collector_only"]),
        },
        "cross_refs": {
            "numista_id": coin_row["numista_id"],
        },
        "images": images,
        "provenance": {
            "source": "numista_v3",
            "endpoint": f"{API_BASE}/types/{coin_row['numista_id']}",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "numista_raw": numista_data,
    }


def enrich(
    conn: sqlite3.Connection,
    km: KeyManager,
    *,
    dry_run: bool,
    limit: int | None,
) -> dict:
    conn.row_factory = sqlite3.Row
    candidates = conn.execute(
        """
        SELECT *
        FROM coins
        WHERE numista_id IS NOT NULL
          AND (raw_payload_json IS NULL OR raw_payload_json = '')
        ORDER BY country, year, eurio_id
        """
    ).fetchall()
    total = len(candidates)
    if limit is not None:
        candidates = candidates[:limit]

    n_ok = 0
    n_images_obv = 0
    n_images_rev = 0
    n_skipped = 0
    n_failed = 0
    failures: list[dict] = []
    no_image_eurios: list[str] = []

    for i, row in enumerate(candidates, 1):
        eid = row["eurio_id"]
        nid = int(row["numista_id"])
        logger.info("[%d/%d] %s (numista_id=%d)", i, len(candidates), eid, nid)

        if dry_run:
            n_skipped += 1
            continue

        try:
            key = km.pick()
            data = _fetch_type(key, nid)
            km.record_call(key)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                km.mark_exhausted(key)
            n_failed += 1
            failures.append({"eurio_id": eid, "nid": nid, "error": f"HTTP {exc.response.status_code}"})
            logger.warning("  FAIL %s: HTTP %d", eid, exc.response.status_code)
            continue
        except Exception as exc:  # noqa: BLE001
            n_failed += 1
            failures.append({"eurio_id": eid, "nid": nid, "error": str(exc)[:200]})
            logger.warning("  FAIL %s: %s", eid, exc)
            continue

        payload = _build_payload(row, data)
        if payload["images"].get("obverse"):
            n_images_obv += 1
        if payload["images"].get("reverse"):
            n_images_rev += 1
        if not payload["images"]:
            no_image_eurios.append(eid)

        conn.execute(
            """
            UPDATE coins
            SET raw_payload_json = ?,
                updated_at = ?
            WHERE eurio_id = ?
            """,
            (
                json.dumps(payload, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
                eid,
            ),
        )
        conn.commit()
        n_ok += 1

        time.sleep(THROTTLE_SECONDS)

    return {
        "n_candidates_total": total,
        "n_processed": len(candidates),
        "n_ok": n_ok,
        "n_skipped_dry_run": n_skipped,
        "n_failed": n_failed,
        "n_with_obverse": n_images_obv,
        "n_with_reverse": n_images_rev,
        "n_no_image": len(no_image_eurios),
        "no_image_eurios": no_image_eurios,
        "failures": failures,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true",
                        help="Liste les candidats sans appeler l'API")
    parser.add_argument("--limit", type=int, default=None,
                        help="N'enrichit que les N premiers (pour sample-run)")
    args = parser.parse_args()

    if not args.dry_run:
        from store import resolve_db_readonly

        if resolve_db_readonly():
            raise SystemExit(
                "DB en lecture seule (réplique Direction A) — writer canonique = VPS. "
                "Poser EURIO_DB_READONLY=0 seulement sur le host canonique."
            )

    km = KeyManager(db_path=args.db)
    logger.info("Numista keys loaded: %d", len(km._keys))  # noqa: SLF001

    conn = sqlite3.connect(args.db)
    try:
        summary = enrich(conn, km, dry_run=args.dry_run, limit=args.limit)
    finally:
        conn.close()

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
