"""Step 7 — Agrégation des prix de référence (chunk C3 — pipeline prix).

Tourne en fin de pipeline, après ``enqueue``. Pour chaque coin touché
par le run, agrège les annonces ``single`` (pièce nue) découvertes par
ce run en un prix de référence par tier d'état, et persiste le résultat
dans ``coin_market_quotes`` — une ligne par (coin, source, période,
tier).

Pourquoi only ``single`` : lots, coffrets et slabs gradés portent un
premium (multi-pièces, emballage, grade) qui n'est pas le prix de la
pièce nue que l'utilisateur scanne. Ils sont stockés et taggés
(``listing_kind``, chunk C2) mais exclus du prix de référence.

Période = la fenêtre du run (``started_at`` → maintenant). Chaque run
écrit donc un snapshot — l'historique de prix s'accumule run après run,
sans code dédié (la clé unique de ``coin_market_quotes`` inclut
``period_start``).

Le prix reste un prix *demandé* (Browse API = annonces actives) : la
pondération vélocité (cf. ``sources/pricing/aggregate``) atténue le
biais haussier en sous-pondérant les annonces anciennes invendues.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from sources._base.dedup import CoinMarketQuoteRow, upsert_coin_market_quote
from sources.pricing import PricedListing, aggregate_priced_listings

logger = logging.getLogger(__name__)


@dataclass
class PriceAggregateResult:
    n_coins: int          # coins ayant ≥1 annonce single exploitable
    n_quotes: int         # lignes coin_market_quotes écrites (tiers confondus)
    n_listings: int       # annonces single dédupliquées agrégées


def _listing_key(source_url: str | None, source_ref: str) -> str:
    """Identité d'un listing eBay (N images → N source_images, 1 listing).

    ``source_url`` est identique pour toutes les images d'un listing ;
    fallback sur ``source_ref`` sans le suffixe ``_img<N>``.
    """
    if source_url:
        return source_url
    return source_ref.rsplit("_img", 1)[0]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Called by: ml/sources/_base/orchestrator.py (step 7 — after enqueue)
def run_price_aggregate(
    *,
    conn: sqlite3.Connection,
    run_id: str,
    source: str,
) -> PriceAggregateResult:
    """Agrège les prix des annonces single du run → ``coin_market_quotes``."""
    started = conn.execute(
        "SELECT started_at FROM source_runs WHERE id = ?", (run_id,)
    ).fetchone()
    period_start = (started["started_at"] if started and started["started_at"]
                    else _now_iso())
    period_end = _now_iso()

    rows = conn.execute(
        """
        SELECT si.target_eurio_id AS eurio_id,
               si.listing_price   AS price,
               si.listing_origin_date AS origin_date,
               si.sold_qty        AS sold_qty,
               si.source_url      AS source_url,
               si.source_ref      AS source_ref,
               lts.condition_normalized AS condition
          FROM source_images si
          JOIN listing_text_signals lts ON lts.source_image_id = si.id
         WHERE si.run_id = ?
           AND si.source = ?
           AND si.target_eurio_id IS NOT NULL
           AND si.listing_price IS NOT NULL
           AND si.listing_price > 0
           AND si.listing_currency = 'EUR'
           AND lts.listing_kind = 'single'
        """,
        (run_id, source),
    ).fetchall()

    # Dédup : 1 PricedListing par (coin, listing) — les N images d'un
    # listing partagent prix / état.
    per_coin: dict[str, dict[str, PricedListing]] = {}
    for r in rows:
        key = _listing_key(r["source_url"], r["source_ref"])
        listings = per_coin.setdefault(r["eurio_id"], {})
        if key in listings:
            continue
        listings[key] = PricedListing(
            price=float(r["price"]),
            condition=r["condition"] or "UNC",  # NULL = row pré-C2
            sold_qty=int(r["sold_qty"] or 0),
            origin_date=r["origin_date"],
        )

    n_quotes = 0
    n_listings = 0
    for eurio_id, listings in per_coin.items():
        n_listings += len(listings)
        for q in aggregate_priced_listings(list(listings.values())):
            upsert_coin_market_quote(conn, CoinMarketQuoteRow(
                eurio_id=eurio_id,
                source=source,
                period_start=period_start,
                period_end=period_end,
                condition_raw=q.condition,
                condition_normalized=q.condition,
                currency="EUR",
                p10=q.p10,
                p50=q.p50,
                p90=q.p90,
                sample_size=q.sample_size,
                run_id=run_id,
                raw_payload={"n_raw": q.n_raw, "n_after_outlier": q.sample_size},
            ))
            n_quotes += 1
    conn.commit()

    logger.info(
        "[%s] price_aggregate → %d coins / %d single listings / %d quotes",
        source, len(per_coin), n_listings, n_quotes,
    )
    return PriceAggregateResult(
        n_coins=len(per_coin),
        n_quotes=n_quotes,
        n_listings=n_listings,
    )
