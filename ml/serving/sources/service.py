"""Logique métier `sources` — orchestre les repository calls.

Pas d'HTTP ici, pas de SQL non plus. Manipule des objets domaine.

Phase 2b data-layer-unification : les endpoints `/sources/status` et
`/sources/{id}` reposent sur un **registry statique** (labels, cli_hints,
expected_cadence_days) — c'est la même métadonnée que l'aggregator legacy
(`sources_aggregator.SOURCES_REGISTRY`), mais sans les couches dynamiques
qui dépendaient du filesystem (`state/sources_runs.json`,
`state/price_snapshots/*.json`) ni des modules ML lourds
(`referential.numista_keys.KeyManager`, `shared.api_quota.QuotaTracker`).

Trade-offs documentés dans DECISIONS.md §D-09 :
- quota live : non porté (front a fallback)
- delta prix : non porté (front a fallback)
- coverage live : non porté (front a fallback)

Le shape JSON reste identique pour préserver la compat front. Les champs
absents prennent une valeur neutre (`null` ou 0).

Cf. ARCHITECTURE.md §2.3.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from .models import (
    CliHint,
    SourceCoverage,
    SourceDelta,
    SourceDetailHeader,
    SourceQuota,
    SourcesStatusResponse,
    SourceStatus,
    SourceTemporal,
    LastRunSummary,
)
from . import repository


# ─── Registry statique (cf. doc DECISIONS.md §D-09) ────────────────────────

_NUMISTA_MONTHLY_LIMIT = 1800
_EBAY_DAILY_LIMIT = 5000

SOURCES_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "numista_match", "label": "Numista — Match",
        "subtitle": "API · détection nouvelles pièces", "kind": "api",
        "quota_group": "numista", "expected_cadence_days": 14,
        "coverage_unit": "pièces matchées",
        "cli_hints": [
            {"kind": "run", "title": "Run complet",
             "command": "go-task ml:batch-match",
             "description": "Match toutes les nouvelles pièces du référentiel sans numista_id",
             "expected_outcome": "Met à jour cross_refs.numista_id sur les coins matchés"},
            {"kind": "dry-run", "title": "Aperçu candidats",
             "command": "go-task ml:batch-match-dry",
             "description": "Affiche les candidats proposés sans rien écrire",
             "expected_outcome": "Liste eurio_id → numista_id proposés en stdout"},
        ],
    },
    {
        "id": "numista_enrich", "label": "Numista — Enrichissement",
        "subtitle": "API · métadonnées canoniques", "kind": "api",
        "quota_group": "numista", "expected_cadence_days": 30,
        "coverage_unit": "pièces enrichies",
        "cli_hints": [
            {"kind": "run", "title": "Run complet",
             "command": "go-task ml:enrich-numista",
             "description": "Enrichit les pièces avec numista_id mais sans métadonnées",
             "expected_outcome": "Ajoute theme/designer/atelier dans coins, ~1 call par pièce"},
        ],
    },
    {
        "id": "numista_images", "label": "Numista — Images",
        "subtitle": "API · obverse/reverse", "kind": "api",
        "quota_group": "numista", "expected_cadence_days": 30,
        "coverage_unit": "pièces avec images",
        "cli_hints": [
            {"kind": "run", "title": "Run complet",
             "command": "go-task ml:batch-images",
             "description": "Télécharge obverse + reverse pour les pièces sans images",
             "expected_outcome": "Met à jour coins.images"},
        ],
    },
    {
        "id": "ebay", "label": "eBay Browse",
        "subtitle": "API · prix marché actif", "kind": "api",
        "quota_group": None, "expected_cadence_days": 30,
        "coverage_unit": "commémos enrichies",
        "cli_hints": [
            {"kind": "run", "title": "Run complet",
             "command": "go-task ml:scrape-ebay",
             "description": "Enrichit toutes les commémos ciblées (~500 calls)",
             "expected_outcome": "INSERT dans coin_market_quotes"},
        ],
    },
    {
        "id": "lmdlp", "label": "La Monnaie de la Pièce",
        "subtitle": "API WooCommerce · prix boutique FR", "kind": "scrape",
        "quota_group": None, "expected_cadence_days": 90,
        "coverage_unit": "cotations parsées",
        "cli_hints": [
            {"kind": "run", "title": "Scrape complet",
             "command": "go-task ml:scrape-lmdlp",
             "description": "Re-scrape l'intégralité du catalogue LMDLP",
             "expected_outcome": "Écrit ml/datasets/sources/lmdlp_<date>.json"},
        ],
    },
    {
        "id": "mdp", "label": "Monnaie de Paris",
        "subtitle": "Scrape HTML · catalogue officiel FR", "kind": "scrape",
        "quota_group": None, "expected_cadence_days": 90,
        "coverage_unit": "fiches parsées",
        "cli_hints": [
            {"kind": "run", "title": "Scrape complet",
             "command": "go-task ml:scrape-mdp",
             "description": "Re-scrape le catalogue Monnaie de Paris",
             "expected_outcome": "Écrit ml/datasets/sources/mdp_<date>.json"},
        ],
    },
    {
        "id": "bce", "label": "BCE",
        "subtitle": "Scrape HTML · images canoniques officielles", "kind": "scrape",
        "quota_group": None, "expected_cadence_days": 90,
        "coverage_unit": "pièces avec image BCE",
        "cli_hints": [
            {"kind": "run", "title": "Scrape toutes années",
             "command": "go-task ml:scrape-bce",
             "description": "Re-scrape les pages commémo BCE de 2004 à l'année courante",
             "expected_outcome": "Écrit ml/datasets/sources/bce_comm_<year>_<date>.html"},
        ],
    },
    {
        "id": "wikipedia", "label": "Wikipedia",
        "subtitle": "Scrape HTML · backfill métadonnées par pays", "kind": "scrape",
        "quota_group": None, "expected_cadence_days": 365,
        "coverage_unit": "pays", "is_future": True,
        "future_note": "Source planifiée — pas encore de scraper. À écrire : "
                       "ml/referential/scrape_wikipedia.py.",
        "cli_hints": [],
    },
]


def _last_run_per_source(
    conn: sqlite3.Connection, source_id: str,
) -> tuple[str | None, str | None]:
    """(last_run_at, last_run_kind) du dernier run terminé pour `source_id`."""
    row = conn.execute(
        """
        SELECT started_at, kind FROM source_runs
         WHERE source = ? AND status != 'running'
         ORDER BY started_at DESC LIMIT 1
        """,
        (source_id,),
    ).fetchone()
    if row is None:
        return None, None
    return row["started_at"], row["kind"]


def _days_since(started_at: str | None) -> int | None:
    if not started_at:
        return None
    try:
        dt = datetime.fromisoformat(started_at.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).days


def _build_source_status(
    conn: sqlite3.Connection, spec: dict[str, Any],
) -> SourceStatus:
    src_id = spec["id"]
    last_run_at, last_run_kind = _last_run_per_source(conn, src_id)
    days = _days_since(last_run_at)
    cadence = spec["expected_cadence_days"]
    is_future = bool(spec.get("is_future"))
    overdue = (not is_future) and (days is not None) and days > cadence

    health = "healthy"
    health_reason: str | None = None
    if overdue:
        health = "warning"
        health_reason = f"Overdue : {days}j depuis le dernier run (cadence {cadence}j)"
    elif not is_future and last_run_at is None:
        health = "warning"
        health_reason = "Aucun run terminé"

    return SourceStatus(
        id=src_id, label=spec["label"], subtitle=spec["subtitle"],
        kind=spec["kind"], quota_group=spec.get("quota_group"),
        health=health, health_reason=health_reason,
        quota=None,  # cf. D-09 — pas porté en Phase 2b
        temporal=SourceTemporal(
            last_run_at=last_run_at,
            last_run_kind=last_run_kind,
            days_since_last_run=days,
            expected_cadence_days=cadence,
            overdue=overdue,
            delta=None,  # cf. D-09 — pas porté en Phase 2b
        ),
        coverage=SourceCoverage(
            enriched=0, total_target=0, pct=0.0,
            unit=spec["coverage_unit"],
        ),
        cli_hints=[CliHint(**h) for h in spec.get("cli_hints", [])],
        is_future=is_future or None,
        future_note=spec.get("future_note"),
    )


def build_status(conn: sqlite3.Connection) -> SourcesStatusResponse:
    sources = [_build_source_status(conn, spec) for spec in SOURCES_REGISTRY]
    # quota_groups : Numista non porté (pas de KeyManager dans image lean).
    # Le front a un fallback mock — on renvoie un dict vide pour rester valide.
    return SourcesStatusResponse(sources=sources, quota_groups={})


def get_source_detail(
    conn: sqlite3.Connection, source_id: str,
) -> SourceDetailHeader:
    spec = next((s for s in SOURCES_REGISTRY if s["id"] == source_id), None)
    if spec is None:
        # Fallback minimal pour les sources connues uniquement de source_runs
        # (ex: `jo`). Permet à fetchSourceDetail de ne pas crasher.
        runs_exist = conn.execute(
            "SELECT 1 FROM source_runs WHERE source = ? LIMIT 1", (source_id,),
        ).fetchone()
        if runs_exist is None:
            raise repository.SourceNotFound(source_id)
        spec = {
            "id": source_id, "label": source_id,
            "subtitle": f"Source `{source_id}` — métadonnées non enregistrées",
            "kind": "scrape", "quota_group": None,
            "expected_cadence_days": 0, "coverage_unit": "items",
            "cli_hints": [],
        }

    status = _build_source_status(conn, spec)
    last = repository.last_completed_run(conn, source_id)
    last_summary: LastRunSummary | None = None
    if last:
        duration = 0
        if last["started_at"] and last["ended_at"]:
            try:
                t0 = datetime.fromisoformat(last["started_at"].replace(" ", "T"))
                t1 = datetime.fromisoformat(last["ended_at"].replace(" ", "T"))
                duration = int((t1 - t0).total_seconds())
            except ValueError:
                duration = 0
        last_summary = LastRunSummary(
            n_images=(last["n_raws_added"] or 0) + (last["n_crops_added"] or 0),
            n_quotes=last["n_quotes_added"] or 0,
            n_calls=last["n_calls"] or 0,
            duration_s=duration,
            status=last["status"],
        )
    cov = status.coverage
    label = (
        f"{cov.enriched:,} / {cov.total_target:,} {cov.unit}"
    ).replace(",", " ")
    return SourceDetailHeader(
        id=status.id, label=status.label, subtitle=status.subtitle,
        health=status.health, health_reason=status.health_reason,
        expected_cadence_days=status.temporal.expected_cadence_days,
        last_run_at=status.temporal.last_run_at,
        last_run_summary=last_summary,
        coverage_pct=cov.pct,
        coverage_label=label,
    )
