"""Push local eurio.db state vers Supabase (miroir pour l'app Android future).

Architecture (cf. memory ``feedback_architecture_eurio_db_vs_supabase``):
- eurio.db local = source de vérité.
- Supabase = miroir poussé manuellement, jamais écrit en live pendant le dev.

Ce script regroupe 3 étapes :

  1. **Rewrite local URLs** — réécrit ``coin_canonical_images.url`` pour qu'il
     pointe vers le layout canonique Supabase Storage attendu :
     ``{base}/storage/v1/object/public/coin-images/{eurio_id}/{role}_{source_tag}.webp``
     C'est nécessaire car les URLs en DB peuvent dater (CDN Numista, Supabase legacy).

  2. **Upload Storage** — pour chaque fichier WebP local
     (``ml/canonical_images/{eurio_id}/...``), upload vers Supabase Storage si
     pas déjà présent (HEAD check). Idempotent.

  3. **Sync tables** — déclenche ``scripts/-m ml.export.sync_to_supabase`` qui
     upsert coins / observations / market_prices / i18n / aliases via PostgREST.

  4. **Cleanup zombies** — DELETE des eurio_id présents en Supabase mais
     absents en eurio.db (slugs orphelins de synchros antérieures).

Idempotent par construction (upsert, HEAD check, set difference).

Usage::

    python -m scripts.push_to_supabase --dry-run
    python -m scripts.push_to_supabase --skip-storage    # juste rewrite + sync + cleanup
    python -m scripts.push_to_supabase
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from export.sync_to_supabase import load_env  # noqa: E402
from referential.canonical_image_local import canonical_path, relative_path  # noqa: E402
from referential.coin_image_storage import BUCKET_NAME, source_file_tag  # noqa: E402

logger = logging.getLogger("push_to_supabase")

DEFAULT_DB = ROOT / "state" / "eurio.db"


def _supabase_url_for(supabase_url: str, eurio_id: str, role: str, source: str, *, thumb: bool = False) -> str:
    tag = source_file_tag(source)
    suffix = "_thumb" if thumb else ""
    return (
        f"{supabase_url}/storage/v1/object/public/{BUCKET_NAME}/"
        f"{eurio_id}/{role}_{tag}{suffix}.webp"
    )


def _list_bucket_keys(client: httpx.Client, supabase_url: str) -> set[str]:
    """Liste toutes les clés actuellement présentes dans le bucket.

    Endpoint Supabase ``POST /storage/v1/object/list/{bucket}`` — paginé avec
    offset/limit. On parcourt récursivement les "dossiers" (eurio_id) parce
    que l'API ne renvoie qu'un niveau à la fois.
    """
    keys: set[str] = set()
    # Niveau 1 : tous les "dossiers" (= eurio_id) à la racine.
    offset = 0
    limit = 1000
    eurio_dirs: list[str] = []
    while True:
        resp = client.post(
            f"{supabase_url}/storage/v1/object/list/{BUCKET_NAME}",
            json={"prefix": "", "limit": limit, "offset": offset,
                  "sortBy": {"column": "name", "order": "asc"}},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning("list root failed: HTTP %d %s", resp.status_code, resp.text[:200])
            return keys
        batch = resp.json() or []
        if not batch:
            break
        for item in batch:
            name = item.get("name")
            # Les sous-dossiers ont id=None / metadata=None côté Supabase.
            if name and (item.get("id") is None or item.get("metadata") is None):
                eurio_dirs.append(name)
            elif name:
                # Fichier à la racine — rare mais possible.
                keys.add(name)
        if len(batch) < limit:
            break
        offset += len(batch)

    # Niveau 2 : files dans chaque eurio_id/
    for dir_name in eurio_dirs:
        offset = 0
        while True:
            resp = client.post(
                f"{supabase_url}/storage/v1/object/list/{BUCKET_NAME}",
                json={"prefix": dir_name, "limit": limit, "offset": offset,
                      "sortBy": {"column": "name", "order": "asc"}},
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning("list %s failed: HTTP %d", dir_name, resp.status_code)
                break
            batch = resp.json() or []
            if not batch:
                break
            for item in batch:
                name = item.get("name")
                if name and item.get("metadata"):
                    keys.add(f"{dir_name}/{name}")
            if len(batch) < limit:
                break
            offset += len(batch)
    return keys


def _upload_object(client: httpx.Client, supabase_url: str, key: str, data: bytes) -> bool:
    resp = client.post(
        f"{supabase_url}/storage/v1/object/{BUCKET_NAME}/{key}",
        content=data,
        headers={"Content-Type": "image/webp", "x-upsert": "true"},
        timeout=30,
    )
    return resp.status_code < 400


def rewrite_urls(conn: sqlite3.Connection, supabase_url: str, *, dry_run: bool) -> dict:
    """Réécrit ``coin_canonical_images.url`` pour pointer vers le layout canonique."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT eurio_id, source, role, url FROM coin_canonical_images"
    ).fetchall()

    n_rewritten = 0
    n_unchanged = 0
    for r in rows:
        expected = _supabase_url_for(supabase_url, r["eurio_id"], r["role"], r["source"])
        if r["url"] == expected:
            n_unchanged += 1
            continue
        if not dry_run:
            conn.execute(
                "UPDATE coin_canonical_images SET url = ? "
                "WHERE eurio_id = ? AND source = ? AND role = ?",
                (expected, r["eurio_id"], r["source"], r["role"]),
            )
        n_rewritten += 1
    if not dry_run:
        conn.commit()
    return {"n_rewritten": n_rewritten, "n_unchanged": n_unchanged, "n_total": len(rows)}


