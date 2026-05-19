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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import httpx

from market.ebay_client import EbayClient
from sources._base.adapter import (
    DiscardedListingRecord,
    DiscoveredItem,
    RawDownloadResult,
    RecordDiscardedFn,
    RecordSearchFn,
    SourceQuery,
)
from sources._base.dedup import DiscoverySearchRecord
from sources.ebay.filters import (
    accept_listing,
    is_lot_suspected,
    listing_row,
)
from sources.ebay.marketplaces import MarketplaceRoute, route_for
from sources.ebay.queries import (
    EbayQuery,
    build_query,
    load_coin,
    title_matches_theme,
)

# Factory invoked by the adapter to materialize a client for a given
# marketplace. Callers wire it as e.g.
# `lambda mkt: EbayClient(token, marketplace=mkt, tracker=shared_tracker)`
# so the multiple per-mkt clients share the same daily quota counter.
MakeClientFn = Callable[[str], EbayClient]

logger = logging.getLogger(__name__)

# Cap on item-group expansion per search (multi-year variation pages
# inflate quota cost — top-K is enough to surface the cheapest variants).
DEFAULT_GROUP_EXPAND_TOP_K = 2
DEFAULT_SEARCH_LIMIT = 50              # D-23 — no pagination V1
DEFAULT_DOWNLOAD_TIMEOUT_SEC = 30


@dataclass
class SearchExpandResult:
    """Funnel ventilé du `_search_and_expand` (chunk 0 auto-validation).

    - ``rows``           : liste finale, post theme-token drop, prête pour
                           `accept_listing`.
    - ``n_summaries``    : N0 — `itemSummaries` retournés brut par Browse.
    - ``n_after_groups`` : N1 — N0 + lignes ajoutées par expansion
                           `getItemsByGroup` (top-K limité).
    - ``theme_dropped``  : rows écartées par le filtre theme-tokens (vide
                           si non ambigu). Persistées en discarded_listings
                           avec reason='theme_mismatch' par discover().
    """

    rows: list[dict]
    n_summaries: int
    n_after_groups: int
    theme_dropped: list[dict]


@dataclass
class _MergedItem:
    """Listing dé-dupliqué cross-marketplace pour 1 eurio_id (B4).

    `first_mkt` = mkt qui a vu l'item en premier (ordre primary→global).
    `found` = set des mkts où l'item est apparu (= base du JSON persisté).
    `client` = EbayClient associé à `first_mkt` (utilisé pour le call
    item/{id} HD ; les détails images sont stables cross-mkt, donc tirer
    via le premier client est OK et plus simple).
    """

    first_mkt: str
    found: set[str]
    row: dict
    client: EbayClient


