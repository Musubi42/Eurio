"""Seed the `sets` table with auto-generated structural achievement sets.

Generates ~55 sets from the current referential, grouped by 3 categories:

1. **Per-series circulation** — one set per entry in `coin_series` (~32 sets).
   Uses `series_id` as the criteria so the set updates automatically when
   new coin millésimes are minted within the series.

2. **Per-country national commemoratives** — one set per eurozone country +
   Monaco/San Marino/Vatican (~24 sets). Uses
   `{country, issue_type: 'commemo-national'}`. Country codes are UPPERCASE
   to match the legacy `coins.country` column convention.

3. **Hunt sets** — cross-cutting collector goals:
   - `micro-states` — circulation €2 from MC/SM/VA/AD (4 slots)
   - `eurozone-tour` — circulation €2 from each eurozone country (21 slots)
   - `withdrawn-collector` — any coin with `is_withdrawn=true` (0 for now,
     modelling exercise)

**NOT seeded** (pending architectural clarification):
BCE common commemoratives (Rome 2007, EMU 2009, etc.) are currently stored
as 1 row per theme with country='eu' and a national_variants jsonb listing
the participating countries (Option A from DECISIONS). That model doesn't
map cleanly to a set of N distinct owned coins — you'd own "Rome 2007" as a
single eurio_id rather than 13 per-country variants. Creating sets for them
would give misleading progress (1/1 after one scan instead of 1/13).
→ Revisit when the referential is refactored to emit one row per
(theme, country) pair.

All sets are structural (DSL-driven). No curated sets are seeded — those are
created editorially via the admin tool.

name_i18n is populated with `fr` and `en` at minimum (required by CHECK
constraint). `de` and `it` are left for the admin tool to fill.

Idempotent on `sets.id` via upsert. Dry-run by default.

Usage:
    python ml/seed_sets.py              # dry-run
    python ml/seed_sets.py --apply      # actually write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sync_to_supabase import PostgrestClient, load_env

SEED_PATH = Path(__file__).parent / "data" / "coin_series_seed.json"

# Country codes UPPERCASE to match the legacy `coins.country` column convention.
# Eurozone 21 (as of 2026)
EUROZONE = [
    "BE", "DE", "IE", "ES", "FR", "IT", "LU", "NL", "AT", "PT",
    "FI", "GR", "SI", "CY", "MT", "SK", "EE", "LV", "LT", "HR", "BG",
]
MICRO_STATES = ["MC", "SM", "VA", "AD"]

COUNTRY_NAMES_FR = {
    "BE": "Belgique", "DE": "Allemagne", "IE": "Irlande", "ES": "Espagne",
    "FR": "France", "IT": "Italie", "LU": "Luxembourg", "NL": "Pays-Bas",
    "AT": "Autriche", "PT": "Portugal", "FI": "Finlande", "GR": "Grèce",
    "SI": "Slovénie", "CY": "Chypre", "MT": "Malte", "SK": "Slovaquie",
    "EE": "Estonie", "LV": "Lettonie", "LT": "Lituanie", "HR": "Croatie",
    "BG": "Bulgarie", "MC": "Monaco", "SM": "Saint-Marin", "VA": "Vatican",
    "AD": "Andorre",
}

COUNTRY_NAMES_EN = {
    "BE": "Belgium", "DE": "Germany", "IE": "Ireland", "ES": "Spain",
    "FR": "France", "IT": "Italy", "LU": "Luxembourg", "NL": "Netherlands",
    "AT": "Austria", "PT": "Portugal", "FI": "Finland", "GR": "Greece",
    "SI": "Slovenia", "CY": "Cyprus", "MT": "Malta", "SK": "Slovakia",
    "EE": "Estonia", "LV": "Latvia", "LT": "Lithuania", "HR": "Croatia",
    "BG": "Bulgaria", "MC": "Monaco", "SM": "San Marino", "VA": "Vatican City",
    "AD": "Andorra",
}


def build_sets() -> list[dict[str, Any]]:
    """Build the full list of set rows to upsert."""
    series_data = json.loads(SEED_PATH.read_text())["series"]

    sets: list[dict[str, Any]] = []
    order = 0

    def next_order() -> int:
        nonlocal order
        order += 10
        return order

    # --- 1. Per-series circulation ---
    for s in series_data:
        country = s["country"].upper()
        series_id = s["id"]
        designation = s["designation"]
        sets.append({
            "id": f"circulation-{series_id}",
            "kind": "structural",
            "name_i18n": {
                "fr": f"Circulation {COUNTRY_NAMES_FR.get(country, country)} — {designation}",
                "en": f"{COUNTRY_NAMES_EN.get(country, country)} circulation — {designation}",
            },
            "description_i18n": None,
            "criteria": {
                "series_id": series_id,
                "issue_type": "circulation",
            },
            "param_key": None,
            "reward": {"badge": "silver", "xp": 200},
            "display_order": next_order(),
            "category": "country",
            "icon": None,
            "expected_count": None,
            "active": True,
        })

    # --- 2. Per-country national commemoratives ---
    # AD (Andorra) has no commemos in the current referential → skipped.
    # BCE common commemoratives are NOT seeded here — see module docstring.
    for country in EUROZONE + ["MC", "SM", "VA"]:
        sets.append({
            "id": f"commemos-{country.lower()}",
            "kind": "structural",
            "name_i18n": {
                "fr": f"Commémoratives {COUNTRY_NAMES_FR[country]}",
                "en": f"{COUNTRY_NAMES_EN[country]} commemoratives",
            },
            "description_i18n": None,
            "criteria": {
                "country": country,
                "issue_type": "commemo-national",
            },
            "param_key": None,
            "reward": {"badge": "gold", "xp": 400},
            "display_order": next_order(),
            "category": "country",
            "icon": None,
            "expected_count": None,  # grows over time, not asserted
            "active": True,
        })

    # --- 3. Hunt sets ---
    sets.append({
        "id": "micro-states",
        "kind": "structural",
        "name_i18n": {
            "fr": "Les quatre micro-États",
            "en": "The four microstates",
        },
        "description_i18n": {
            "fr": "Une pièce de 2 € de chacun des quatre micro-États émetteurs (Monaco, Saint-Marin, Vatican, Andorre).",
            "en": "One €2 coin from each of the four microstate issuers (Monaco, San Marino, Vatican City, Andorra).",
        },
        "criteria": {
            "country": MICRO_STATES,
            "issue_type": "circulation",
            "denomination": [2.00],
            "distinct_by": "country",
        },
        "param_key": None,
        "reward": {"badge": "gold", "xp": 500},
        "display_order": next_order(),
        "category": "hunt",
        "icon": None,
        "expected_count": 4,
        "active": True,
    })

    sets.append({
        "id": "eurozone-tour",
        "kind": "structural",
        "name_i18n": {
            "fr": "Le tour de la zone euro",
            "en": "The eurozone tour",
        },
        "description_i18n": {
            "fr": "Une pièce de 2 € de chaque pays de la zone euro (21 pays).",
            "en": "One €2 coin from each country in the eurozone (21 countries).",
        },
        "criteria": {
            "country": EUROZONE,
            "issue_type": "circulation",
            "denomination": [2.00],
            "distinct_by": "country",
        },
        "param_key": None,
        "reward": {"badge": "gold", "xp": 800},
        "display_order": next_order(),
        "category": "hunt",
        "icon": None,
        "expected_count": 21,
        "active": True,
    })

    sets.append({
        "id": "withdrawn-collector",
        "kind": "structural",
        "name_i18n": {
            "fr": "Pièces retirées de la circulation",
            "en": "Withdrawn coins",
        },
        "description_i18n": {
            "fr": "Aucune pièce euro n'a été officiellement retirée de la circulation à ce jour. Ce set existe pour le jour où cela arrive — quand c'est le cas, la valeur de collection explose.",
            "en": "No euro coin has ever been officially withdrawn from circulation. This set exists for the day it happens — when it does, collector value explodes.",
        },
        "criteria": {
            "is_withdrawn": True,
        },
        "param_key": None,
        "reward": {"badge": "gold", "xp": 1000},
        "display_order": next_order(),
        "category": "hunt",
        "icon": None,
        "expected_count": 0,
        "active": True,
    })

    return sets


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Seed the sets table with auto-generated structural sets")
    ap.add_argument("--apply", action="store_true", help="Actually write to Supabase (default is dry-run)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== seed_sets.py [{mode}] ===\n")

    all_sets = build_sets()

    # Breakdown by category
    by_category: dict[str, int] = {}
    for s in all_sets:
        by_category[s["category"]] = by_category.get(s["category"], 0) + 1

    print(f"Built {len(all_sets)} sets:")
    for cat, count in sorted(by_category.items()):
        print(f"  {cat:15} {count:3}")

    print(f"\nSample ids:")
    for s in all_sets[:5]:
        print(f"  {s['id']:40} {s['name_i18n']['fr']}")
    if len(all_sets) > 5:
        print(f"  ... and {len(all_sets) - 5} more")

    env = load_env()
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("\nERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing from .env")
        sys.exit(1)

    if args.apply:
        with PostgrestClient(url, key) as client:
            print(f"\nUpserting {len(all_sets)} sets...")
            client.upsert("sets", all_sets, on_conflict="id")
            total = client.count("sets")
            print(f"  ✓ sets count in DB now: {total}")
    else:
        print(f"\n[dry-run] would upsert {len(all_sets)} sets. Pass --apply to write.")

    print("\n=== done ===")


if __name__ == "__main__":
    main()
