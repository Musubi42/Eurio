"""Sweep Numista pour découvrir des commémo 2 € fraîches (ce que la BCE ne
publie pas encore).

Contexte : la BCE (oracle officiel) lag d'environ un an sur le quotidien
(cf. son disclaimer renvoyant au JOUE série C). Numista, communautaire, index
typiquement en quelques semaines après l'annonce JOUE. C'est notre source
primaire pour les pièces 2026+.

Flow par run :

  1. Pour chaque pays eurozone (24 entries, hors placeholders Numista) :
     ``GET /v3/types?issuer={code}&q=2 euros&category=coin``
  2. Filtrage client-side : titre commence par "2 euros", parenthèses présentes
     (pattern commémo), ``min_year`` >= ``year_from``.
  3. ``numista_id`` déjà en ``coins`` ? → skip.
  4. Sinon ``GET /v3/types/{nid}`` → confirme ``type == 'commemorative'``,
     récupère payload + ``obverse.picture`` / ``reverse.picture``.
  5. INSERT row dans ``coins`` (eurio_id généré via ``compute_eurio_id``) +
     ``coin_canonical_images`` pour les URLs Numista.
  6. (Optionnel) cascade vers ``migrate_canonical_images_local`` pour télécharger
     et stocker localement.

Idempotent : un numista_id déjà connu est skip. Re-jouable.

Usage::

    python -m scripts.discover_numista_recent --dry-run
    python -m scripts.discover_numista_recent --year-from 2025 --year-to 2027
    python -m scripts.discover_numista_recent                # default: now-1 → now+1
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from referential.eurio_referential import compute_eurio_id, slugify  # noqa: E402
from referential.numista_keys import KeyManager  # noqa: E402
from referential.refetch_numista_2eur import (  # noqa: E402
    NUMISTA_ISSUER_CODE,
    api_search,
    api_type_details,
)

logger = logging.getLogger("discover_numista_recent")

DEFAULT_DB = ROOT / "state" / "eurio.db"
THROTTLE = 0.4  # courtesy delay between API calls

# 24 codes : on retire `germany` et `lithuania` qui pointent vers issuers
# historiques côté Numista. Les modernes utilisent `allemagne` / `lituanie`.
EUROZONE_ISO2 = list(NUMISTA_ISSUER_CODE.keys())

# Country full names (pour bootstrap coins.country_name)
COUNTRY_NAMES: dict[str, str] = {
    "AD": "Andorra", "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria",
    "CY": "Cyprus", "DE": "Germany", "EE": "Estonia", "ES": "Spain",
    "FI": "Finland", "FR": "France", "GR": "Greece", "HR": "Croatia",
    "IE": "Ireland", "IT": "Italy", "LT": "Lithuania", "LU": "Luxembourg",
    "LV": "Latvia", "MC": "Monaco", "MT": "Malta", "NL": "Netherlands",
    "PT": "Portugal", "SI": "Slovenia", "SK": "Slovakia", "SM": "San Marino",
    "VA": "Vatican City",
}

# Vatican + Monaco = collector_only (pas circulation grand public).
COLLECTOR_ONLY = {"VA", "MC"}

# Title example: "2 Euros (Bearded vulture)" → extract "Bearded vulture".
_THEME_RE = re.compile(r"^2\s*[Ee]uros?\s*\(([^)]+)\)\s*$")


def _extract_theme(title: str) -> str:
    m = _THEME_RE.match(title.strip())
    return (m.group(1).strip() if m else title.strip())


def _is_commemorative_title(title: str) -> bool:
    """Heuristique pré-API : 2 euros avec parenthèses = probablement commémo.
    Le check définitif est ``type == 'commemorative'`` côté ``/v3/types/{nid}``.
    """
    t = title.strip().lower()
    if not t.startswith("2 euro"):
        return False
    if "cent" in t:  # exclure "2 Euro Cents"
        return False
    return "(" in title  # parenthèses → commémo


def discover(
    conn: sqlite3.Connection,
    km: KeyManager,
    *,
    year_from: int,
    year_to: int,
    dry_run: bool,
    limit_countries: list[str] | None = None,
) -> dict:
    conn.row_factory = sqlite3.Row

    # Index des numista_id déjà connus en DB.
    known_nids = {r[0] for r in conn.execute(
        "SELECT numista_id FROM coins WHERE numista_id IS NOT NULL"
    )}
    logger.info("known numista_ids in eurio.db: %d", len(known_nids))

    countries = [c for c in EUROZONE_ISO2 if (not limit_countries or c in limit_countries)]
    logger.info("countries to sweep: %s", countries)

    discovered: list[dict] = []
    api_calls = 0
    n_skipped_known = 0
    n_skipped_pre_filter = 0
    n_skipped_not_commemo = 0
    by_country: dict[str, dict] = {}

    for iso2 in countries:
        issuer = NUMISTA_ISSUER_CODE[iso2]
        country_stats = {"searched": 0, "candidates": 0, "new": 0, "errors": 0}

        page = 1
        types_seen = 0
        while True:
            try:
                key = km.pick()
                resp = api_search(key, issuer, page=page, count=50)
                km.record_call(key)
                api_calls += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] search page=%d FAIL: %s", iso2, page, exc)
                country_stats["errors"] += 1
                break

            types = resp.get("types") or []
            if not types:
                break
            types_seen += len(types)

            for t in types:
                nid = int(t["id"])
                title = t.get("title") or ""
                min_year = t.get("min_year") or 0

                # Filtre pré-API
                if not _is_commemorative_title(title):
                    n_skipped_pre_filter += 1
                    continue
                if min_year < year_from or min_year > year_to:
                    n_skipped_pre_filter += 1
                    continue
                if nid in known_nids:
                    n_skipped_known += 1
                    continue

                country_stats["candidates"] += 1

                # Fetch détail pour confirmer commemo + récupérer images
                if dry_run:
                    discovered.append({
                        "iso2": iso2, "numista_id": nid, "year": min_year,
                        "title": title, "would_insert": True,
                    })
                    continue

                try:
                    key = km.pick()
                    data = api_type_details(key, nid)
                    km.record_call(key)
                    api_calls += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] details %d FAIL: %s", iso2, nid, exc)
                    country_stats["errors"] += 1
                    continue

                # Confirme commemorative
                coin_type = (data.get("type") or "").lower()
                if "commemorative" not in coin_type:
                    n_skipped_not_commemo += 1
                    continue

                # Build eurio_id
                theme_text = _extract_theme(title)
                theme_slug = slugify(theme_text) or "unknown"
                year = data.get("min_year") or min_year or year_from
                eid = compute_eurio_id(iso2, year, 2.0, theme_slug)

                # Collision : suffixer si nécessaire (rare)
                base_eid = eid
                suffix = 2
                while conn.execute(
                    "SELECT 1 FROM coins WHERE eurio_id = ?", (eid,)
                ).fetchone():
                    eid = f"{base_eid}-v{suffix}"
                    suffix += 1

                # Payload Eurio-format (cf. enrich_missing_payloads pour le schéma)
                obverse = data.get("obverse") or {}
                reverse = data.get("reverse") or {}
                images: dict = {}
                if isinstance(obverse, dict) and obverse.get("picture"):
                    images["obverse"] = obverse["picture"]
                    images["obverse_source"] = "numista"
                if isinstance(reverse, dict) and reverse.get("picture"):
                    images["reverse"] = reverse["picture"]
                    images["reverse_source"] = "numista"

                payload = {
                    "eurio_id": eid,
                    "identity": {
                        "country": iso2,
                        "country_name": COUNTRY_NAMES.get(iso2),
                        "year": year,
                        "face_value": 2.0,
                        "currency": "EUR",
                        "is_commemorative": True,
                        "theme": theme_text,
                        "design_description": (data.get("obverse") or {}).get("description"),
                        "collector_only": iso2 in COLLECTOR_ONLY,
                    },
                    "cross_refs": {"numista_id": nid},
                    "images": images,
                    "provenance": {
                        "source": "numista_v3_discover",
                        "endpoint": f"https://api.numista.com/v3/types/{nid}",
                        "discovered_at": datetime.now(timezone.utc).isoformat(),
                    },
                    "numista_raw": data,
                }

                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT INTO coins
                      (eurio_id, country, country_name, year, face_value,
                       is_commemorative, theme, numista_id, ref_source, ref_native_id,
                       currency, collector_only, design_description, status,
                       raw_payload_json, imported_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        eid, iso2, COUNTRY_NAMES.get(iso2), year, 2.0, 1, theme_text,
                        nid, "numista", str(nid), "EUR",
                        1 if iso2 in COLLECTOR_ONLY else 0,
                        (data.get("obverse") or {}).get("description"),
                        "referenced",
                        json.dumps(payload, ensure_ascii=False),
                        now, now,
                    ),
                )
                # canonical_images : on enregistre les URLs Numista ; le local_path
                # sera rempli par migrate_canonical_images_local au step suivant.
                for role, url in (("obverse", images.get("obverse")),
                                  ("reverse", images.get("reverse"))):
                    if url:
                        conn.execute(
                            "INSERT INTO coin_canonical_images "
                            "(eurio_id, source, role, url, local_path) "
                            "VALUES (?, ?, ?, ?, ?)",
                            # P.3b : registry vocabulary (was 'numista').
                            (eid, "numista_api", role, url, None),
                        )
                conn.commit()
                known_nids.add(nid)
                country_stats["new"] += 1
                discovered.append({
                    "iso2": iso2, "numista_id": nid, "year": year,
                    "eurio_id": eid, "theme": theme_text,
                })
                logger.info("  NEW %s nid=%d %s", eid, nid, theme_text[:60])

                time.sleep(THROTTLE)

            country_stats["searched"] += len(types)
            # Numista renvoie 'count' = total, 'page' = current. On stoppe quand
            # on a vu tous les types.
            total = int(resp.get("count") or 0)
            if types_seen >= total:
                break
            page += 1
            time.sleep(THROTTLE)

        by_country[iso2] = country_stats

    return {
        "year_from": year_from,
        "year_to": year_to,
        "countries_swept": len(countries),
        "api_calls": api_calls,
        "n_discovered": len(discovered),
        "n_skipped_known": n_skipped_known,
        "n_skipped_pre_filter": n_skipped_pre_filter,
        "n_skipped_not_commemo": n_skipped_not_commemo,
        "by_country": by_country,
        "discovered": discovered,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--year-from", type=int, default=None,
                   help="Année min (default: now-1)")
    p.add_argument("--year-to", type=int, default=None,
                   help="Année max (default: now+1)")
    p.add_argument("--countries", nargs="*", default=None,
                   help="Liste d'ISO2 à limiter (default: tous)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    now_year = datetime.now(timezone.utc).year
    year_from = args.year_from if args.year_from is not None else now_year - 1
    year_to = args.year_to if args.year_to is not None else now_year + 1

    km = KeyManager(db_path=args.db)
    conn = sqlite3.connect(args.db)
    try:
        summary = discover(
            conn, km,
            year_from=year_from, year_to=year_to,
            dry_run=args.dry_run,
            limit_countries=args.countries,
        )
    finally:
        conn.close()

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
