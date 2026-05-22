"""One-shot migration: filesystem images → MinIO, hard cut.

Spec: docs/harmonisation-images/chunk-3-migration-script.md.

Three categories of images, each with a distinct fs source and S3 target:

  canonical : ml/datasets/<numista_id>/{obverse,reverse}.jpg
              → numista-canonical/numista/<numista_id>/<face>.jpg

  raw       : ml/state/sources/<src>/raw/<shard>/<source_ref>.<ext>
              referenced by source_images.storage_path
              → enrichment-raws/<source>/<run_id>/<source_image_id>.<ext>

  crop      : ml/state/sources/<src>/crops/<shard>/<source_ref>__c<idx>.png
              referenced by image_assets.storage_path
              → enrichment-crops/<source>/<run_id>/<asset_id>.png

Sub-commands:
  inventory  build a manifest of every file to migrate (sha256 + target key)
  upload     push everything to MinIO (idempotent: skips if sha256 matches)
  db         rewrite storage_path values, archive originals in *_legacy
  verify     sample sha256 audit against MinIO
  lock-fs    chmod a-w on local source dirs (7-day safety)

The manifest lives at docs/harmonisation-images/migration-manifest.jsonl
and is committed to git as the rollback / historical record.

Run as `python -m ml.scripts.migrate_to_minio <subcommand> [args]`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sqlite3
import stat
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
ML_ROOT = REPO_ROOT / "ml"
DATASETS_DIR = ML_ROOT / "datasets"
SOURCES_DIR = ML_ROOT / "state" / "sources"
DB_PATH = ML_ROOT / "state" / "eurio.db"
MANIFEST_PATH = REPO_ROOT / "docs" / "harmonisation-images" / "migration-manifest.jsonl"

CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp",
    ".gif": "image/gif",
}


# ─── Manifest entry ─────────────────────────────────────────────────────────


@dataclass
class Entry:
    category: str             # "canonical" | "raw" | "crop"
    fs_path: str              # absolute path on the Mac
    bucket: str
    storage_key: str
    size: int
    sha256: str
    # Identity for DB updates (None for canonical — no DB row).
    table: str | None = None       # "image_assets" | "source_images"
    row_id: str | None = None      # primary key value
    legacy_path: str | None = None # current storage_path value (will be saved to *_legacy)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _sha256_file(p: Path, buf_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(buf_size):
            h.update(chunk)
    return h.hexdigest()


def _norm_source(s: str | None) -> str:
    return (s or "unknown").strip().lower() or "unknown"


def _run_id_or_sentinel(run_id: str | None) -> str:
    return run_id if run_id else "no-run"


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        sys.exit(f"DB not found: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ─── Inventory ──────────────────────────────────────────────────────────────


def _iter_canonical() -> Iterator[Entry]:
    """ml/datasets/<numista_id>/{obverse,reverse}.jpg"""
    if not DATASETS_DIR.exists():
        return
    for coin_dir in sorted(DATASETS_DIR.iterdir()):
        if not coin_dir.is_dir():
            continue
        # Skip non-numeric folders (e.g. coin_detect_v2, sources, ...).
        if not coin_dir.name.isdigit():
            continue
        numista_id = coin_dir.name
        for face in ("obverse", "reverse"):
            f = coin_dir / f"{face}.jpg"
            if not f.is_file():
                continue
            yield Entry(
                category="canonical",
                fs_path=str(f),
                bucket="numista-canonical",
                storage_key=f"numista/{numista_id}/{face}.jpg",
                size=f.stat().st_size,
                sha256=_sha256_file(f),
            )


def _iter_raws(conn: sqlite3.Connection) -> Iterator[Entry]:
    rows = conn.execute(
        """SELECT id, source, run_id, storage_path
             FROM source_images
            WHERE storage_path IS NOT NULL"""
    ).fetchall()
    for r in rows:
        fs_path = Path(r["storage_path"])
        if not fs_path.is_absolute() or not fs_path.is_file():
            # Already migrated, or missing — skip silently here, the
            # `--report-missing` option (run separately) can flag these.
            continue
        ext = fs_path.suffix.lower().lstrip(".") or "bin"
        source = _norm_source(r["source"])
        run_id = _run_id_or_sentinel(r["run_id"])
        key = f"{source}/{run_id}/{r['id']}.{ext}"
        yield Entry(
            category="raw",
            fs_path=str(fs_path),
            bucket="enrichment-raws",
            storage_key=key,
            size=fs_path.stat().st_size,
            sha256=_sha256_file(fs_path),
            table="source_images",
            row_id=r["id"],
            legacy_path=str(fs_path),
        )


def _iter_crops(conn: sqlite3.Connection) -> Iterator[Entry]:
    rows = conn.execute(
        """SELECT a.id AS asset_id, a.storage_path, a.run_id AS asset_run_id,
                  s.source, s.run_id AS si_run_id
             FROM image_assets a
             JOIN source_images s ON s.id = a.source_image_id
            WHERE a.storage_path IS NOT NULL"""
    ).fetchall()
    for r in rows:
        fs_path = Path(r["storage_path"])
        if not fs_path.is_absolute() or not fs_path.is_file():
            continue
        source = _norm_source(r["source"])
        # Prefer asset.run_id, fall back to source_image.run_id.
        run_id = _run_id_or_sentinel(r["asset_run_id"] or r["si_run_id"])
        key = f"{source}/{run_id}/{r['asset_id']}.png"
        yield Entry(
            category="crop",
            fs_path=str(fs_path),
            bucket="enrichment-crops",
            storage_key=key,
            size=fs_path.stat().st_size,
            sha256=_sha256_file(fs_path),
            table="image_assets",
            row_id=r["asset_id"],
            legacy_path=str(fs_path),
        )


def cmd_inventory(args: argparse.Namespace) -> int:
    """Walk the 3 sources, hash everything, write the manifest."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        n_by_cat = {"canonical": 0, "raw": 0, "crop": 0}
        total_bytes = 0
        with MANIFEST_PATH.open("w", encoding="utf-8") as out:
            for it in _iter_canonical():
                out.write(json.dumps(asdict(it)) + "\n")
                n_by_cat[it.category] += 1
                total_bytes += it.size
            for it in _iter_raws(conn):
                out.write(json.dumps(asdict(it)) + "\n")
                n_by_cat[it.category] += 1
                total_bytes += it.size
            for it in _iter_crops(conn):
                out.write(json.dumps(asdict(it)) + "\n")
                n_by_cat[it.category] += 1
                total_bytes += it.size
    finally:
        conn.close()
    print(f"manifest: {MANIFEST_PATH}")
    print(f"  canonical: {n_by_cat['canonical']:>6}")
    print(f"  raw      : {n_by_cat['raw']:>6}")
    print(f"  crop     : {n_by_cat['crop']:>6}")
    print(f"  total    : {sum(n_by_cat.values()):>6}  ({total_bytes / 1024**2:.1f} MiB)")
    return 0


