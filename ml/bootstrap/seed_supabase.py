"""Seed Supabase with trained embeddings.

Dual-write during the mobile transition:
  1. `model_classes` — one row per class (keyed by class_id, disambiguated by
     class_kind). Source of truth for the new pipeline.
  2. `coin_embeddings` — one row per eurio_id member of each class. Preserved
     so the current Android reader keeps working until it migrates to
     model_classes in a separate chantier.

Class membership (numista_ids, eurio_ids) is taken from embeddings_v1.json,
which was itself populated by compute_embeddings from the dataset manifest.

Usage:
    .venv/bin/python seed_supabase.py
    .venv/bin/python seed_supabase.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from eval.class_resolver import load_env

EMBEDDINGS_DEFAULT = Path(__file__).parent.parent / "output" / "embeddings_v1.json"


def seed(args: argparse.Namespace) -> int:
    env = load_env()
    supabase_url = env.get("SUPABASE_URL", "")
    supabase_key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required")
        return 2

    print(f"Supabase: {supabase_url}")

    embeddings_path = Path(args.embeddings)
    if not embeddings_path.exists():
        print(f"Embeddings file not found: {embeddings_path}")
        print("Run compute_embeddings.py first!")
        return 1

    emb_data = json.loads(embeddings_path.read_text())
    coins_data: dict[str, dict] = emb_data.get("coins", {})
    if not coins_data:
        print("No coins in embeddings file.")
        return 1

    embedding_dim = emb_data.get("embedding_dim", 256)
    model_version = emb_data.get("model", "v1-arcface")
    print(
        f"Embeddings: {len(coins_data)} classes, dim={embedding_dim}, "
        f"model={model_version}"
    )

    model_classes_rows: list[dict] = []
    coin_embeddings_rows: list[dict] = []

    for class_id, payload in coins_data.items():
        embedding = payload["embedding"] if isinstance(payload, dict) else payload
        class_kind = (
            payload.get("class_kind") if isinstance(payload, dict) else None
        ) or "eurio_id"
        eurio_ids = payload.get("eurio_ids", []) if isinstance(payload, dict) else []
        n_samples = payload.get("n_samples") if isinstance(payload, dict) else None

        model_classes_rows.append(
            {
                "class_id": class_id,
                "class_kind": class_kind,
                "embedding": embedding,
                "model_version": model_version,
                "n_train_images": n_samples,
            }
        )

        # Dual-write: expand a class to its member eurio_ids for back-compat.
        if class_kind == "eurio_id":
            # Class_id IS the eurio_id (standalone coin).
            coin_embeddings_rows.append(
                {
                    "eurio_id": class_id,
                    "embedding": embedding,
                    "model_version": model_version,
                }
            )
        else:
            # design_group: fan out to every member.
            if not eurio_ids:
                print(
                    f"  WARNING: {class_id} has class_kind=design_group_id "
                    "but no eurio_ids in manifest — coin_embeddings skipped"
                )
            for eid in eurio_ids:
                coin_embeddings_rows.append(
                    {
                        "eurio_id": eid,
                        "embedding": embedding,
                        "model_version": model_version,
                    }
                )

    print(
        f"\n{len(model_classes_rows)} model_classes rows · "
        f"{len(coin_embeddings_rows)} coin_embeddings rows"
    )

    if args.dry_run:
        print("--dry-run: not writing.")
        for row in model_classes_rows[:5]:
            print(f"  model_classes: {row['class_id']} [{row['class_kind']}]")
        if len(model_classes_rows) > 5:
            print(f"  ... and {len(model_classes_rows) - 5} more")
        return 0

    if not model_classes_rows:
        print("Nothing to seed.")
        return 0

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates",
    }
    rest_base = supabase_url.rstrip("/") + "/rest/v1"

    with httpx.Client(headers=headers, timeout=120) as client:
        batch_size = 100

        mc_upserted = _batched_upsert(
            client,
            rest_base,
            "model_classes?on_conflict=class_id",
            model_classes_rows,
            batch_size,
        )
        print(f"  model_classes upserted: {mc_upserted}")

        if coin_embeddings_rows:
            ce_upserted = _batched_upsert(
                client,
                rest_base,
                "coin_embeddings?on_conflict=eurio_id",
                coin_embeddings_rows,
                batch_size,
            )
            print(f"  coin_embeddings upserted: {ce_upserted}")

    print("\nDone.")
    return 0


def _batched_upsert(
    client: httpx.Client,
    rest_base: str,
    endpoint: str,
    rows: list[dict],
    batch_size: int,
) -> int:
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        resp = client.post(f"{rest_base}/{endpoint}", json=batch)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Supabase error ({resp.status_code}) on {endpoint}: {resp.text}"
            )
        total += len(batch)
    return total


def main():
    parser = argparse.ArgumentParser(description="Seed Supabase with embeddings")
    parser.add_argument(
        "--embeddings",
        type=str,
        default=str(EMBEDDINGS_DEFAULT),
        help="Path to embeddings JSON",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(seed(args))


if __name__ == "__main__":
    main()
