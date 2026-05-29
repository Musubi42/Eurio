"""Découverte des 2 € **standards** (circulation, non-commémo) via le resolver V2.

Complète ``discover_numista_recent.py`` (commémo, legacy ``compute_eurio_id``)
qui ignore les standards : son pré-filtre exige des parenthèses dans le titre
et confirme ``type == 'commemorative'``. Les pièces de circulation
(« 2 Euros - Philippe », « 2 Euros (1st map) », « 2 Euros ») passent donc à
travers les mailles.

Doctrine V2 (cf. plan extraction riche Numista) :

  * l'``eurio_id`` est dérivé du **resolver canonique**
    ``numista_eurio_id.eurio_id_from_numista_payload`` — le MÊME que le refetch
    (``scripts/refetch_numista_2eur``). On n'utilise PAS ``compute_eurio_id``,
    qui produisait des slugs divergents (risque de collision Type, flaggé).
  * le discover crée le **Type** (row ``coins``, ``is_commemorative=0``) ; les
    **millésimes** (``coin_mint_releases``) sont créés par le refetch.
  * provenance first-class + vocabulaire registry (``source='numista_api'``) :
    on réutilise les transforms/writer Numista pour que la row coin soit
    bit-identique à celle du refetch (zéro drift).

Quota : les détails ``/types/{nid}`` sont écrits dans le cache disque partagé
(``state/numista_cache/{nid}/type.json``) pour que le refetch les réutilise
sans re-fetch.

Idempotent : un ``numista_id`` déjà en base est skip. Re-jouable.

Usage::

    python -m scripts.discover_numista_standards --country FR --dry-run
    python -m scripts.discover_numista_standards --country FR        # apply
    python -m scripts.discover_numista_standards --country FR --country DE
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from referential.numista_eurio_id import (  # noqa: E402
    eurio_id_from_numista_payload,
    related_canonical_nid,
)
from referential.numista_keys import KeyManager  # noqa: E402
from referential.numista_transforms import (  # noqa: E402
    coin_canonical_image_rows,
    coin_row,
    coin_source_ref_row,
    design_group_row,
)
from referential.numista_writer import NumistaWriter  # noqa: E402
from referential.refetch_numista_2eur import (  # noqa: E402
    NUMISTA_ISSUER_CODE,
    api_search,
    api_type_details,
)

logger = logging.getLogger("discover_numista_standards")

DEFAULT_DB = ROOT / "state" / "eurio.db"
DEFAULT_CACHE = ROOT / "state" / "numista_cache"
THROTTLE = 0.4  # politeness delay between API calls


def _is_2euro_title(title: str) -> bool:
    """Pré-filtre large : titre « 2 euro(s) … » hors centimes. Contrairement
    au discover commémo, on n'exige PAS de parenthèses (les standards comme
    « 2 Euros - Philippe » n'en ont pas forcément)."""
    t = (title or "").strip().lower()
    if not t.startswith("2 euro"):
        return False
    if "cent" in t:  # exclure "2 Euro Cents"
        return False
    return True


def _cached_or_fetch_detail(
    km: KeyManager, cache_dir: Path, nid: int
) -> dict:
    """Lit ``{cache_dir}/{nid}/type.json`` s'il existe (zéro call), sinon fetch
    le détail EN via KeyManager et l'écrit dans le cache partagé du refetch."""
    import json

    cache_path = cache_dir / str(nid) / "type.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    detail = km.call(api_type_details, nid)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(detail, indent=2, ensure_ascii=False))
    return detail