# ─── Upload ─────────────────────────────────────────────────────────────────


def _read_manifest() -> list[Entry]:
    if not MANIFEST_PATH.exists():
        sys.exit(f"manifest not found: {MANIFEST_PATH}\nRun `inventory` first.")
    out = []
    with MANIFEST_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(Entry(**json.loads(line)))
    return out


def _upload_one(client, e: Entry) -> tuple[Entry, str]:
    """Upload if not already there with matching sha256. Returns ("uploaded"|"skipped"|err)."""
    from botocore.exceptions import ClientError

    # Idempotence: head_object, check our custom sha256 metadata.
    try:
        head = client.head_object(Bucket=e.bucket, Key=e.storage_key)
        existing_sha = head.get("Metadata", {}).get("sha256")
        if existing_sha == e.sha256:
            return e, "skipped"
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
            raise

    extra = {
        "ContentType": CONTENT_TYPES.get(
            "." + e.storage_key.rsplit(".", 1)[-1].lower(),
            "application/octet-stream",
        ),
        "Metadata": {"sha256": e.sha256},
    }
    if e.bucket == "numista-canonical":
        extra["CacheControl"] = "public, max-age=604800, immutable"

    client.upload_file(e.fs_path, e.bucket, e.storage_key, ExtraArgs=extra)
    return e, "uploaded"


