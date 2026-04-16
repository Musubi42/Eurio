"""Seed Supabase coin_embeddings table from computed embeddings.

Resolves numista_id (directory names in the dataset) → eurio_id by querying
existing coins in Supabase. Does NOT insert/modify coins — those are managed
by the bootstrap pipeline.

Usage:
    .venv/bin/python seed_supabase.py
    .venv/bin/python seed_supabase.py --embeddings ./output/embeddings_v1.json
    .venv/bin/python seed_supabase.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

EMBEDDINGS_DEFAULT = Path(__file__).parent / "output" / "embeddings_v1.json"


def load_env() -> dict[str, str]:
    """Load environment variables from .env file."""
    env: dict[str, str] = {}
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    for key in ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"]:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def resolve_numista_to_eurio(
    client: httpx.Client,
    rest_base: str,
    numista_ids: list[int],
) -> dict[int, list[str]]:
    """Query Supabase for coins matching numista_ids, return {numista_id: [eurio_id, ...]}."""
    mapping: dict[int, list[str]] = {}

    # Fetch all coins that have a numista_id in cross_refs
    resp = client.get(
        f"{rest_base}/coins",
        params={
            "select": "eurio_id,cross_refs",
            "cross_refs->numista_id": "not.is.null",
        },
        headers={"Range": "0-4999"},
    )
    resp.raise_for_status()

    for row in resp.json():
        cr = row.get("cross_refs") or {}
        nid = cr.get("numista_id")
        if nid is None:
            continue
        nid = int(nid)
        if nid in numista_ids:
            mapping.setdefault(nid, []).append(row["eurio_id"])

    return mapping


def seed(args: argparse.Namespace) -> int:
    env = load_env()
    supabase_url = env.get("SUPABASE_URL", "")
    supabase_key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required")
        return 2

    print(f"Supabase: {supabase_url}")

    # Load embeddings
    embeddings_path = Path(args.embeddings)
    if not embeddings_path.exists():
        print(f"Embeddings file not found: {embeddings_path}")
        print("Run compute_embeddings.py first!")
        return 1

    with open(embeddings_path) as f:
        emb_data = json.load(f)

    coins_data = emb_data.get("coins", {})
    if not coins_data:
        print("No coins in embeddings file.")
        return 1

    embedding_dim = emb_data.get("embedding_dim", 256)
    model_version = emb_data.get("model", "v1")
    print(f"Embeddings: {len(coins_data)} classes, dim={embedding_dim}, model={model_version}")

    # Parse class names as numista_ids
    numista_ids: list[int] = []
    for class_name in coins_data:
        try:
            numista_ids.append(int(class_name))
        except ValueError:
            print(f"  WARNING: class '{class_name}' is not a numista_id, skipping")

    if not numista_ids:
        print("No valid numista_id classes found in embeddings.")
        return 1

    # Resolve numista_id → eurio_id via Supabase
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates",
    }
    rest_base = supabase_url.rstrip("/") + "/rest/v1"

    with httpx.Client(headers=headers, timeout=60) as client:
        print(f"\nResolving {len(numista_ids)} numista_ids → eurio_ids...")
        mapping = resolve_numista_to_eurio(client, rest_base, numista_ids)

        resolved = sum(len(v) for v in mapping.values())
        print(f"  Resolved: {len(mapping)} numista_ids → {resolved} eurio_ids")

        unresolved = [nid for nid in numista_ids if nid not in mapping]
        if unresolved:
            print(f"  Unresolved: {unresolved}")

        # Build embedding rows
        embedding_rows: list[dict] = []
        for nid in numista_ids:
            class_name = str(nid)
            coin_emb = coins_data.get(class_name)
            if not coin_emb:
                continue

            eurio_ids = mapping.get(nid, [])
            if not eurio_ids:
                print(f"  {class_name}: no eurio_ids found in Supabase, skipping")
                continue

            embedding = coin_emb["embedding"] if isinstance(coin_emb, dict) else coin_emb

            # Insert one embedding row per eurio_id that shares this design
            for eid in eurio_ids:
                embedding_rows.append({
                    "eurio_id": eid,
                    "embedding": embedding,
                    "model_version": model_version,
                })

        print(f"\n{len(embedding_rows)} embedding rows to upsert")

        if args.dry_run:
            print("--dry-run: not writing.")
            for row in embedding_rows[:5]:
                print(f"  {row['eurio_id']} (dim={len(row['embedding'])})")
            if len(embedding_rows) > 5:
                print(f"  ... and {len(embedding_rows) - 5} more")
            return 0

        if not embedding_rows:
            print("Nothing to seed.")
            return 0

        # Upsert embeddings in batches
        batch_size = 100
        total_upserted = 0
        for i in range(0, len(embedding_rows), batch_size):
            batch = embedding_rows[i : i + batch_size]
            resp = client.post(
                f"{rest_base}/coin_embeddings?on_conflict=eurio_id",
                json=batch,
            )
            if resp.status_code >= 400:
                print(f"Supabase error ({resp.status_code}): {resp.text}")
                return 1
            total_upserted += len(batch)
            print(f"  Batch {i // batch_size + 1}: {len(batch)} rows upserted")

        print(f"\nDone! {total_upserted} embeddings seeded into coin_embeddings.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Seed Supabase with embeddings")
    parser.add_argument(
        "--embeddings",
        type=str,
        default=str(EMBEDDINGS_DEFAULT),
        help="Path to embeddings JSON",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    sys.exit(seed(args))


if __name__ == "__main__":
    main()
