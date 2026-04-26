"""One-time migration: rename dataset directories from slug names to Numista IDs.

Run once:
    .venv/bin/python rename_to_numista_ids.py
"""

import json
import shutil
from pathlib import Path

CATALOG_PATH = Path(__file__).parent.parent / "datasets" / "coin_catalog.json"
DATASETS_DIR = Path(__file__).parent.parent / "datasets"


def main():
    with open(CATALOG_PATH) as f:
        catalog = json.load(f)

    coins = catalog.get("coins", {})
    renamed = 0

    for key, value in list(coins.items()):
        numista_id = str(value["numista_id"])

        # Skip if already keyed by numista_id
        if key == numista_id:
            continue

        old_dir = DATASETS_DIR / key
        new_dir = DATASETS_DIR / numista_id

        if old_dir.exists():
            if new_dir.exists():
                print(f"  SKIP {key} → {numista_id} (target exists)")
                continue
            old_dir.rename(new_dir)
            print(f"  RENAMED {key} → {numista_id}")
            renamed += 1
        else:
            print(f"  SKIP {key} (directory not found)")

    print(f"\nRenamed {renamed} directories.")
    print("Now run: .venv/bin/python import_numista.py")
    print("The import script will also migrate coin_catalog.json keys to numista IDs.")


if __name__ == "__main__":
    main()