def cmd_upload(args: argparse.Namespace) -> int:
    from storage import _client

    entries = _read_manifest()
    if args.category:
        entries = [e for e in entries if e.category == args.category]
    print(f"uploading {len(entries)} entries with {args.workers} workers…")

    client = _client()
    counts = {"uploaded": 0, "skipped": 0, "failed": 0}
    failures: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_upload_one, client, e): e for e in entries}
        for i, fut in enumerate(as_completed(futures), 1):
            e = futures[fut]
            try:
                _, status = fut.result()
                counts[status] += 1
            except Exception as exc:  # noqa: BLE001
                counts["failed"] += 1
                failures.append((f"{e.bucket}/{e.storage_key}", str(exc)[:200]))
            if i % 100 == 0 or i == len(entries):
                print(
                    f"  {i}/{len(entries)} "
                    f"(uploaded={counts['uploaded']}, skipped={counts['skipped']}, "
                    f"failed={counts['failed']})"
                )

    print(json.dumps(counts, indent=2))
    if failures:
        print("\nfailures (first 20):")
        for k, msg in failures[:20]:
            print(f"  {k}: {msg}")
        return 1
    return 0


# ─── DB rewrite ─────────────────────────────────────────────────────────────


def _ensure_legacy_columns(conn: sqlite3.Connection) -> None:
    for table in ("image_assets", "source_images"):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "storage_path_legacy" not in cols:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN storage_path_legacy TEXT"
            )

    cols_log = {r["name"] for r in conn.execute("PRAGMA table_info(migrations_log)")}
    if not cols_log:
        conn.execute(
            """CREATE TABLE migrations_log (
                 name TEXT PRIMARY KEY,
                 applied_at TEXT NOT NULL,
                 rows_affected INTEGER NOT NULL DEFAULT 0,
                 notes TEXT
               )"""
        )


def cmd_db(args: argparse.Namespace) -> int:
    entries = _read_manifest()
    rewrites = [e for e in entries if e.table and e.row_id]
    print(f"rewriting {len(rewrites)} rows across {len({e.table for e in rewrites})} tables…")

    conn = _connect()
    try:
        _ensure_legacy_columns(conn)
        with conn:  # transactional
            # 1. Snapshot legacy values (only first time — don't overwrite if already set).
            conn.execute(
                """UPDATE image_assets
                      SET storage_path_legacy = storage_path
                    WHERE storage_path_legacy IS NULL"""
            )
            conn.execute(
                """UPDATE source_images
                      SET storage_path_legacy = storage_path
                    WHERE storage_path_legacy IS NULL"""
            )

            # 2. Rewrite storage_path = S3 key.
            for e in rewrites:
                conn.execute(
                    f"UPDATE {e.table} SET storage_path = ? WHERE id = ?",
                    (e.storage_key, e.row_id),
                )

            # 3. Sanity: no absolute paths or NULLs left.
            for table in ("image_assets", "source_images"):
                bad = conn.execute(
                    f"""SELECT COUNT(*) AS n FROM {table}
                         WHERE storage_path LIKE '/%' OR storage_path IS NULL"""
                ).fetchone()["n"]
                if bad > 0:
                    raise RuntimeError(
                        f"{table}: {bad} rows still have absolute / NULL storage_path"
                    )

            # 4. Seal in migrations_log.
            conn.execute(
                """INSERT INTO migrations_log (name, applied_at, rows_affected, notes)
                   VALUES ('fs_to_minio', datetime('now'), ?, NULL)
                   ON CONFLICT(name) DO UPDATE
                      SET applied_at = excluded.applied_at,
                          rows_affected = excluded.rows_affected""",
                (len(rewrites),),
            )
    finally:
        conn.close()
    print("DB rewrite OK.")
    return 0


# ─── Verify (sample sha256) ─────────────────────────────────────────────────