def discover_standards(
    conn: sqlite3.Connection,
    km: KeyManager,
    *,
    countries: list[str],
    cache_dir: Path,
    dry_run: bool,
    include_commemorative: bool = False,
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict:
    conn.row_factory = sqlite3.Row

    known_nids = {r[0] for r in conn.execute(
        "SELECT numista_id FROM coins WHERE numista_id IS NOT NULL"
    )}
    logger.info("known numista_ids in eurio.db: %d", len(known_nids))

    writer = NumistaWriter(conn)
    discovered: list[dict] = []
    api_calls = 0
    skipped = {"known": 0, "pre_filter": 0, "out_of_scope": 0, "commemo": 0,
               "year": 0}
    by_country: dict[str, dict] = {}

    for iso2 in countries:
        issuer = NUMISTA_ISSUER_CODE.get(iso2)
        if not issuer:
            logger.warning("[%s] pas de code issuer Numista — skip", iso2)
            continue
        stats = {"candidates": 0, "new_standards": 0, "errors": 0}

        page = 1
        types_seen = 0
        while True:
            try:
                resp = km.call(api_search, issuer, page, 50)
                api_calls += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] search page=%d FAIL: %s", iso2, page, exc)
                stats["errors"] += 1
                break

            types = resp.get("types") or []
            if not types:
                break
            types_seen += len(types)

            for t in types:
                nid = int(t["id"])
                title = t.get("title") or ""
                if not _is_2euro_title(title):
                    skipped["pre_filter"] += 1
                    continue
                if nid in known_nids:
                    skipped["known"] += 1
                    continue

                stats["candidates"] += 1

                if dry_run:
                    discovered.append({
                        "iso2": iso2, "numista_id": nid, "title": title,
                        "resolved": "(dry-run, détail non fetché)",
                    })
                    continue

                try:
                    detail = _cached_or_fetch_detail(km, cache_dir, nid)
                    api_calls += 1
                    time.sleep(THROTTLE)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] details %d FAIL: %s", iso2, nid, exc)
                    stats["errors"] += 1
                    continue

                slug = eurio_id_from_numista_payload(detail)
                if slug is None:
                    skipped["out_of_scope"] += 1
                    continue
                if slug.is_commemorative and not include_commemorative:
                    # Les commémo sont du ressort de discover_numista_recent /
                    # du refetch ; ce script cible les standards.
                    skipped["commemo"] += 1
                    continue
                if year_from is not None and slug.year < year_from:
                    skipped["year"] += 1
                    continue
                if year_to is not None and slug.year > year_to:
                    skipped["year"] += 1
                    continue

                # Chantier variantes : une variante a son propre eurio_id
                # `base-{kind}`. Groupage via related_types (source primaire),
                # puis tiebreak même-kind via compteur idempotent.
                review_reason = None
                if slug.canonical_eurio_id is not None:
                    nid_can, ambiguous = related_canonical_nid(detail)
                    resolved = (writer.resolve_eurio_for_nid(nid_can, cache_dir)
                                if nid_can else None)
                    if resolved and resolved != slug.eurio_id:
                        slug = replace(slug, canonical_eurio_id=resolved)
                    elif not resolved:
                        review_reason = "variant_canonical_unresolved"
                    if ambiguous:
                        review_reason = "variant_canonical_ambiguous"
                    unique = writer.unique_eurio_id(slug.eurio_id, nid)
                    if unique != slug.eurio_id:
                        slug = replace(slug, eurio_id=unique)

                try:
                    conn.execute("BEGIN IMMEDIATE")
                    # Réutilise les transforms/writer du refetch → row coin
                    # bit-identique (même eurio_id, même shape, registry).
                    writer.write_design_group(design_group_row(slug))  # None pour standard
                    writer.write_coin(coin_row(slug, detail))
                    if review_reason:
                        conn.execute(
                            "UPDATE coins SET needs_review = 1, review_reason = ? "
                            "WHERE eurio_id = ?", (review_reason, slug.eurio_id))
                    writer.write_source_ref(coin_source_ref_row(slug, detail))
                    writer.write_images(coin_canonical_image_rows(slug, detail))
                    conn.execute("COMMIT")
                except Exception as exc:  # noqa: BLE001
                    conn.execute("ROLLBACK")
                    logger.warning("[%s] write %s FAIL: %s", iso2, slug.eurio_id, exc)
                    stats["errors"] += 1
                    continue

                known_nids.add(nid)
                stats["new_standards"] += 1
                discovered.append({
                    "iso2": iso2, "numista_id": nid, "year": slug.year,
                    "eurio_id": slug.eurio_id, "is_commemorative": slug.is_commemorative,
                    "title": title,
                })
                logger.info("  NEW %s nid=%d %s", slug.eurio_id, nid, title[:60])

            total = int(resp.get("count") or 0)
            if types_seen >= total:
                break
            page += 1
            time.sleep(THROTTLE)

        by_country[iso2] = stats

    return {
        "countries": countries,
        "api_calls": api_calls,
        "n_discovered": len(discovered),
        "skipped": skipped,
        "by_country": by_country,
        "discovered": discovered,
    }


def main() -> int:
    import json

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--country", action="append", dest="countries",
                   help="ISO2 (répétable). Default: tous les pays eurozone.")
    p.add_argument("--include-commemorative", action="store_true",
                   help="Aussi créer les commémo via le resolver V2 (par "
                        "défaut on ne garde que les standards).")
    p.add_argument("--year-from", type=int, default=None)
    p.add_argument("--year-to", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    countries = ([c.upper() for c in args.countries]
                 if args.countries else list(NUMISTA_ISSUER_CODE.keys()))

    km = KeyManager(db_path=args.db)
    conn = sqlite3.connect(args.db, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        summary = discover_standards(
            conn, km,
            countries=countries,
            cache_dir=args.cache_dir,
            dry_run=args.dry_run,
            include_commemorative=args.include_commemorative,
            year_from=args.year_from,
            year_to=args.year_to,
        )
    finally:
        conn.close()

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
