"""Periodic audit + repair of the MinIO ↔ DB ↔ cache trio.

Spec: docs/harmonisation-images/chunk-9-cascade-sync.md.

Sub-commands:
  migrate-schema   add the storage_status column on the 2 tables (idempotent)
  audit            list drifts (read-only)
  repair           apply corrections (mark DB rows missing, purge stale cache)
  purge-cache      drop cache files whose sha256 no longer matches MinIO

The script never deletes MinIO objects — that's reserved for the admin
flow (`storage.cascade.delete_asset_cascade`) or the orphan cleanup
script (chunk 8.3). Its purpose is to detect divergence and bring DB +
cache in sync with MinIO, never the other way around.

Run as `python -m scripts.cascade_sync <subcommand>` from `ml/`.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

from storage import Bucket
from storage.cascade import (
    STATUS_MISSING,
    STATUS_PRESENT,
    STATUS_REMOVED,
    _connect,
    _db_path,
)

_BUCKETS_FOR_TABLE = {
    "image_assets": ("numista-canonical", "enrichment-crops"),
    "source_images": ("enrichment-raws",),
}


# ─── migrate-schema ─────────────────────────────────────────────────────────


_MIGRATION_SQL = """
ALTER TABLE image_assets
  ADD COLUMN storage_status TEXT NOT NULL DEFAULT 'present'
  CHECK (storage_status IN ('present', 'missing_in_storage', 'removed_via_admin'));

ALTER TABLE source_images
  ADD COLUMN storage_status TEXT NOT NULL DEFAULT 'present'
  CHECK (storage_status IN ('present', 'missing_in_storage', 'removed_via_admin'));

CREATE INDEX IF NOT EXISTS idx_image_assets_storage_status
  ON image_assets(storage_status) WHERE storage_status != 'present';

CREATE INDEX IF NOT EXISTS idx_source_images_storage_status
  ON source_images(storage_status) WHERE storage_status != 'present';
"""


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return any(
        r["name"] == col
        for r in conn.execute(f"PRAGMA table_info({table})")
    )


def cmd_migrate_schema(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        with conn:
            for table in ("image_assets", "source_images"):
                if _has_column(conn, table, "storage_status"):
                    print(f"  {table}: storage_status already present, skipping ALTER")
                else:
                    conn.execute(
                        f"""ALTER TABLE {table}
                            ADD COLUMN storage_status TEXT NOT NULL DEFAULT 'present'
                            CHECK (storage_status IN ('present', 'missing_in_storage', 'removed_via_admin'))"""
                    )
                    print(f"  {table}: added storage_status")
                conn.execute(
                    f"""CREATE INDEX IF NOT EXISTS idx_{table}_storage_status
                          ON {table}(storage_status) WHERE storage_status != 'present'"""
                )
        print("migrate-schema OK")
        return 0
    finally:
        conn.close()


# ─── audit ──────────────────────────────────────────────────────────────────


def _bucket_for_row(table: str, source: str | None) -> Bucket:
    if table == "source_images":
        return "enrichment-raws"
    if (source or "").lower() == "numista":
        return "numista-canonical"
    return "enrichment-crops"


def _list_db_keys(conn: sqlite3.Connection) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Return {(bucket, storage_key): [(table, row_id), ...]} for `present` rows."""
    out: dict[tuple[str, str], list[tuple[str, str]]] = {}
    rows = conn.execute(
        """SELECT a.id AS row_id, a.storage_path, s.source
             FROM image_assets a
             JOIN source_images s ON s.id = a.source_image_id
            WHERE a.storage_status = 'present' AND a.storage_path IS NOT NULL"""
    ).fetchall()
    for r in rows:
        b = _bucket_for_row("image_assets", r["source"])
        out.setdefault((b, r["storage_path"]), []).append(("image_assets", r["row_id"]))

    rows = conn.execute(
        """SELECT id AS row_id, storage_path, source
             FROM source_images
            WHERE storage_status = 'present' AND storage_path IS NOT NULL"""
    ).fetchall()
    for r in rows:
        b = _bucket_for_row("source_images", r["source"])
        out.setdefault((b, r["storage_path"]), []).append(("source_images", r["row_id"]))
    return out


def _list_minio_keys(client, bucket: Bucket) -> set[str]:
    keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
    return keys


def _head_sha256(client, bucket: Bucket, key: str) -> str | None:
    try:
        h = client.head_object(Bucket=bucket, Key=key)
    except Exception:  # noqa: BLE001
        return None
    return h.get("Metadata", {}).get("sha256")