def cmd_verify(args: argparse.Namespace) -> int:
    from storage import _client

    entries = _read_manifest()
    if not entries:
        print("manifest empty.")
        return 0
    n = max(args.floor, int(len(entries) * args.sample_pct / 100))
    n = min(n, args.ceil, len(entries))
    sample = random.sample(entries, n)
    print(f"verifying {n}/{len(entries)} entries (sha256 round-trip)…")

    client = _client()
    mismatches: list[str] = []
    for i, e in enumerate(sample, 1):
        h = hashlib.sha256()
        resp = client.get_object(Bucket=e.bucket, Key=e.storage_key)
        for chunk in resp["Body"].iter_chunks(1 << 20):
            h.update(chunk)
        got = h.hexdigest()
        if got != e.sha256:
            mismatches.append(f"{e.bucket}/{e.storage_key}: expected {e.sha256[:8]} got {got[:8]}")
        if i % 20 == 0 or i == n:
            print(f"  {i}/{n} ({len(mismatches)} mismatches)")
    if mismatches:
        print(f"\n{len(mismatches)} MISMATCHES:")
        for m in mismatches[:20]:
            print(f"  {m}")
        return 1
    print("OK — all sampled hashes match.")
    return 0


# ─── Lock fs (7-day safety) ─────────────────────────────────────────────────


def _chmod_recursive_readonly(root: Path) -> int:
    if not root.exists():
        return 0
    n = 0
    # Strip write bits from owner/group/others on all files & subdirs.
    # Keep dirs traversable (we don't want to lose +x on directories).
    mask_file = ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    for p in root.rglob("*"):
        try:
            mode = p.stat().st_mode
            p.chmod(mode & mask_file)
            n += 1
        except OSError:
            pass
    # Don't chmod the root dir itself (we may need to write a marker file later).
    return n


def cmd_lock_fs(args: argparse.Namespace) -> int:
    n = 0
    n += _chmod_recursive_readonly(DATASETS_DIR)
    for src_dir in SOURCES_DIR.glob("*"):
        n += _chmod_recursive_readonly(src_dir / "raw")
        n += _chmod_recursive_readonly(src_dir / "crops")
    print(f"chmod a-w applied on {n} entries.")
    return 0


# ─── Argparse ───────────────────────────────────────────────────────────────


_DEPRECATED_BANNER = """\
╔══════════════════════════════════════════════════════════════════════════╗
║  DEPRECATED — migrate_to_minio.py                                        ║
║                                                                          ║
║  Le scrape écrit désormais directement dans MinIO via le write-through   ║
║  cache (ml/sources/_base/steps/download.py + detect_crop.py). Ce script  ║
║  reste disponible comme utility de récup ou de réindexation batch,       ║
║  mais n'est plus appelé par le pipeline normal.                          ║
║                                                                          ║
║  Référence : docs/harmonisation-images/scrape-write-through-kickoff.md   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""


def main(argv: list[str] | None = None) -> int:
    print(_DEPRECATED_BANNER, file=sys.stderr)
    p = argparse.ArgumentParser(prog="migrate_to_minio")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("inventory", help="Build the manifest (sha256 + S3 keys)")

    up = sub.add_parser("upload", help="Push manifest entries to MinIO")
    up.add_argument("--workers", type=int, default=8)
    up.add_argument("--category", choices=["canonical", "raw", "crop"], default=None,
                    help="Limit to one category (default: all)")

    sub.add_parser("db", help="Rewrite storage_path → S3 key, archive legacy")

    vf = sub.add_parser("verify", help="Sample sha256 audit against MinIO")
    vf.add_argument("--sample-pct", type=float, default=5.0)
    vf.add_argument("--floor", type=int, default=100)
    vf.add_argument("--ceil", type=int, default=1000)

    sub.add_parser("lock-fs", help="chmod a-w on local source dirs (7-day safety)")

    args = p.parse_args(argv)
    return {
        "inventory": cmd_inventory,
        "upload": cmd_upload,
        "db": cmd_db,
        "verify": cmd_verify,
        "lock-fs": cmd_lock_fs,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
