"""eBay adapter for the ingestion orchestrator.

Implements ``SourceAdapter`` (sources/_base/adapter.py). Two methods :

* ``discover(query)`` — receives a SourceQuery scoped to **a single
  discovery group** ``(dénomination, pays, année)`` — the orchestrator
  unfolds group batches at the Discover step. Runs one Browse API search
  per marketplace, optionally expands item groups (multi-year
  variations), attributes each listing to a coin of the group via the
  multilingual theme matcher, fetches per-listing HD images via
  ``item/{id}`` (D-22), and yields one ``DiscoveredItem`` per *image* of
  each accepted listing. ``source_ref`` follows the pattern
  ``ebay_<itemId>_img<N>`` to keep the "1 source_image = 1 file"
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

from sources.market.ebay_client import EbayClient
from sources._base.adapter import (
    DiscardedListingRecord,
    DiscoveredItem,
    DiscoveryGroup,
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
from sources.ebay.marketplaces import discovery_marketplaces
from sources.ebay.queries import (
    EbayQuery,
    build_group_query,
    load_coin,
    load_group_coins,
    match_listing_to_group,
    search_limit_for_group,
)
from sources.ebay.standards import (
    COMMEMO_IN_STANDARD_PREFIX,
    attribute_standard_listing,
    load_standard_eras,
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
    """Funnel ventilé du `_search_and_expand`.

    - ``rows``           : listings bruts (post-expansion groupes), prêts
                           pour `accept_listing` + `match_listing_to_group`.
    - ``n_summaries``    : N0 — `itemSummaries` retournés brut par Browse.
    - ``n_after_groups`` : N1 — N0 + lignes ajoutées par expansion
                           `getItemsByGroup` (top-K limité).
    - ``browse_url``     : URL d'appel Browse exacte de la search (F3).
    """

    rows: list[dict]
    n_summaries: int
    n_after_groups: int
    browse_url: str | None = None


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
    instancie 1 client par marketplace de ``DISCOVERY_MARKETPLACES``
    (EBAY_DE + EBAY_ES, routage uniforme), partage le quota tracker
    entre eux via la closure côté caller.

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

        Découverte par **groupe** ``(dénomination, pays, année)`` : une
        seule recherche eBay par marketplace couvre toutes les commémos-
        sœurs du groupe. Chaque listing retourné est attribué à une pièce
        du groupe par ``match_listing_to_group``. ``target_eurio_id`` de
        chaque ``DiscoveredItem`` porte donc la pièce *résolue* par le
        theme-match — pas la pièce cherchée (il n'y a plus de pièce
        cherchée, juste un groupe). ``None`` pour les listings ambigus.

        Multi-marketplace : interroge ``DISCOVERY_MARKETPLACES`` (EBAY_DE
        puis EBAY_ES, routage uniforme). Les rows sont agrégées par item_id
        en mémoire (1ʳᵉ occurrence wins pour ``marketplace``, set complet
        pour ``marketplace_found``).
        """
        group = self._resolve_group(query)
        is_standard = group.kind == "standard"

        # Périmètre du groupe : commémos-sœurs (theme-match) vs ères de design
        # standard (appartenance de plage). `coin_ids` n'est consommé que par
        # le chemin commémo ; le chemin standard attribue par millésime.
        coin_ids: list[str] = []
        if is_standard:
            eras = load_standard_eras(
                self.conn, group.denomination, group.country,
            )
            if not eras:
                raise ValueError(
                    f"No standard era for group {group} — nothing to discover."
                )
            n_in_group = len(eras)
        else:
            coins = load_group_coins(
                self.conn, group.denomination, group.country, group.year,
            )
            if not coins:
                raise ValueError(
                    f"No commemorative coin for group {group} — nothing to discover."
                )
            coin_ids = [c.eurio_id for c in coins]
            n_in_group = len(coins)
        limit = search_limit_for_group(n_in_group, standard=is_standard)

        # Routage uniforme : EBAY_DE puis EBAY_ES, chacun queryé dans sa
        # langue native (cf. marketplaces.py — décision benchmark).
        marketplaces: list[tuple[str, str]] = [
            (c.marketplace, c.query_lang) for c in discovery_marketplaces()
        ]

        merged: dict[str, _MergedItem] = {}

        for mkt, lang in marketplaces:
            client = self._client_for(mkt)
            ebay_q = build_group_query(
                group.denomination, group.country, group.year, query_lang=lang,
            )
            filters_meta = {
                "marketplace": mkt,
                "query_lang": lang,
                "aspect_filter": ebay_q.aspect_filter,
                "group": {
                    "denomination": group.denomination,
                    "country": group.country,
                    "year": group.year,
                },
                "n_coins_in_group": n_in_group,
                "kind": group.kind,
                "search_limit": limit,
                "category_id": ebay_q.category_id,
            }
            logger.info(
                "[ebay] group=%s/%s/%s kind=%s mkt=%s lang=%s q=%r n_coins=%d limit=%d",
                group.denomination, group.country, group.year, group.kind,
                mkt, lang, ebay_q.q, n_in_group, limit,
            )

            t0 = time.monotonic()
            try:
                expand = self._search_and_expand(client, ebay_q, limit=limit)
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((time.monotonic() - t0) * 1000)
                http_status: int | None = None
                if isinstance(exc, httpx.HTTPStatusError):
                    http_status = exc.response.status_code
                if record_search is not None:
                    record_search(DiscoverySearchRecord(
                        run_id="",
                        source="",
                        target_eurio_id=None,
                        endpoint="ebay.browse.search",
                        query_q=ebay_q.q,
                        query_filters=filters_meta,
                        status="failed",
                        http_status=http_status,
                        duration_ms=duration_ms,
                        error=str(exc)[:500],
                        marketplace=mkt,
                        browse_url=client.last_request_url,
                    ))
                # Un mkt qui plante ne doit pas casser l'autre.
                logger.warning(
                    "[ebay] mkt=%s search failed for group %s/%s: %s",
                    mkt, group.country, group.year, exc,
                )
                continue

            # Par listing : accept_listing (anti-bruit) puis attribution à une
            # pièce du groupe — theme-match (commémo) ou appartenance de plage
            # d'années (standard).
            kept: list[dict] = []
            for row in expand.rows:
                ok, reason = accept_listing(
                    row,
                    group.denomination,
                    expected_year=group.year,            # None → pas de filtre année (standard)
                    is_commemorative=not is_standard,
                )
                if not ok:
                    self._record_discard(record_discarded, row, reason, mkt)
                    continue
                if is_standard:
                    if not self._attribute_standard_row(row, group):
                        discard_reason: str = row["_discard_reason"]
                        if discard_reason.startswith(COMMEMO_IN_STANDARD_PREFIX):
                            # Commémo détectée dans un run standard : on la sauve
                            # au lieu de la jeter. Elle part dans le flux normal
                            # (→ _yield_listing_images) avec l'eurio_id extrait,
                            # et on trace également dans discarded_listings (audit).
                            eurio_id: str = discard_reason.split(":", 1)[1]
                            row["_resolved_eurio_id"] = eurio_id
                            row["_group_verdict"] = "rescued"
                            kept.append(row)
                            self._record_discard(
                                record_discarded, row,
                                f"rescued_to:{eurio_id}", mkt,
                                target_eurio_id=eurio_id,
                            )
                        else:
                            # no_match / no_eras / group_contradict_* → discard.
                            self._record_discard(
                                record_discarded, row, discard_reason, mkt,
                            )
                        continue
                elif not self._attribute_commemo_row(row, coin_ids):
                    self._record_discard(
                        record_discarded, row, row["_discard_reason"], mkt,
                    )
                    continue
                kept.append(row)

            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "[ebay] group=%s/%s mkt=%s funnel summaries=%d → groups=%d → kept=%d",
                group.country, group.year, mkt,
                expand.n_summaries, expand.n_after_groups, len(kept),
            )

            if record_search is not None:
                record_search(DiscoverySearchRecord(
                    run_id="",
                    source="",
                    target_eurio_id=None,
                    endpoint="ebay.browse.search",
                    query_q=ebay_q.q,
                    query_filters=filters_meta,
                    status="success" if kept else "empty",
                    http_status=200,
                    n_summaries=expand.n_summaries,
                    n_after_groups=expand.n_after_groups,
                    n_raw_results=len(expand.rows),
                    n_kept_results=len(kept),
                    duration_ms=duration_ms,
                    marketplace=mkt,
                    browse_url=expand.browse_url,
                ))

            # Merge en mémoire : 1ʳᵉ occurrence d'un item_id fixe
            # `first_mkt` (ordre DE→ES de la boucle). Les suivantes
            # étendent le set `found`.
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
        # puis yield 1 DiscoveredItem par image.
        for iid, item in merged.items():
            yield from self._yield_listing_images(
                row=item.row,
                group=group,
                resolved_eurio_id=item.row.get("_resolved_eurio_id"),
                group_candidates=item.row.get("_group_candidates"),
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

    def _resolve_group(self, query: SourceQuery) -> DiscoveryGroup:
        """Détermine le groupe de découverte d'une SourceQuery.

        Accepte soit un ``discovery_group`` explicite, soit un
        ``target_eurio_id`` (résolu vers *son* groupe — pratique pour
        re-scrape une pièce précise / debug). Une SourceQuery sans
        l'un ni l'autre est une erreur de l'orchestrateur.
        """
        if query.discovery_group is not None:
            return query.discovery_group
        if query.target_eurio_id:
            coin = load_coin(self.conn, query.target_eurio_id)
            # Un standard se résout vers son groupe pays (année=None) ; une
            # commémo vers son groupe (denom, pays, année).
            if coin.is_commemorative:
                return DiscoveryGroup(
                    denomination=coin.face_value,
                    country=coin.country,
                    year=coin.year,
                )
            return DiscoveryGroup(
                denomination=coin.face_value,
                country=coin.country,
                year=None,
                kind="standard",
            )
        raise ValueError(
            "EbayAdapter.discover requires query.discovery_group "
            "(or a target_eurio_id to resolve into its group)."
        )

    def _record_discard(
        self,
        record_discarded: "RecordDiscardedFn | None",
        row: dict,
        reason: str,
        marketplace: str,
        *,
        target_eurio_id: str | None = None,
    ) -> None:
        """Persiste un rejet de listing (audit ``discarded_listings``).

        ``target_eurio_id`` est ``None`` pour les rejets ordinaires ; passé
        explicitement pour les rescues commémo (audit avec eurio_id résolu).
        """
        if record_discarded is None or not row.get("item_id"):
            return
        record_discarded(DiscardedListingRecord(
            source_ref=f"ebay_listing_{row['item_id']}",
            target_eurio_id=target_eurio_id,
            reason=reason,
            title=row.get("title"),
            raw_payload={
                "item_id": row.get("item_id"),
                "price": row.get("price"),
                "currency": row.get("currency"),
                "item_web_url": row.get("item_web_url"),
            },
            marketplace=marketplace,
        ))

    # ── Attribution par listing (commémo / standard) ─────────────────────────

    def _attribute_commemo_row(self, row: dict, coin_ids: list[str]) -> bool:
        """Attribue un listing à une commémo-sœur du groupe (theme-match).

        Retourne ``True`` si gardé (pose ``_resolved_eurio_id`` /
        ``_group_verdict`` / ``_group_candidates`` sur ``row``), ``False`` si
        à jeter (pose ``_discard_reason``). C1 — single / lot / ambiguous sont
        tous gardés ; seul ``no_match`` (contradiction franche pays/année/
        dénom) jette.
        """
        gm = match_listing_to_group(
            row.get("title") or "", coin_ids, conn=self.conn,
        )
        if gm.verdict == "no_match":
            axe = gm.contradictions[0] if gm.contradictions else "unknown"
            row["_discard_reason"] = f"group_contradict_{axe}"
            return False
        row["_resolved_eurio_id"] = gm.target_eurio_id
        row["_group_verdict"] = gm.verdict
        # Candidates review : 'ambiguous' → toutes les sœurs ; 'lot' → le
        # sous-ensemble matché ; 'single' → rien (target déjà résolu). Cf.
        # P10-E (fix multi-coin groups 2026-05-26).
        if gm.verdict == "ambiguous":
            row["_group_candidates"] = list(coin_ids)
        elif gm.verdict == "lot":
            row["_group_candidates"] = list(gm.matched)
        else:
            row["_group_candidates"] = None
        return True

    def _attribute_standard_row(self, row: dict, group: DiscoveryGroup) -> bool:
        """Attribue un listing à une ère standard du pays (appartenance de plage).

        Retourne ``True`` si gardé, ``False`` si à jeter (``commemo`` /
        ``no_match`` / ``no_eras`` — pose ``_discard_reason``). Doctrine
        standards « tout en review » : ``single`` et ``ambiguous`` sont gardés
        et partent en review ; ``target`` est un *prior* (None si ambiguous) et
        les ères du pays sont toujours portées en candidates pour que l'humain
        tranche / corrige.
        """
        sm = attribute_standard_listing(
            row.get("title") or "", group.denomination, group.country,
            conn=self.conn,
        )
        if sm.verdict in ("commemo", "no_match", "no_eras"):
            row["_discard_reason"] = sm.reason
            return False
        row["_resolved_eurio_id"] = sm.target_eurio_id
        row["_group_verdict"] = sm.verdict
        row["_group_candidates"] = list(sm.candidates)
        return True

    def _search_and_expand(
        self,
        client: EbayClient,
        ebay_q: EbayQuery,
        *,
        limit: int,
    ) -> "SearchExpandResult":
        """Search + expansion getItemsByGroup, avec ventilation N0/N1.

        Retourne les listings bruts (post-expansion) + les compteurs du
        funnel. L'attribution theme-match et accept_listing vivent en
        aval, dans ``discover()``.

        Note (bloc 1, 2026-05-05) : pas de `filter_expr` prix/devise — le
        filtre eBay sur `priceCurrency` crashait le recall (49→0 sur
        bearded-vulture en probe S3). Prix/devise vivent en post-filter
        applicatif côté `accept_listing`.
        """
        search = client.search(
            ebay_q.q,
            category_ids=ebay_q.category_id,
            aspect_filter=ebay_q.aspect_filter,
            limit=limit,
        )
        # URL de la search elle-même — capturée avant les appels
        # getItemsByGroup qui écraseraient `last_request_url`.
        browse_url = client.last_request_url
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

        return SearchExpandResult(
            rows=rows,
            n_summaries=n_summaries,
            n_after_groups=len(rows),
            browse_url=browse_url,
        )

    def _yield_listing_images(
        self,
        *,
        row: dict,
        group: DiscoveryGroup,
        resolved_eurio_id: str | None,
        group_candidates: list[str] | None,
        marketplace: str,
        marketplace_found: tuple[str, ...],
        client: EbayClient,
    ) -> Iterable[DiscoveredItem]:
        """Fetch HD images via ``item/{id}`` and yield 1 item per image.

        ``resolved_eurio_id`` est la pièce attribuée au listing par le
        theme-match (``None`` si verdict ambigu) — il devient le
        ``target_eurio_id`` de chaque ``DiscoveredItem``.

        En mode ``dry_run`` on saute le call ``item/{id}`` pour ne pas
        consommer de quota inutilement (preview cheap) — on yield seulement
        les images du summary (basse-déf). Le ``client`` reçu est celui
        du first_mkt (B4 : un item_id étant stable cross-mkt, peu importe
        quel mkt sert le item/{id} ; on prend le first par convention).
        """
        item_id = row["item_id"]
        title = row["title"]
        lot_flag = is_lot_suspected(title) or row.get("_group_verdict") == "lot"

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
                target_eurio_id=resolved_eurio_id,
                listing_title=title,
                listing_country=group.country,
                listing_year=group.year,
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
                    "group_candidates": group_candidates,
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