def _file_sha256(p: Path, buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(buf):
            h.update(chunk)
    return h.hexdigest()


def _audit(client, conn: sqlite3.Connection, *, check_cache: bool):
    """Compute the 3 drift sets without mutating anything."""
    db_keys = _list_db_keys(conn)
    db_set = set(db_keys.keys())
    db_by_bucket: dict[str, set[str]] = {}
    for b, k in db_set:
        db_by_bucket.setdefault(b, set()).add(k)

    rows_missing_in_minio: list[tuple[str, str, str, str]] = []   # (bucket, key, table, row_id)
    minio_missing_in_db: dict[str, list[str]] = {}                # bucket -> [keys]
    cache_stale: list[Path] = []

    for bucket in ("numista-canonical", "enrichment-raws", "enrichment-crops"):
        minio_keys = _list_minio_keys(client, bucket)
        db_keys_for_bucket = db_by_bucket.get(bucket, set())

        for key in db_keys_for_bucket - minio_keys:
            for table, row_id in db_keys[(bucket, key)]:
                rows_missing_in_minio.append((bucket, key, table, row_id))

        orphans = sorted(minio_keys - db_keys_for_bucket)
        if orphans:
            minio_missing_in_db[bucket] = orphans

        if check_cache:
            from storage import local_cache  # lazy
            cache_dir = local_cache._cache_root() / bucket  # noqa: SLF001
            if not cache_dir.exists():
                continue
            for f in cache_dir.rglob("*"):
                if not f.is_file() or f.name.endswith(".tmp"):
                    continue
                key = str(f.relative_to(cache_dir))
                expected = _head_sha256(client, bucket, key)
                if expected is None:
                    cache_stale.append(f)
                    continue
                actual = _file_sha256(f)
                if actual != expected:
                    cache_stale.append(f)

    return rows_missing_in_minio, minio_missing_in_db, cache_stale


def cmd_audit(args: argparse.Namespace) -> int:
    from storage import _client

    conn = _connect()
    try:
        rmi, mmi, cs = _audit(_client(), conn, check_cache=args.check_cache)
    finally:
        conn.close()

    print("== DB rows missing in MinIO ==")
    if not rmi:
        print("  (none)")
    else:
        by_bucket: dict[str, list[tuple[str, str, str]]] = {}
        for b, k, t, r in rmi:
            by_bucket.setdefault(b, []).append((k, t, r))
        for b, items in by_bucket.items():
            print(f"  {b}: {len(items)} rows")
            for k, t, r in items[:10]:
                print(f"    {t} {r} → {k}")
            if len(items) > 10:
                print(f"    … ({len(items) - 10} more)")

    print("\n== MinIO objects missing in DB (orphans) ==")
    if not mmi:
        print("  (none)")
    else:
        for b, keys in mmi.items():
            print(f"  {b}: {len(keys)} orphans")
            for k in keys[:10]:
                print(f"    {k}")
            if len(keys) > 10:
                print(f"    … ({len(keys) - 10} more)")

    if args.check_cache:
        print("\n== Cache files stale ==")
        if not cs:
            print("  (none)")
        else:
            for f in cs[:20]:
                print(f"  {f}")
            if len(cs) > 20:
                print(f"  … ({len(cs) - 20} more)")
    else:
        print("\n(cache check skipped — pass --check-cache to enable)")

    drift = bool(rmi or mmi or cs)
    print(
        f"\nSummary: rows_missing={len(rmi)}, minio_orphans="
        f"{sum(len(v) for v in mmi.values())}, cache_stale={len(cs)}"
    )
    if drift and not args.allow_drift:
        print("\nNon-zero drift. Run `repair` to fix DB+cache (orphans stay manual).")
        return 1
    return 0


# ─── repair ─────────────────────────────────────────────────────────────────


def cmd_repair(args: argparse.Namespace) -> int:
    from storage import _client

    conn = _connect()
    try:
        rmi, _orphans, cs = _audit(_client(), conn, check_cache=args.check_cache)

        # 1. Mark missing-in-MinIO rows.
        if rmi:
            with conn:
                for bucket, key, table, row_id in rmi:
                    conn.execute(
                        f"""UPDATE {table}
                              SET storage_status = ?
                            WHERE id = ? AND storage_status = ?""",
                        (STATUS_MISSING, row_id, STATUS_PRESENT),
                    )
            print(f"marked {len(rmi)} rows as {STATUS_MISSING}")
        else:
            print("no rows to mark")

        # 2. Purge stale cache.
        if cs:
            for f in cs:
                f.unlink(missing_ok=True)
            print(f"purged {len(cs)} stale cache files")
        else:
            print("no cache files to purge")
    finally:
        conn.close()

    # MinIO orphans are NOT auto-deleted — chunk 8.3 owns that flow.
    print("\nMinIO orphans untouched. Use the orphan_cleanup script for those.")
    return 0


# ─── purge-cache ────────────────────────────────────────────────────────────


def cmd_purge_cache(args: argparse.Namespace) -> int:
    from storage import _client, local_cache

    client = _client()
    cache_root = local_cache._cache_root()  # noqa: SLF001
    if not cache_root.exists():
        print("cache root does not exist, nothing to do.")
        return 0

    purged = 0
    for bucket_dir in cache_root.iterdir():
        if not bucket_dir.is_dir():
            continue
        bucket = bucket_dir.name
        for f in bucket_dir.rglob("*"):
            if not f.is_file() or f.name.endswith(".tmp"):
                continue
            key = str(f.relative_to(bucket_dir))
            expected = _head_sha256(client, bucket, key)
            actual = _file_sha256(f)
            if expected is None or expected != actual:
                f.unlink(missing_ok=True)
                purged += 1
    print(f"purged {purged} stale cache files")
    return 0


# ─── argparse ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cascade_sync")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "migrate-schema",
        help="Add storage_status column on image_assets + source_images (idempotent).",
    )

    aud = sub.add_parser("audit", help="List drifts MinIO ↔ DB ↔ cache (read-only).")
    aud.add_argument("--check-cache", action="store_true",
                     help="Also walk the local cache and compare sha256 vs MinIO metadata.")
    aud.add_argument("--allow-drift", action="store_true",
                     help="Exit 0 even if drift is found.")

    rep = sub.add_parser("repair", help="Mark DB rows missing + purge stale cache.")
    rep.add_argument("--check-cache", action="store_true",
                     help="Also purge cache files whose sha256 doesn't match MinIO.")

    sub.add_parser(
        "purge-cache",
        help="Walk cache, drop files whose sha256 no longer matches MinIO.",
    )

    args = p.parse_args(argv)
    return {
        "migrate-schema": cmd_migrate_schema,
        "audit": cmd_audit,
        "repair": cmd_repair,
        "purge-cache": cmd_purge_cache,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
