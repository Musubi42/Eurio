"""Pipeline d'ingestion LMDLP — discover → promote (prix par qualité).

Pas d'image, pas de download : la source est pure-métadonnées. Le promote
écrit, pour chaque pièce matchée :

- ``coin_market_quotes`` : 1 row par qualité (``condition_raw`` = libellé LMDLP,
  ``condition_normalized='unknown'`` — un prix boutique neuf ne se fond pas dans
  l'agrégation marché-secondaire eBay ; ``p10=p50=p90`` = prix boutique,
  ``sample_size`` = nb de produits collapsés sur cette qualité).
- ``coin_source_refs`` : 1 row d'identité (source='lmdlp', permalink).

Quand plusieurs produits partagent (eurio_id, qualité) — ex. « BU FDC » nu vs
« BU FDC Coincard » — on retient le **prix minimum** (le plus proche du prix de
la pièce, hors premium packaging) ; tous les SKU/prix sont conservés dans
``raw_payload_json`` pour l'audit.

Période = fenêtre du run (``started_at`` → maintenant) ; chaque run écrit un
snapshot, l'historique s'accumule via la clé unique de ``coin_market_quotes``.

Sortie filesystem par run : ``ml/state/lmdlp_runs/{run_id}.json`` (manifest).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sources._base.adapter import DiscoveredItem, SourceQuery
from sources._base.dedup import CoinMarketQuoteRow, upsert_coin_market_quote
from sources._base.registry_map import to_registry_source
from sources._base.run_logger import RunHandle, start_run
from sources.lmdlp.adapter import LmdlpAdapter
from state.sources_runs import record_run

logger = logging.getLogger(__name__)

_RUNS_DIR = Path(__file__).resolve().parents[2] / "state" / "lmdlp_runs"
_REGISTRY_SOURCE = to_registry_source(SOURCE_ID := "lmdlp")  # → 'lmdlp'


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class LmdlpStepsResult:
    n_discovered: int          # produits matchés émis
    n_coins: int               # pièces distinctes touchées
    n_quotes: int              # rows coin_market_quotes écrites
    n_errors: int


def run_lmdlp_pipeline(
    adapter: LmdlpAdapter,
    query: SourceQuery,
    *,
    store,
    dry_run: bool = False,
    force: bool = False,
) -> str:
    """Exécute le pipeline LMDLP et retourne le ``run_id``."""
    kind = "dry" if dry_run else "run"
    conn = store._connection()  # noqa: SLF001

    with start_run(conn, source=adapter.source_id, kind=kind,
                   filters=asdict(query), force=force) as run:
        logger.info("[lmdlp] run_id=%s kind=%s query=%s", run.run_id, kind, query)
        run.set_step("discover")
        items = list(adapter.discover(query))
        run.bump(n_calls=1)

        if dry_run:
            logger.info("[lmdlp] dry-run : %d produits matchés, on n'écrit rien", len(items))
            _write_manifest(run.run_id, kind, query, items, n_coins=0, n_quotes=0,
                            status="success")
            run.end("success")
            return run.run_id

        run.set_step("price_aggregate")
        result = _promote(conn, run, items)

        status = "partial" if result.n_errors else "success"
        err = f"{result.n_errors} erreur(s) — voir logs" if result.n_errors else None
        _write_manifest(run.run_id, kind, query, items,
                        n_coins=result.n_coins, n_quotes=result.n_quotes, status=status)
        run.end(status, error_summary=err)
        record_run("lmdlp", kind, calls=result.n_discovered, added_coins=result.n_coins)
        logger.info("[lmdlp] run %s done — discovered=%d coins=%d quotes=%d errors=%d",
                    run.run_id, result.n_discovered, result.n_coins,
                    result.n_quotes, result.n_errors)
        return run.run_id


def _promote(
    conn: sqlite3.Connection,
    run: RunHandle,
    items: list[DiscoveredItem],
) -> LmdlpStepsResult:
    """Écrit quotes (1/qualité) + source_refs pour chaque pièce matchée."""
    started = conn.execute(
        "SELECT started_at FROM source_runs WHERE id = ?", (run.run_id,)
    ).fetchone()
    period_start = started["started_at"] if started and started["started_at"] else _now_iso()
    period_end = _now_iso()

    # Groupe par (eurio_id, qualité) → collapse au prix min (+ audit des SKU).
    by_coin_quality: dict[tuple[str, str], list[DiscoveredItem]] = defaultdict(list)
    permalink_by_coin: dict[str, str | None] = {}
    for it in items:
        eurio_id = it.target_eurio_id
        quality = it.condition_raw or "unknown"
        by_coin_quality[(eurio_id, quality)].append(it)
        permalink_by_coin.setdefault(eurio_id, it.source_url)

    n_quotes = 0
    n_errors = 0
    coins_with_quote: set[str] = set()

    for (eurio_id, quality), group in by_coin_quality.items():
        priced = [g for g in group if g.listing_price is not None and g.listing_price > 0]
        if not priced:
            continue
        rep = min(priced, key=lambda g: g.listing_price)  # prix le plus bas = pièce nue
        price = float(rep.listing_price)
        variants = [{"sku": (g.raw_payload or {}).get("sku"),
                     "price_eur": g.listing_price,
                     "in_stock": (g.raw_payload or {}).get("in_stock")}
                    for g in priced]
        try:
            upsert_coin_market_quote(conn, CoinMarketQuoteRow(
                eurio_id=eurio_id,
                source=_REGISTRY_SOURCE,
                period_start=period_start,
                period_end=period_end,
                condition_raw=quality,
                condition_normalized="unknown",
                currency="EUR",
                p10=price, p50=price, p90=price,
                sample_size=len(priced),
                run_id=run.run_id,
                raw_payload={
                    "kind": "merchant_catalog",
                    "permalink": rep.source_url,
                    "sku": (rep.raw_payload or {}).get("sku"),
                    "variants": variants,
                },
            ))
            n_quotes += 1
            coins_with_quote.add(eurio_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[lmdlp] upsert quote FAILED eurio=%s qual=%s: %s",
                           eurio_id, quality, exc)
            n_errors += 1
            run.bump(n_errors=1)

    # source_refs : 1 row d'identité par pièce ayant ≥1 quote.
    for eurio_id in coins_with_quote:
        try:
            conn.execute(
                """
                INSERT INTO coin_source_refs
                  (target_kind, target_id, source, source_native_id, source_url)
                VALUES ('coin', ?, ?, ?, ?)
                ON CONFLICT (target_kind, target_id, source) DO UPDATE SET
                  source_native_id = excluded.source_native_id,
                  source_url       = excluded.source_url,
                  fetched_at       = datetime('now')
                """,
                (eurio_id, _REGISTRY_SOURCE, eurio_id, permalink_by_coin.get(eurio_id)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[lmdlp] upsert source_ref FAILED eurio=%s: %s", eurio_id, exc)
            n_errors += 1
            run.bump(n_errors=1)

    run.bump(n_quotes_added=n_quotes)
    conn.commit()
    return LmdlpStepsResult(
        n_discovered=len(items),
        n_coins=len(coins_with_quote),
        n_quotes=n_quotes,
        n_errors=n_errors,
    )


def _write_manifest(
    run_id: str,
    kind: str,
    query: SourceQuery,
    items: list[DiscoveredItem],
    *,
    n_coins: int,
    n_quotes: int,
    status: str,
) -> Path:
    """Manifest JSON par run (audit offline, mirror de ml/state/bce_runs/)."""
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    matched = sorted({it.target_eurio_id for it in items})
    manifest = {
        "run_id": run_id,
        "source": "lmdlp",
        "kind": kind,
        "status": status,
        "written_at": _now_iso(),
        "query": asdict(query),
        "n_products_matched": len(items),
        "n_coins": n_coins,
        "n_quotes": n_quotes,
        "matched_eurio_ids": matched,
    }
    path = _RUNS_DIR / f"{run_id}.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