@dataclass
class EbayAdapter:
    """Glue between EbayClient(s) and the orchestrator's SourceAdapter contract.

    Multi-marketplace (B4) : reçoit une **factory** ``make_client`` qui
    construit un EbayClient pour un marketplace donné. L'adapter
    instancie 1 à 2 clients par eurio_id selon ``route_for(country)``
    (primary + GB, ou GB seul), partage le quota tracker entre eux via
    la closure côté caller.

    Une instance == un run ; les clients vivent le temps du run.
    """

    make_client: MakeClientFn
    conn: sqlite3.Connection
    source_id: str = "ebay"
    search_limit: int = DEFAULT_SEARCH_LIMIT
    group_expand_top_k: int = DEFAULT_GROUP_EXPAND_TOP_K
    download_timeout: int = DEFAULT_DOWNLOAD_TIMEOUT_SEC
    # Dry-run mode (set by orchestrator via run_pipeline(..., dry_run=True)
    # propagated through CLI/API). Skip item/{id} HD expansion to keep the
    # preview cheap : 1 search call per eurio_id instead of ~10.
    dry_run: bool = False

    def __post_init__(self) -> None:
        # Cache des clients par mkt — évite de re-instancier (donc de
        # re-checker le token, de re-créer un httpx.Client) à chaque
        # eurio_id du batch. Réinitialisé par instance d'adapter.
        self._client_cache: dict[str, EbayClient] = {}

    def _client_for(self, marketplace: str) -> EbayClient:
        cli = self._client_cache.get(marketplace)
        if cli is None:
            cli = self.make_client(marketplace)
            self._client_cache[marketplace] = cli
        return cli

    # ── Discover ────────────────────────────────────────────────────────────

    def discover(
        self,
        query: SourceQuery,
        *,
        record_search: "RecordSearchFn | None" = None,
        record_discarded: "RecordDiscardedFn | None" = None,
    ) -> Iterable[DiscoveredItem]:
        """Yield 1 DiscoveredItem per image of each accepted listing.

        B4 — Multi-marketplace : appelle ``route_for(coin.country)`` pour
        décider du couple (primary, GB). Boucle sur les mkts (1 ou 2),
        agrège les rows par item_id en mémoire (1ʳᵉ occurrence wins pour
        ``marketplace``, set complet pour ``marketplace_found``), puis
        yield 1 DiscoveredItem par image de chaque listing accepté.
        """
        if not query.target_eurio_id:
            raise ValueError(
                "EbayAdapter.discover requires query.target_eurio_id set "
                "(orchestrator should unfold target_eurio_ids)."
            )

        coin = load_coin(self.conn, query.target_eurio_id)
        route = route_for(coin.country)
        ambiguous = self._is_ambiguous_country_year(coin.country, coin.year)

        # Ordre des marketplaces : primary natif d'abord, GB ensuite. Si
        # primary == None ou primary == GB, on ne fait qu'un appel (GB).
        marketplaces: list[tuple[str, str]] = []  # (mkt, query_lang)
        if route.primary is not None and route.primary != route.global_:
            marketplaces.append((route.primary, route.query_lang))
        marketplaces.append((route.global_, "en"))

        merged: dict[str, _MergedItem] = {}

        for mkt, lang in marketplaces:
            client = self._client_for(mkt)
            ebay_q = build_query(coin, query_lang=lang)
            filters_meta = {
                "marketplace": mkt,
                "query_lang": lang,
                "aspect_filter": ebay_q.aspect_filter,
                "theme_tokens": ebay_q.theme_tokens,
                "ambiguous": ambiguous,
                "search_limit": self.search_limit,
                "category_id": ebay_q.category_id,
            }
            logger.info(
                "[ebay] eurio=%s mkt=%s lang=%s q=%r ambiguous=%s",
                coin.eurio_id, mkt, lang, ebay_q.q, ambiguous,
            )

            t0 = time.monotonic()
            try:
                expand = self._search_and_expand(
                    client, ebay_q, ambiguous=ambiguous
                )
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((time.monotonic() - t0) * 1000)
                http_status: int | None = None
                if isinstance(exc, httpx.HTTPStatusError):
                    http_status = exc.response.status_code
                if record_search is not None:
                    record_search(DiscoverySearchRecord(
                        run_id="",
                        source="",
                        target_eurio_id=coin.eurio_id,
                        endpoint="ebay.browse.search",
                        query_q=ebay_q.q,
                        query_filters=filters_meta,
                        status="failed",
                        http_status=http_status,
                        duration_ms=duration_ms,
                        error=str(exc)[:500],
                        marketplace=mkt,
                    ))
                # Un mkt qui plante ne doit pas casser l'autre. On log et
                # on continue ; le run repart sur le mkt suivant ou yield
                # ce qu'on a déjà mergé.
                logger.warning(
                    "[ebay] mkt=%s search failed for %s: %s",
                    mkt, coin.eurio_id, exc,
                )
                continue

            # Persist theme-token drops (mkt-aware).
            if expand.theme_dropped and record_discarded is not None:
                for row in expand.theme_dropped:
                    if not row.get("item_id"):
                        continue
                    record_discarded(DiscardedListingRecord(
                        source_ref=f"ebay_listing_{row['item_id']}",
                        target_eurio_id=coin.eurio_id,
                        reason="theme_mismatch",
                        title=row.get("title"),
                        raw_payload={
                            "item_id": row.get("item_id"),
                            "price": row.get("price"),
                            "currency": row.get("currency"),
                            "item_web_url": row.get("item_web_url"),
                            "theme_tokens": ebay_q.theme_tokens,
                        },
                        marketplace=mkt,
                    ))

            # accept_listing per mkt — les reject reasons sont attribuées
            # au mkt qui a yieldé le listing rejeté.
            kept: list[dict] = []
            for row in expand.rows:
                ok, reason = accept_listing(
                    row,
                    coin.face_value,
                    expected_year=coin.year,
                    is_commemorative=coin.is_commemorative,
                )
                if not ok:
                    if record_discarded is not None and row.get("item_id"):
                        record_discarded(DiscardedListingRecord(
                            source_ref=f"ebay_listing_{row['item_id']}",
                            target_eurio_id=coin.eurio_id,
                            reason=reason,
                            title=row.get("title"),
                            raw_payload={
                                "item_id": row.get("item_id"),
                                "price": row.get("price"),
                                "currency": row.get("currency"),
                                "item_web_url": row.get("item_web_url"),
                            },
                            marketplace=mkt,
                        ))
                    continue
                kept.append(row)

            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "[ebay] eurio=%s mkt=%s funnel summaries=%d → groups=%d → theme=%d → kept=%d",
                coin.eurio_id, mkt,
                expand.n_summaries, expand.n_after_groups,
                len(expand.rows), len(kept),
            )

            if record_search is not None:
                record_search(DiscoverySearchRecord(
                    run_id="",
                    source="",
                    target_eurio_id=coin.eurio_id,
                    endpoint="ebay.browse.search",
                    query_q=ebay_q.q,
                    query_filters=filters_meta,
                    status="success" if expand.rows else "empty",
                    http_status=200,
                    n_summaries=expand.n_summaries,
                    n_after_groups=expand.n_after_groups,
                    n_raw_results=len(expand.rows),
                    n_kept_results=len(kept),
                    duration_ms=duration_ms,
                    marketplace=mkt,
                ))

            # Merge en mémoire : 1ʳᵉ occurrence d'un item_id fixe
            # `first_mkt` (l'ordre primary→GB de la boucle garantit
            # cette sémantique). Les suivantes étendent le set `found`.
            for row in kept:
                iid = row.get("item_id")
                if not iid:
                    continue
                if iid in merged:
                    merged[iid].found.add(mkt)
                else:
                    merged[iid] = _MergedItem(
                        first_mkt=mkt, found={mkt}, row=row, client=client,
                    )

        # D-22 — fetch HD images via item/{id} sur le client du first_mkt,
        # puis yield 1 DiscoveredItem par image avec marketplace +
        # marketplace_found renseignés.
        for iid, item in merged.items():
            yield from self._yield_listing_images(
                row=item.row,
                coin=coin,
                marketplace=item.first_mkt,
                marketplace_found=tuple(sorted(item.found)),
                client=item.client,
            )

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
            http_status = resp.status_code
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
            endpoint_url=url,
            http_status=http_status,
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

    def _search_and_expand(
        self, client: EbayClient, ebay_q: EbayQuery, *, ambiguous: bool,
    ) -> "SearchExpandResult":
        """Search + group expansion + theme drop, avec ventilation N0/N1/N2.

        Retourne un :class:`SearchExpandResult` qui porte la liste finale
        (post-theme drop) ET les compteurs intermédiaires + les rows
        explicitement filtrées par theme drop, pour audit.
        """
        # Note (bloc 1, 2026-05-05) : on a drop le `filter_expr` qui contenait
        # `price:[1..500],priceCurrency:EUR`. Le filtre eBay sur `priceCurrency`
        # crashait le recall (49→0 mesuré sur bearded-vulture en probe S3).
        # Les contraintes prix/devise vivent désormais en post-filter
        # applicatif côté `accept_listing` (filters.py).
        search = client.search(
            ebay_q.q,
            category_ids=ebay_q.category_id,
            aspect_filter=ebay_q.aspect_filter,
            limit=self.search_limit,
        )
        summaries = search.get("itemSummaries") or []
        n_summaries = len(summaries)

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
                data = client.get_items_by_group(gid)
                for it in data.get("items") or []:
                    rows.append(listing_row(it))
            except httpx.HTTPError as exc:
                logger.warning("[ebay] group %s failed: %s", gid, exc)

        n_after_groups = len(rows)

        # Theme filter applied only when (country, year) has multiple commemos.
        theme_dropped: list[dict] = []
        if ambiguous:
            kept_rows: list[dict] = []
            for r in rows:
                if title_matches_theme(r.get("title") or "", ebay_q.theme_tokens):
                    kept_rows.append(r)
                else:
                    theme_dropped.append(r)
            rows = kept_rows

        return SearchExpandResult(
            rows=rows,
            n_summaries=n_summaries,
            n_after_groups=n_after_groups,
            theme_dropped=theme_dropped,
        )

    def _yield_listing_images(
        self,
        *,
        row: dict,
        coin,
        marketplace: str,
        marketplace_found: tuple[str, ...],
        client: EbayClient,
    ) -> Iterable[DiscoveredItem]:
        """Fetch HD images via ``item/{id}`` and yield 1 item per image.

        En mode ``dry_run`` on saute le call ``item/{id}`` pour ne pas
        consommer de quota inutilement (preview cheap) — on yield seulement
        les images du summary (basse-déf). Le ``client`` reçu est celui
        du first_mkt (B4 : un item_id étant stable cross-mkt, peu importe
        quel mkt sert le item/{id} ; on prend le first par convention).
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
                detail = client.get_item(item_id, fieldgroups="PRODUCT")
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
                marketplace=marketplace,
                marketplace_found=marketplace_found,
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
