"""Migration des images canoniques du référentiel vers le stockage local.

Contexte (acté 2026-05-24, cf. memory ``feedback_architecture_eurio_db_vs_supabase``):
``eurio.db`` est la source de vérité dev. Les images canoniques doivent
vivre **localement** sous ``ml/canonical_images/{eurio_id}/...``, pas dans
Supabase Storage (qui reste cible future pour Android).

Pour chaque ligne de ``coin_canonical_images`` :

1. Si déjà migrée (``local_path`` présent ET fichier existe ET thumb existe) → skip.
2. Sinon on tente d'obtenir les **bytes source** dans cet ordre :
   a) Fichier local existant : ``ml/datasets/{numista_id}/{role}.jpg``
      (héritage des anciens scrapes Numista).
   b) Layout canonique Supabase Storage (public, sans auth) :
      ``{base}/storage/v1/object/public/coin-images/{eurio_id}/{role}_{tag}.webp``
   c) URL stockée en DB (CDN Numista direct, ou autre).
3. On encode WebP detail (400 px) + thumb (120 px) via
   ``canonical_image_local.write_variants``.
4. On met à jour ``coin_canonical_images.local_path`` (chemin relatif au repo).

Idempotent : re-runner ne fait rien si tout est déjà sur disque.
Resume-friendly : commit par row, pas de transaction longue.

Usage::

    python -m scripts.migrate_canonical_images_local --dry-run
    python -m scripts.migrate_canonical_images_local --limit 5
    python -m scripts.migrate_canonical_images_local
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from referential.canonical_image_local import (  # noqa: E402
    CANONICAL_DIR,
    canonical_path,
    exists as local_exists,
    relative_path,
    write_variants,
)
from referential.coin_image_storage import BUCKET_NAME, source_file_tag  # noqa: E402

logger = logging.getLogger("migrate_canonical_images_local")

DEFAULT_DB = ROOT / "state" / "eurio.db"
ML_DATASETS = ROOT / "datasets"
SUPABASE_URL_DEFAULT = "https://ettxkixkxrzchbnohgfm.supabase.co"

HTTP_TIMEOUT = 20
# Numista CDN bloque les UA "Mozilla/5.0" mais accepte les autres / vides.
NUMISTA_UA = "Eurio/0.1 (referential-image-migrator)"


def _supabase_canonical_url(supabase_url: str, eurio_id: str, role: str, source: str) -> str:
    tag = source_file_tag(source)
    return f"{supabase_url}/storage/v1/object/public/{BUCKET_NAME}/{eurio_id}/{role}_{tag}.webp"


def _local_source_path(numista_id: int | None, role: str) -> Path | None:
    """Cherche ml/datasets/{numista_id}/{role}.{jpg,png,webp}. None si absent."""
    if not numista_id:
        return None
    base = ML_DATASETS / str(numista_id)
    for ext in ("jpg", "png", "webp"):
        p = base / f"{role}.{ext}"
        if p.is_file():
            return p
    return None


def _fetch_bytes(client: httpx.Client, url: str, *, ua: str | None = None) -> bytes | None:
    try:
        headers = {"User-Agent": ua} if ua else {}
        resp = client.get(url, headers=headers, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.debug("  fetch err %s: %s", url[:80], exc)
        return None
    if resp.status_code != 200:
        return None
    if len(resp.content) < 1024:  # 1 KB safety floor — Supabase 404 returns JSON body
        return None
    return resp.content


def _gather_bytes(
    client: httpx.Client,
    row: sqlite3.Row,
    supabase_url: str,
) -> tuple[bytes | None, str]:
    """Tente plusieurs sources, retourne (bytes, source_hint) ou (None, '')."""
    eurio_id = row["eurio_id"]
    role = row["role"]
    source = row["source"]
    numista_id = row["numista_id"]

    # 1) Local jpg/png/webp from past Numista scrapes
    local = _local_source_path(numista_id, role)
    if local:
        try:
            return local.read_bytes(), f"local:{local.relative_to(ROOT.parent)}"
        except OSError as exc:
            logger.debug("  read local fail %s: %s", local, exc)

    # 2) Supabase canonical layout — try the declared source first.
    canonical_url = _supabase_canonical_url(supabase_url, eurio_id, role, source)
    data = _fetch_bytes(client, canonical_url)
    if data:
        return data, "supabase_canonical"

    # 2b) source='unknown' (legacy bulk import) — try numista/bce tag fallbacks.
    if source == "unknown":
        for alt in ("numista", "bce_comm"):
            alt_url = _supabase_canonical_url(supabase_url, eurio_id, role, alt)
            data = _fetch_bytes(client, alt_url)
            if data:
                return data, f"supabase_canonical_alt_{alt}"

    # 3) URL stored in DB (CDN Numista, BCE, legacy …)
    if row["url"]:
        ua = NUMISTA_UA if "numista.com" in row["url"] else None
        data = _fetch_bytes(client, row["url"], ua=ua)
        if data:
            return data, "db_url"

    return None, ""


def migrate(
    conn: sqlite3.Connection,
    *,
    dry_run: bool,
    limit: int | None,
    supabase_url: str,
) -> dict:
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT ci.eurio_id, ci.role, ci.source, ci.url, ci.local_path,
               c.numista_id
        FROM coin_canonical_images ci
        JOIN coins c ON c.eurio_id = ci.eurio_id
        ORDER BY ci.eurio_id, ci.role, ci.source
        """
    ).fetchall()
    total = len(rows)
    if limit is not None:
        rows = rows[:limit]

    n_already = 0
    n_ok = 0
    n_failed = 0
    by_origin: dict[str, int] = {}
    failures: list[dict] = []

    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(timeout=HTTP_TIMEOUT)

    try:
        for i, row in enumerate(rows, 1):
            eid = row["eurio_id"]
            role = row["role"]
            source = row["source"]

            # Skip if local files already exist AND DB knows the local_path.
            if local_exists(eid, role, source):
                if row["local_path"]:
                    n_already += 1
                    continue
                # File present but DB still NULL : backfill the column only.
                if not dry_run:
                    conn.execute(
                        "UPDATE coin_canonical_images SET local_path = ? "
                        "WHERE eurio_id = ? AND source = ? AND role = ?",
                        (relative_path(eid, role, source), eid, source, role),
                    )
                    conn.commit()
                n_already += 1
                continue

            if dry_run:
                logger.info("[%d/%d] %s %s/%s → would fetch", i, len(rows), eid, role, source)
                continue

            data, origin = _gather_bytes(client, row, supabase_url)
            if not data:
                n_failed += 1
                failures.append({"eurio_id": eid, "role": role, "source": source})
                logger.warning("[%d/%d] %s %s/%s FAIL (no source)", i, len(rows), eid, role, source)
                continue

            try:
                meta = write_variants(eid, role, source, data)
            except Exception as exc:  # noqa: BLE001
                n_failed += 1
                failures.append({"eurio_id": eid, "role": role, "source": source, "error": str(exc)[:200]})
                logger.warning("[%d/%d] %s %s/%s ENCODE FAIL: %s", i, len(rows), eid, role, source, exc)
                continue

            conn.execute(
                "UPDATE coin_canonical_images SET local_path = ? "
                "WHERE eurio_id = ? AND source = ? AND role = ?",
                (relative_path(eid, role, source), eid, source, role),
            )
            conn.commit()

            by_origin[origin.split(":")[0]] = by_origin.get(origin.split(":")[0], 0) + 1
            n_ok += 1
            if i % 50 == 0 or i == len(rows):
                logger.info(
                    "[%d/%d] %s %s/%s OK (%s, %d/%d B)",
                    i, len(rows), eid, role, source, origin.split(":")[0],
                    meta["detail_bytes"], meta["thumb_bytes"],
                )

    finally:
        client.close()

    return {
        "n_rows_total": total,
        "n_processed": len(rows),
        "n_already": n_already,
        "n_ok": n_ok,
        "n_failed": n_failed,
        "by_origin": by_origin,
        "failures_sample": failures[:20],
        "n_failures": len(failures),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL", SUPABASE_URL_DEFAULT))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        summary = migrate(conn, dry_run=args.dry_run, limit=args.limit, supabase_url=args.supabase_url)
    finally:
        conn.close()

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
