"""Seed Supabase with coin catalogue from Numista + computed embeddings."""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

CATALOG_PATH = Path(__file__).parent / "datasets" / "coin_catalog.json"


def load_env() -> dict[str, str]:
    """Load environment variables from .env file."""
    env = {}
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    # Override with actual env vars
    for key in ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "NUMISTA_API_KEY"]:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def fetch_numista_coin(numista_id: int, api_key: str) -> dict | None:
    """Fetch coin details from Numista API v3 by type ID."""
    try:
        resp = httpx.get(
            f"https://api.numista.com/v3/types/{numista_id}",
            headers={"Numista-API-Key": api_key},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"  Numista API returned {resp.status_code} for type {numista_id}")
    except httpx.HTTPError as e:
        print(f"  Numista API error for type {numista_id}: {e}")
    return None


def numista_to_coin_row(data: dict) -> dict:
    """Convert Numista API response to a row for the coins table."""
    numista_id = data.get("id")
    issuer = data.get("issuer", {})
    country = issuer.get("name", "Unknown")

    year = data.get("min_year")

    # Face value — clamp to numeric(4,2) range (max 99.99)
    face_value = None
    if data.get("value"):
        fv = data["value"].get("numeric_value")
        if fv is not None and fv < 100:
            face_value = fv

    coin_type = "circulation"
    if "commemorative" in data.get("title", "").lower():
        coin_type = "commemorative"
    if data.get("commemorated_topic"):
        coin_type = "commemorative"

    obverse_url = None
    reverse_url = None
    if data.get("obverse"):
        obverse_url = data["obverse"].get("picture")
    if data.get("reverse"):
        reverse_url = data["reverse"].get("picture")

    return {
        "numista_id": numista_id,
        "name": data.get("title", f"Coin {numista_id}"),
        "country": country,
        "year": year,
        "face_value": face_value,
        "type": coin_type,
        "mintage": None,
        "image_obverse_url": obverse_url,
        "image_reverse_url": reverse_url,
    }


def supabase_upsert(url: str, key: str, table: str, rows: list[dict], on_conflict: str = "") -> list[dict]:
    """Upsert rows into a Supabase table via REST API. Returns upserted rows."""
    endpoint = f"{url}/rest/v1/{table}"
    if on_conflict:
        endpoint += f"?on_conflict={on_conflict}"

    resp = httpx.post(
        endpoint,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation,resolution=merge-duplicates",
        },
        json=rows,
        timeout=15,
    )

    if resp.status_code in (200, 201):
        return resp.json()

    if resp.status_code in (401, 403):
        print(f"\nERROR: Supabase returned {resp.status_code} for INSERT into {table}.")
        print("RLS is enabled. You need either:")
        print("  1. Add SUPABASE_SERVICE_ROLE_KEY to .env and use that instead")
        print("  2. Create an INSERT policy on the table")
        print(f"Response: {resp.text}")
        sys.exit(1)

    print(f"Supabase INSERT error ({resp.status_code}): {resp.text}")
    sys.exit(1)


def seed(args):
    env = load_env()

    supabase_url = env.get("SUPABASE_URL")
    # Prefer service role key for seeding (bypasses RLS)
    supabase_key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_ANON_KEY")
    numista_key = env.get("NUMISTA_API_KEY")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_ANON_KEY (or SERVICE_ROLE_KEY) required in .env")
        sys.exit(1)

    if not numista_key:
        print("WARNING: NUMISTA_API_KEY not found. Using fallback metadata.")

    using_service_key = "SUPABASE_SERVICE_ROLE_KEY" in env
    print(f"Supabase: {supabase_url}")
    print(f"Auth key: {'service_role' if using_service_key else 'anon'}")

    # Load catalog
    with open(CATALOG_PATH) as f:
        catalog = json.load(f)["coins"]

    # Step 1: Fetch coin metadata and insert into coins table
    print("\n--- Seeding coins table ---")
    coin_rows = []
    dir_to_index = {}

    for dir_name, cat_entry in catalog.items():
        numista_id = cat_entry["numista_id"]
        print(f"\n  {dir_name} (Numista #{numista_id})")

        row = None
        if numista_key:
            data = fetch_numista_coin(numista_id, numista_key)
            if data:
                row = numista_to_coin_row(data)
                print(f"    → {row['name']} ({row['country']}, {row['year']})")

        if row is None:
            # Use catalog entry as fallback
            row = {
                "numista_id": numista_id,
                "name": cat_entry["name"],
                "country": cat_entry["country"],
                "year": cat_entry["year"],
                "face_value": cat_entry["face_value"],
                "type": cat_entry["type"],
                "mintage": None,
                "image_obverse_url": None,
                "image_reverse_url": None,
            }
            print(f"    → Using catalog fallback: {row['name']}")

        dir_to_index[dir_name] = len(coin_rows)
        coin_rows.append(row)

    inserted_coins = supabase_upsert(supabase_url, supabase_key, "coins", coin_rows, on_conflict="numista_id")
    print(f"\nInserted {len(inserted_coins)} coins")

    # Build dir_name → UUID mapping (using insertion order)
    dir_to_uuid = {}
    for dir_name, idx in dir_to_index.items():
        dir_to_uuid[dir_name] = inserted_coins[idx]["id"]

    # Step 2: Insert embeddings
    print("\n--- Seeding coin_embeddings table ---")
    embeddings_path = Path(args.embeddings)
    if not embeddings_path.exists():
        print(f"Embeddings file not found: {embeddings_path}")
        print("Run compute_embeddings.py first!")
        sys.exit(1)

    with open(embeddings_path) as f:
        emb_data = json.load(f)

    embedding_rows = []
    for dir_name, coin_uuid in dir_to_uuid.items():
        coin_emb = emb_data.get("coins", {}).get(dir_name)
        if not coin_emb:
            print(f"  WARNING: No embedding for {dir_name}, skipping")
            continue

        embedding_rows.append({
            "coin_id": coin_uuid,
            "embedding": coin_emb["embedding"],
            "model_version": "v1",
        })

    if embedding_rows:
        inserted_emb = supabase_upsert(supabase_url, supabase_key, "coin_embeddings", embedding_rows, on_conflict="coin_id")
        print(f"Inserted {len(inserted_emb)} embeddings")
    else:
        print("No embeddings to insert.")

    print("\nDone! Seeding complete.")


def main():
    parser = argparse.ArgumentParser(description="Seed Supabase with coin data")
    parser.add_argument(
        "--embeddings", type=str,
        default="./output/embeddings_v1.json",
        help="Path to embeddings JSON",
    )
    args = parser.parse_args()
    seed(args)


if __name__ == "__main__":
    main()