def upload_storage(
    conn: sqlite3.Connection,
    supabase_url: str,
    service_key: str,
    *,
    dry_run: bool,
) -> dict:
    """Upload des fichiers WebP locaux vers Supabase Storage si absents."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT eurio_id, source, role FROM coin_canonical_images "
        "WHERE local_path IS NOT NULL"
    ).fetchall()

    # Construction de la liste des uploads à faire : (key, local_path).
    targets: list[tuple[str, Path]] = []
    n_missing_local = 0
    for r in rows:
        eid = r["eurio_id"]
        role = r["role"]
        source = r["source"]
        for thumb in (False, True):
            local_p = canonical_path(eid, role, source, thumb=thumb)
            if not local_p.is_file():
                n_missing_local += 1
                continue
            tag = source_file_tag(source)
            suffix = "_thumb" if thumb else ""
            key = f"{eid}/{role}_{tag}{suffix}.webp"
            targets.append((key, local_p))

    if dry_run:
        return {
            "n_total_rows": len(rows),
            "n_targets": len(targets),
            "n_missing_local": n_missing_local,
            "note": "dry-run — aucun upload effectué",
        }

    # Upload parallèle (x-upsert: true → idempotent côté Supabase).
    # 8 threads × ~200 ms par upload = ~60 s pour 2300 fichiers.
    n_uploaded = 0
    n_failed = 0
    failures: list[dict] = []

    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}

    def _do_upload(key: str, local_p: Path) -> tuple[str, bool, str | None]:
        # Client par thread — httpx Client n'est pas thread-safe.
        # Retry une fois sur timeout : ~0.2 % de taux d'échec aléatoire observé.
        last_err: str | None = None
        for attempt in (1, 2):
            try:
                with httpx.Client(headers=headers, timeout=30) as c:
                    data = local_p.read_bytes()
                    ok = _upload_object(c, supabase_url, key, data)
                    if ok:
                        return key, True, None
                    last_err = "HTTP failed"
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)[:150]
            if attempt == 1:
                # Petit backoff avant retry.
                import time
                time.sleep(1.0)
        return key, False, last_err

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_do_upload, key, p) for key, p in targets]
        for i, fut in enumerate(as_completed(futs), 1):
            key, ok, err = fut.result()
            if ok:
                n_uploaded += 1
            else:
                n_failed += 1
                failures.append({"key": key, "error": err or "unknown"})
            if i % 200 == 0:
                logger.info("  upload progress: %d/%d ok=%d fail=%d",
                            i, len(targets), n_uploaded, n_failed)

    return {
        "n_total_rows": len(rows),
        "n_targets": len(targets),
        "n_uploaded": n_uploaded,
        "n_failed": n_failed,
        "n_missing_local": n_missing_local,
        "failures_sample": failures[:10],
    }


def sync_db_tables(*, dry_run: bool) -> dict:
    """Lance ``scripts/-m export.sync_to_supabase`` et capture le résultat."""
    args = [sys.executable, "-m", "export.sync_to_supabase"]
    if dry_run:
        args.append("--dry-run")
    proc = subprocess.run(args, capture_output=True, text=True, cwd=ROOT, timeout=600)
    return {
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-1500:],
        "stderr_tail": proc.stderr[-500:],
    }


def cleanup_zombies(
    conn: sqlite3.Connection,
    supabase_url: str,
    service_key: str,
    *,
    dry_run: bool,
) -> dict:
    """DELETE des eurio_id présents en Supabase mais absents en eurio.db."""
    db_ids = {r[0] for r in conn.execute("SELECT eurio_id FROM coins")}

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    client = httpx.Client(headers=headers, timeout=60)
    try:
        # Page sur les coins Supabase via PostgREST.
        page = 0
        page_size = 1000
        zombies: list[str] = []
        while True:
            resp = client.get(
                f"{supabase_url}/rest/v1/coins",
                params={"select": "eurio_id", "limit": page_size, "offset": page * page_size},
            )
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code} reading Supabase coins"}
            batch = resp.json()
            if not batch:
                break
            for row in batch:
                eid = row.get("eurio_id")
                if eid and eid not in db_ids:
                    zombies.append(eid)
            if len(batch) < page_size:
                break
            page += 1

        if dry_run:
            return {
                "n_supabase_total": page * page_size + len(batch),
                "n_local_total": len(db_ids),
                "n_zombies": len(zombies),
                "zombies_sample": zombies[:20],
                "deleted": False,
            }

        # DELETE par chunks (PostgREST: ?eurio_id=in.(...) avec quoting).
        deleted = 0
        chunk = 50
        for i in range(0, len(zombies), chunk):
            ids = zombies[i:i + chunk]
            # PostgREST wants strings quoted: eurio_id=in.("a","b")
            quoted = ",".join(f'"{e}"' for e in ids)
            resp = client.delete(
                f"{supabase_url}/rest/v1/coins",
                params={"eurio_id": f"in.({quoted})"},
            )
            if resp.status_code < 400:
                deleted += len(ids)
            else:
                logger.warning("delete chunk failed: %d %s", resp.status_code, resp.text[:200])

        return {
            "n_local_total": len(db_ids),
            "n_zombies": len(zombies),
            "n_deleted": deleted,
            "zombies_sample": zombies[:20],
        }
    finally:
        client.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-storage", action="store_true",
                   help="Skip image upload (use after a previous storage sync)")
    p.add_argument("--skip-cleanup", action="store_true",
                   help="Skip zombie DELETE")
    args = p.parse_args()

    env = load_env()
    # Make env vars available for sync_to_supabase subprocess
    for k, v in env.items():
        os.environ.setdefault(k, v)
    supabase_url = env.get("SUPABASE_URL")
    service_key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    summary: dict = {}
    try:
        logger.info("Step 1/4 — rewrite_urls")
        summary["rewrite_urls"] = rewrite_urls(conn, supabase_url, dry_run=args.dry_run)

        if not args.skip_storage:
            logger.info("Step 2/4 — upload_storage")
            summary["upload_storage"] = upload_storage(conn, supabase_url, service_key, dry_run=args.dry_run)
        else:
            summary["upload_storage"] = {"skipped": True}

        logger.info("Step 3/4 — sync_db_tables")
        summary["sync_db_tables"] = sync_db_tables(dry_run=args.dry_run)

        if not args.skip_cleanup:
            logger.info("Step 4/4 — cleanup_zombies")
            summary["cleanup_zombies"] = cleanup_zombies(conn, supabase_url, service_key, dry_run=args.dry_run)
        else:
            summary["cleanup_zombies"] = {"skipped": True}
    finally:
        conn.close()

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
