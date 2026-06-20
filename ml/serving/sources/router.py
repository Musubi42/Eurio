"""Routes HTTP du domaine `sources` — thin layer (validation, auth, errors).

Pas de SQL ni de business logic ici — tout délègue à
``repository.py`` / ``service.py``.

URLs (Phase 2b data-layer-unification) :
- ``/sources``                                 — liste registry
- ``/sources/status``                          — dashboard SourcesPage
- ``/sources/healthcheck``                     — smoke
- ``/sources/{id}``                            — header detail
- ``/sources/{id}/runs``                       — liste runs d'une source
- ``/source-runs/{run_id}``                    — snapshot (poll target)
- ``/source-runs/{run_id}/funnel``             — vue entonnoir
- ``/source-runs/{run_id}/breakdown``          — par eurio_id
- ``/source-runs/{run_id}/listings``           — listings raws + crops
- ``/source-runs/{run_id}/searches``           — discovery_searches
- ``/source-runs/{run_id}/discarded``          — discarded_listings
- ``/source-runs/{run_id}/log``                — tail log (FS, dégradé sur VPS)
- ``/sources/ebay/quota-status``               — agrégat api_call_log
- ``/sources/ebay/marketplace-map``            — routage uniforme {DE, ES}
- ``/sources/ebay/filter-config``              — règles filtrage (constantes)
- ``/sources/ebay/freshness-groups``           — freshness queue groupée

Cf. ARCHITECTURE.md §2.4.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection

from . import repository, service
from .models import (
    EbayFilterConfig,
    EbayFreshnessGroupsResponse,
    EbayQuotaStatus,
    FilterRule,
    MarketplaceMapEntry,
    MarketplaceMapResponse,
    RunBreakdown,
    RunDiscarded,
    RunFunnel,
    RunListings,
    RunLogResponse,
    RunSearches,
    RunSnapshot,
    SourceDetailHeader,
    SourceRunListItem,
    SourcesStatusResponse,
)

router = APIRouter(tags=["sources"])

_require_read = require_scope("sources:read")

# Type alias DI (raccourcit la signature).
ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
PrincipalDep = Annotated[Principal, Depends(_require_read)]


# ─── Smoke ──────────────────────────────────────────────────────────────────


@router.get("/sources/healthcheck")
def healthcheck(principal: PrincipalDep) -> dict:
    return {"ok": True, "domain": "sources", "user": principal.email}


# ─── Sources list / status / detail ─────────────────────────────────────────


@router.get("/sources")
def list_sources(principal: PrincipalDep, conn: ConnDep) -> list[dict[str, Any]]:
    """Liste brute de `source_registry` (11 rows). Sert l'admin référentiel."""
    return repository.list_source_registry(conn)


@router.get("/sources/status", response_model=SourcesStatusResponse)
def sources_status(principal: PrincipalDep, conn: ConnDep) -> SourcesStatusResponse:
    """Dashboard SourcesPage. Cf. DECISIONS.md §D-09 pour les deviations."""
    return service.build_status(conn)


@router.get("/sources/ebay/quota-status", response_model=EbayQuotaStatus)
def ebay_quota_status(principal: PrincipalDep, conn: ConnDep) -> EbayQuotaStatus:
    return EbayQuotaStatus(**repository.ebay_quota_status(conn))


@router.get("/sources/ebay/marketplace-map", response_model=MarketplaceMapResponse)
def ebay_marketplace_map(principal: PrincipalDep) -> MarketplaceMapResponse:
    """Routage uniforme depuis ``ml/sources/ebay/marketplaces.py`` (DE, ES).

    Le module ML n'est pas livré dans l'image lean — la paire est figée
    côté front (cf. composable `useMarketplaceMap.ts` FALLBACK) et stable
    depuis le benchmark routing (2026-05-21). On la renvoie en dur.
    """
    return MarketplaceMapResponse(
        marketplaces=[
            MarketplaceMapEntry(marketplace="EBAY_DE", query_lang="de"),
            MarketplaceMapEntry(marketplace="EBAY_ES", query_lang="es"),
        ]
    )


@router.get("/sources/ebay/filter-config", response_model=EbayFilterConfig)
def ebay_filter_config(principal: PrincipalDep) -> EbayFilterConfig:
    """Snapshot des règles ``ml/sources/ebay/filters.py``.

    Patterns/seuils reproduits ici car le module ML n'est pas livré dans
    l'image lean. À synchroniser si filters.py évolue (rare — patterns
    figés depuis chunk C1b 2026-05-22).
    """
    return EbayFilterConfig(
        rules=[
            FilterRule(
                name="noise_title", kind="reject",
                description="Reject si le titre matche un mot-clé hors-scope (argent, or, plaqué, fauté).",
                pattern=r"\b(argent|or\b|silver|gold|plaqu[eé]|erreur\s*de\s*frappe|faut[eé]e?)\b",
                threshold=None, policy=None,
            ),
            FilterRule(
                name="below_face", kind="reject",
                description="Reject si prix < face × 0.8 (= 1.60 € pour les 2 €).",
                pattern=None, threshold=0.8, policy=None,
            ),
            FilterRule(
                name="above_extreme", kind="reject",
                description="Reject si prix > face × 500 (= 1000 € pour les 2 €).",
                pattern=None, threshold=500.0, policy=None,
            ),
            FilterRule(
                name="non_eur", kind="reject",
                description="Reject si currency != EUR.",
                pattern=None, threshold=None, policy=None,
            ),
            FilterRule(
                name="year_mismatch", kind="reject",
                description="Reject si une année trouvée dans le titre ≠ année attendue (commémos uniquement).",
                pattern=r"\b(19|20)\d{2}\b",
                threshold=None, policy="accept-on-missing",
            ),
            FilterRule(
                name="theme_mismatch", kind="reject",
                description=("Découverte groupée : chaque listing est attribué à une commémo "
                             "de son groupe via le matcher de thème multilingue. Reject si "
                             "le titre ne matche AUCUNE commémo du groupe."),
                pattern=None, threshold=None, policy=None,
            ),
            FilterRule(
                name="text_contradict_*", kind="reject",
                description=("Filtre dur du step text_signal : reject si le titre contredit "
                             "franchement la pièce attendue sur un axe (pays / année / dénom)."),
                pattern=None, threshold=None, policy=None,
            ),
            FilterRule(
                name="is_lot_suspected", kind="flag",
                description=("Flag (pas reject) : titre matche lot|coffret|série|rouleau|set. "
                             "Le listing est routé vers review_queue.kind='lot'."),
                pattern=r"\b(lot|coffret|s[eé]rie\b|collection\s*compl[eè]te|rouleau|roll\b|set\s+of\b|set\b)\b",
                threshold=None, policy=None,
            ),
        ],
        source_path="ml/sources/ebay/filters.py",
    )


