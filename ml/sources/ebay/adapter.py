"""eBay adapter for the ingestion orchestrator.

Implements ``SourceAdapter`` (sources/_base/adapter.py). Two methods :

* ``discover(query)`` — receives a SourceQuery with **a single**
  ``target_eurio_id`` (the orchestrator unfolds batches at the
  Discover step). Builds a tightly scoped Browse API search, optionally
  expands item groups (multi-year variations), fetches per-listing HD
  images via ``item/{id}`` (D-22), and yields one ``DiscoveredItem``
  per *image* of each accepted listing. ``source_ref`` follows the
  pattern ``ebay_<itemId>_img<N>`` to keep the "1 source_image = 1 file"
  contract (cf. schema.md / ebay-kickoff.md §"Convention source_ref").

* ``download_raw(item, dest)`` — fetches the image file from the eBay
  CDN (``ebayimg.com``), writes atomically, returns size + sha256 +
  pixel dims. CDN downloads are **not** counted against the Browse API
  quota.

Filtres anti-bruit (proof, fautée, métaux précieux) sont appliqués
avant le yield (économise des ``item/{id}`` calls inutiles). Le flag
``is_lot_suspected`` (D-26 niveau 1) est calculé sur le titre et
propagé sur **tous** les images d'un même listing.

Le quota Browse est tracké par ``EbayClient.QuotaTracker`` (déjà
câblé via ``api_call_log`` SQLite). Si épuisé, ``EbayClient`` lève
``httpx.HTTPStatusError`` 429 et l'orchestrateur attrape via
``n_errors`` (D-25 — recovery par idempotence).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx

from market.ebay_client import EbayClient
from sources._base.adapter import DiscoveredItem, RawDownloadResult, SourceQuery
from sources.ebay.filters import (
    accept_listing,
    is_lot_suspected,
    listing_row,
)
from sources.ebay.queries import (
    EbayQuery,
    build_query,
    load_coin,
    title_matches_theme,
)

logger = logging.getLogger(__name__)

# Cap on item-group expansion per search (multi-year variation pages
# inflate quota cost — top-K is enough to surface the cheapest variants).
DEFAULT_GROUP_EXPAND_TOP_K = 2
DEFAULT_SEARCH_LIMIT = 50              # D-23 — no pagination V1
DEFAULT_DOWNLOAD_TIMEOUT_SEC = 30


@dataclass
class EbayAdapter:
    """Glue between the EbayClient and the orchestrator's SourceAdapter contract.

    Pas de state interne : on prend ``client`` (déjà avec token + tracker)
    et ``conn`` (pour résoudre eurio_id → coin via la table ``coins``).
    Une instance == un run, mais le tracker ``EbayClient`` survit
    cross-run (table SQLite).
    """

    client: EbayClient
    conn: sqlite3.Connection
    source_id: str = "ebay"
    search_limit: int = DEFAULT_SEARCH_LIMIT
    group_expand_top_k: int = DEFAULT_GROUP_EXPAND_TOP_K
    download_timeout: int = DEFAULT_DOWNLOAD_TIMEOUT_SEC
    # Dry-run mode (set by orchestrator via run_pipeline(..., dry_run=True)
    # propagated through CLI/API). Skip item/{id} HD expansion to keep the
    # preview cheap : 1 search call per eurio_id instead of ~10.
    dry_run: bool = False

    # ── Discover ────────────────────────────────────────────────────────────

    def discover(self, query: SourceQuery) -> Iterable[DiscoveredItem]:
        """Yield 1 DiscoveredItem per image of each accepted listing.

        The orchestrator already unfolded a batch into per-eurio_id
        sub-queries — we expect ``query.target_eurio_id`` to be set.
        """
        if not query.target_eurio_id:
            raise ValueError(
                "EbayAdapter.discover requires query.target_eurio_id set "
                "(orchestrator should unfold target_eurio_ids)."
            )

        coin = load_coin(self.conn, query.target_eurio_id)
        ebay_q = build_query(coin)
        ambiguous = self._is_ambiguous_country_year(coin.country, coin.year)

        logger.info(
            "[ebay] eurio=%s q=%r aspect=%r ambiguous=%s theme_tokens=%s",
            coin.eurio_id, ebay_q.q, ebay_q.aspect_filter, ambiguous, ebay_q.theme_tokens,
        )

        listings = self._search_and_expand(ebay_q, ambiguous=ambiguous)
        kept: list[dict] = []
        for row in listings:
            ok, reason = accept_listing(row, coin.face_value)
            if not ok:
                logger.debug("[ebay] reject item_id=%s reason=%s", row.get("item_id"), reason)
                continue
            kept.append(row)

        logger.info(
            "[ebay] eurio=%s search_raw=%d kept=%d",
            coin.eurio_id, len(listings), len(kept),
        )

        # D-22 — fetch HD images via item/{id}, then yield one DiscoveredItem
        # per image (image[0] + additionalImages[*]).
        for row in kept:
            yield from self._yield_listing_images(row=row, coin=coin)

    # ── Download ───────────────────────────────────────────────────────────

    def download_raw(self, item: DiscoveredItem, dest: Path) -> RawDownloadResult:
        url = (item.raw_payload or {}).get("image_url")
        if not url:
            raise ValueError(
                f"DiscoveredItem missing raw_payload['image_url'] (source_ref={item.source_ref})"
            )

        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=self.download_timeout, follow_redirects=True) as cl:
            resp = cl.get(url)
            resp.raise_for_status()
            data = resp.content

        # Atomic write — temp file in same dir, rename at the end.
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp_path, dest)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        sha = hashlib.sha256(data).hexdigest()
        width, height = _try_image_dims(data)
        return RawDownloadResult(
            storage_path=dest,
            bytes=len(data),
            sha256=sha,
            width=width,
            height=height,
        )

    # ── Internals ──────────────────────────────────────────────────────────

    def _is_ambiguous_country_year(self, country: str, year: int) -> bool:
        """True if more than one 2€ commemo exists for this (country, year).

        When ambiguous, listings whose title doesn't match the theme tokens
        are dropped (otherwise we'd ingest images of a sibling commemo
        under the wrong eurio_id label).
        """
        n = self.conn.execute(
            """
            SELECT count(*) AS n
              FROM coins
             WHERE country = ?
               AND year = ?
               AND face_value = 2.0
               AND is_commemorative = 1
            """,
            (country, year),
        ).fetchone()["n"]
        return n > 1

    def _search_and_expand(self, ebay_q: EbayQuery, *, ambiguous: bool) -> list[dict]:
        search = self.client.search(
            ebay_q.q,
            category_ids=ebay_q.category_id,
            aspect_filter=ebay_q.aspect_filter,
            filter_expr="price:[1..500],priceCurrency:EUR",
            limit=self.search_limit,
        )
        summaries = search.get("itemSummaries") or []

        rows: list[dict] = []
        group_ids: list[str] = []
        for it in summaries:
            row = listing_row(it)
            if row.get("primary_group_id"):
                gid = row["primary_group_id"]
                if gid not in group_ids:
                    group_ids.append(gid)
            else:
                rows.append(row)

        # Expansion limitée — coût quota maîtrisé.
        for gid in group_ids[: self.group_expand_top_k]:
            try:
                data = self.client.get_items_by_group(gid)
                for it in data.get("items") or []:
                    rows.append(listing_row(it))
            except httpx.HTTPError as exc:
                logger.warning("[ebay] group %s failed: %s", gid, exc)

        # Theme filter applied only when (country, year) has multiple commemos.
        if ambiguous:
            rows = [r for r in rows if title_matches_theme(r.get("title") or "", ebay_q.theme_tokens)]

        return rows

    def _yield_listing_images(self, *, row: dict, coin) -> Iterable[DiscoveredItem]:
        """Fetch HD images via ``item/{id}`` and yield 1 item per image.

        En mode ``dry_run`` on saute le call ``item/{id}`` pour ne pas
        consommer de quota inutilement (preview cheap) — on yield seulement
        les images du summary (basse-déf).
        """
        item_id = row["item_id"]
        title = row["title"]
        lot_flag = is_lot_suspected(title)

        # D-22 — call item/{id} to get full additionalImages list at HD.
        urls: list[str] = []
        detail: dict | None = None
        if self.dry_run:
            logger.debug("[ebay] dry_run: skip item/{id} for %s", item_id)
        else:
            try:
                detail = self.client.get_item(item_id, fieldgroups="PRODUCT")
            except httpx.HTTPError as exc:
                logger.warning("[ebay] item/{id} failed for %s, falling back to summary: %s", item_id, exc)
                detail = None

        if detail:
            primary = (detail.get("image") or {}).get("imageUrl")
            if primary:
                urls.append(primary)
            for img in detail.get("additionalImages") or []:
                u = img.get("imageUrl")
                if u and u not in urls:
                    urls.append(u)
            condition_raw = detail.get("condition") or row["aspects"].get("État")
            seller = (detail.get("seller") or {}).get("username") or row.get("seller")
        else:
            # Fallback : utilise les URLs du summary si item/{id} a échoué.
            if row.get("image_url"):
                urls.append(row["image_url"])
            for u in row.get("additional_image_urls") or []:
                if u not in urls:
                    urls.append(u)
            condition_raw = row["aspects"].get("État")
            seller = row.get("seller")

        if not urls:
            logger.warning("[ebay] item %s has no images, skip", item_id)
            return

        for idx, url in enumerate(urls):
            yield DiscoveredItem(
                source_ref=f"ebay_{item_id}_img{idx}",
                source_url=row.get("item_web_url"),
                target_eurio_id=coin.eurio_id,
                listing_title=title,
                listing_country=coin.country,
                listing_year=coin.year,
                listing_price=row.get("price"),
                listing_currency=row.get("currency") or "EUR",
                condition_raw=condition_raw,
                seller_id=seller,
                is_lot_suspected=lot_flag,
                raw_payload={
                    "ebay_item_id": item_id,
                    "image_index": idx,
                    "image_url": url,
                    "sold": row.get("sold"),
                    "seller_fb_pct": row.get("seller_fb_pct"),
                    "seller_fb_score": row.get("seller_fb_score"),
                    "origin_date": row.get("origin_date"),
                    "aspects": row.get("aspects"),
                },
            )


def _try_image_dims(data: bytes) -> tuple[int | None, int | None]:
    """Best-effort PIL probe to extract (width, height). None on failure."""
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(data)) as img:
            return img.size
    except Exception as exc:  # noqa: BLE001 — PIL throws a zoo of exceptions
        logger.debug("PIL dims probe failed: %s", exc)
        return (None, None)