@router.get("/sources/ebay/freshness-groups", response_model=EbayFreshnessGroupsResponse)
def ebay_freshness_groups(
    principal: PrincipalDep,
    conn: ConnDep,
    limit: int = Query(default=200, ge=1, le=2000),
) -> EbayFreshnessGroupsResponse:
    items, buckets = repository.ebay_freshness_groups(conn, limit)
    return EbayFreshnessGroupsResponse(items=items, buckets=buckets)


@router.get("/sources/{source_id}", response_model=SourceDetailHeader)
def source_detail(
    source_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
) -> SourceDetailHeader:
    try:
        return service.get_source_detail(conn, source_id)
    except repository.SourceNotFound as exc:
        raise HTTPException(status_code=404, detail=f"source '{source_id}' inconnue") from exc


@router.get("/sources/{source_id}/runs", response_model=list[SourceRunListItem])
def list_runs_for_source(
    source_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = Query(default=None),
) -> list[SourceRunListItem]:
    return repository.list_runs_for_source(
        conn, source_id=source_id, limit=limit, status=status,
    )


# ─── Run-level endpoints (run_id globalement unique → pas de scope source) ──


@router.get("/source-runs/{run_id}", response_model=RunSnapshot)
def get_run(run_id: str, principal: PrincipalDep, conn: ConnDep) -> RunSnapshot:
    try:
        return repository.get_run(conn, run_id)
    except repository.SourceRunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' introuvable") from exc


@router.get("/source-runs/{run_id}/funnel", response_model=RunFunnel)
def get_run_funnel(run_id: str, principal: PrincipalDep, conn: ConnDep) -> RunFunnel:
    try:
        return repository.get_run_funnel(conn, run_id)
    except repository.SourceRunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' introuvable") from exc


@router.get("/source-runs/{run_id}/breakdown", response_model=RunBreakdown)
def get_run_breakdown(
    run_id: str, principal: PrincipalDep, conn: ConnDep,
) -> RunBreakdown:
    try:
        return repository.get_run_breakdown(conn, run_id)
    except repository.SourceRunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' introuvable") from exc


@router.get("/source-runs/{run_id}/listings", response_model=RunListings)
def get_run_listings(
    run_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
    eurio_id: str | None = Query(default=None),
) -> RunListings:
    try:
        return repository.get_run_listings(conn, run_id=run_id, eurio_id=eurio_id)
    except repository.SourceRunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' introuvable") from exc


@router.get("/source-runs/{run_id}/searches", response_model=RunSearches)
def get_run_searches(
    run_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
    eurio_id: str | None = Query(default=None),
) -> RunSearches:
    try:
        return repository.get_run_searches(conn, run_id=run_id, eurio_id=eurio_id)
    except repository.SourceRunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' introuvable") from exc


@router.get("/source-runs/{run_id}/discarded", response_model=RunDiscarded)
def get_run_discarded(
    run_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
    eurio_id: str | None = Query(default=None),
    reason: str | None = Query(default=None),
) -> RunDiscarded:
    try:
        return repository.get_run_discarded(
            conn, run_id=run_id, eurio_id=eurio_id, reason=reason,
        )
    except repository.SourceRunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' introuvable") from exc


@router.get("/source-runs/{run_id}/log", response_model=RunLogResponse)
def get_run_log(
    run_id: str,
    principal: PrincipalDep,
    conn: ConnDep,
    tail: int = Query(default=500, ge=1, le=10_000),
) -> RunLogResponse:
    """Tail du fichier de log d'un run.

    Sur l'image lean VPS, le répertoire `ml/state/run_logs/` n'est pas
    livré → tous les logs sont "unavailable". Documenté D-09.
    """
    try:
        run_status, log_path = repository.get_run_log_meta(conn, run_id)
    except repository.SourceRunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' introuvable") from exc
    if not log_path:
        return RunLogResponse(run_id=run_id, log_path=None,
                              tail="(no log_path on this run)")
    from pathlib import Path
    candidate = Path("/srv/ml/state") / log_path
    if not candidate.is_file():
        return RunLogResponse(
            run_id=run_id, log_path=log_path,
            tail=f"(log file not shipped to VPS — status={run_status})",
        )
    lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    return RunLogResponse(
        run_id=run_id, log_path=log_path,
        tail="\n".join(lines[-tail:]),
    )
