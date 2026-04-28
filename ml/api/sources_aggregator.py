"""Build the response payload for `GET /sources/status`.

Contract: `admin/packages/web/src/features/sources/composables/useSourcesApi.ts`.

All data comes from local files / SQLite — the only external call is the
coverage count against Supabase, cached 60s in-memory to keep the egress
budget on the free tier under control. The endpoint is polled every 10s by
the admin frontend; without that cache we'd hit Supabase 6× per minute per
source.

Inputs by section
-----------------
- quota   → ml/api_quota.QuotaTracker (table api_call_log)
- temporal.last_run_at + last_run_kind  → ml/state/sources_runs.json
- temporal.delta (eBay)                  → ml/state/price_snapshots/ebay_*.json
- temporal.delta (other)                 → sources_runs.last_run_added_coins
- coverage                               → Supabase /coins (cached 60s)
"""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api_quota import QuotaTracker  # noqa: E402
from state.sources_runs import read_all as read_runs  # noqa: E402

PRICE_SNAPSHOTS_DIR = ML_DIR / "state" / "price_snapshots"

NUMISTA_MONTHLY_LIMIT = 1800
EBAY_DAILY_LIMIT = 5000

# In-memory coverage cache (free-tier-friendly).
_coverage_cache: dict[str, Any] = {"data": None, "timestamp": 0.0}
_COVERAGE_TTL_SEC = 60.0


# ── Registry ────────────────────────────────────────────────────────────────

# Each entry holds metadata that can't be derived from the filesystem / DB:
# label, expected cadence, copy for the CLI hints, future-flag, etc.
SOURCES_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "numista_match",
        "label": "Numista — Match",
        "subtitle": "API · détection nouvelles pièces",
        "kind": "api",
        "quota_group": "numista",
        "expected_cadence_days": 14,
        "coverage_unit": "pièces matchées",
        "cli_hints": [
            {
                "kind": "run",
                "title": "Run complet",
                "command": "go-task ml:batch-match",
                "description": "Match toutes les nouvelles pièces du référentiel sans numista_id",
                "expected_outcome": "Met à jour cross_refs.numista_id sur les coins matchés, écrit ml/state/sources_runs.json",
            },
            {
                "kind": "dry-run",
                "title": "Aperçu candidats",
                "command": "go-task ml:batch-match-dry",
                "description": "Affiche les candidats proposés sans rien écrire",
                "expected_outcome": "Liste eurio_id → numista_id proposés en stdout",
            },
        ],
    },
    {
        "id": "numista_enrich",
        "label": "Numista — Enrichissement",
        "subtitle": "API · métadonnées canoniques",
        "kind": "api",
        "quota_group": "numista",
        "expected_cadence_days": 30,
        "coverage_unit": "pièces enrichies",
        "cli_hints": [
            {
                "kind": "run",
                "title": "Run complet",
                "command": "go-task ml:enrich-numista",
                "description": "Enrichit les pièces avec numista_id mais sans métadonnées",
                "expected_outcome": "Ajoute theme/designer/atelier dans coins, ~1 call par pièce",
            },
        ],
    },
    {
        "id": "numista_images",
        "label": "Numista — Images",
        "subtitle": "API · obverse/reverse",
        "kind": "api",
        "quota_group": "numista",
        "expected_cadence_days": 30,
        "coverage_unit": "pièces avec images",
        "cli_hints": [
            {
                "kind": "run",
                "title": "Run complet",
                "command": "go-task ml:batch-images",
                "description": "Télécharge obverse + reverse pour les pièces sans images",
                "expected_outcome": "Met à jour coins.images, écrit ml/state/sources_runs.json",
            },
            {
                "kind": "list",
                "title": "Liste des manquantes",
                "command": "go-task ml:batch-images -- --list-missing",
                "description": "Affiche les eurio_id sans images.obverse",
                "expected_outcome": "1 eurio_id par ligne sur stdout",
            },
        ],
    },
    {
        "id": "ebay",
        "label": "eBay Browse",
        "subtitle": "API · prix marché actif",
        "kind": "api",
        "quota_group": None,
        "quota_source": "ebay",
        "quota_window": "daily",
        "quota_limit": EBAY_DAILY_LIMIT,
        "expected_cadence_days": 30,
        "coverage_unit": "commémos enrichies",
        "cli_hints": [
            {
                "kind": "run",
                "title": "Run complet",
                "command": "go-task ml:scrape-ebay",
                "description": "Enrichit toutes les commémos ciblées (~500 calls)",
                "expected_outcome": "INSERT dans coin_market_prices + ml/state/price_snapshots/ebay_<period>.json",
            },
            {
                "kind": "run",
                "title": "Échantillon (5 pièces)",
                "command": "go-task ml:scrape-ebay -- --limit 5",
                "description": "Limite le run à 5 pièces (test rapide)",
                "expected_outcome": "Snapshot partiel, ~5 calls eBay",
            },
            {
                "kind": "dry-run",
                "title": "Dry-run",
                "command": "go-task ml:scrape-ebay -- --dry-run",
                "description": "Fetch eBay normalement mais skip Supabase et snapshots",
                "expected_outcome": "Aucun INSERT, aucun fichier écrit",
            },
        ],
    },
    {
        "id": "lmdlp",
        "label": "La Maison de la Pièce",
        "subtitle": "Scrape HTML · cotation FR",
        "kind": "scrape",
        "quota_group": None,
        "expected_cadence_days": 90,
        "coverage_unit": "cotations parsées",
        "cli_hints": [
            {
                "kind": "run",
                "title": "Scrape complet",
                "command": "go-task ml:scrape-lmdlp",
                "description": "Re-scrape l'intégralité du catalogue LMDLP",
                "expected_outcome": "Écrit ml/datasets/sources/lmdlp_<date>.json",
            },
            {
                "kind": "list",
                "title": "Liste des manquantes",
                "command": "go-task ml:scrape-lmdlp -- --list-missing",
                "description": "Affiche les commémos non couvertes par LMDLP",
                "expected_outcome": "1 eurio_id par ligne sur stdout",
            },
        ],
    },
    {
        "id": "mdp",
        "label": "Monnaie de Paris",
        "subtitle": "Scrape HTML · catalogue officiel FR",
        "kind": "scrape",
        "quota_group": None,
        "expected_cadence_days": 90,
        "coverage_unit": "fiches parsées",
        "cli_hints": [
            {
                "kind": "run",
                "title": "Scrape complet",
                "command": "go-task ml:scrape-mdp",
                "description": "Re-scrape le catalogue Monnaie de Paris",
                "expected_outcome": "Écrit ml/datasets/sources/mdp_<date>.json",
            },
        ],
    },
    {
        "id": "bce",
        "label": "BCE",
        "subtitle": "Scrape HTML · annonces commémo officielles",
        "kind": "scrape",
        "quota_group": None,
        "expected_cadence_days": 90,
        "coverage_unit": "années couvertes",
        "cli_hints": [
            {
                "kind": "run",
                "title": "Scrape toutes années",
                "command": "go-task ml:scrape-bce",
                "description": "Re-scrape les pages commémo BCE de 2004 à l'année courante",
                "expected_outcome": "Écrit ml/datasets/sources/bce_comm_<year>_<date>.html",
            },
        ],
    },
    {
        "id": "wikipedia",
        "label": "Wikipedia",
        "subtitle": "Scrape HTML · backfill métadonnées par pays",
        "kind": "scrape",
        "quota_group": None,
        "expected_cadence_days": 365,
        "coverage_unit": "pays",
        "is_future": True,
        "future_note": (
            "Source planifiée — pas encore de scraper. À écrire : "
            "ml/referential/scrape_wikipedia.py (page catalogue par pays, 21 pays eurozone)."
        ),
        "cli_hints": [],
    },
]

# Static targets — lookup by source id when coverage isn't computed dynamically.
_STATIC_COVERAGE_TARGETS: dict[str, int] = {
    "bce": 23,        # 2004–2026 → 23 years
    "wikipedia": 21,  # eurozone countries
}


# ── Quota ───────────────────────────────────────────────────────────────────


def _quota_payload(spec: dict) -> dict | None:
    if spec.get("quota_group") == "numista":
        # Per-card quota lives in `quota_groups['numista']`, not on each card.
        return None
    if "quota_source" not in spec:
        return None
    tracker = QuotaTracker(spec["quota_source"], spec["quota_window"], spec["quota_limit"])
    total = tracker.total()
    per_key = tracker.status()
    aggregate_limit = spec["quota_limit"]  # single-key sources only here
    pct = (total.calls / aggregate_limit * 100) if aggregate_limit else 0.0
    payload: dict[str, Any] = {
        "window": total.window,
        "period": total.period,
        "limit": aggregate_limit,
        "calls": total.calls,
        "remaining": max(0, aggregate_limit - total.calls),
        "pct_used": round(pct, 1),
        "exhausted": total.exhausted,
    }
    if per_key:
        payload["per_key"] = [
            {
                "slot": i + 1,
                "key_hash": s.key_hash,
                "calls": s.calls,
                "exhausted": s.exhausted,
            }
            for i, s in enumerate(per_key)
        ]
    return payload


def _numista_quota_payload() -> dict:
    """Aggregate Numista quota across all keys for the response group banner."""
    tracker = QuotaTracker("numista", "monthly", NUMISTA_MONTHLY_LIMIT)
    per_key = tracker.status()
    n_keys = max(len(per_key), 1)
    aggregate_limit = NUMISTA_MONTHLY_LIMIT * n_keys
    total = tracker.total()
    pct = (total.calls / aggregate_limit * 100) if aggregate_limit else 0.0
    return {
        "window": "monthly",
        "period": total.period,
        "limit": aggregate_limit,
        "calls": total.calls,
        "remaining": max(0, aggregate_limit - total.calls),
        "pct_used": round(pct, 1),
        "exhausted": total.exhausted,
        "per_key": [
            {
                "slot": i + 1,
                "key_hash": s.key_hash,
                "calls": s.calls,
                "exhausted": s.exhausted,
            }
            for i, s in enumerate(per_key)
        ],
    }


# ── Temporal ────────────────────────────────────────────────────────────────


def _days_since(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = datetime.now(timezone.utc) - dt
    return max(0, delta.days)


def _ebay_price_delta() -> dict | None:
    """Diff the 2 most recent ebay_<period>.json snapshots."""
    if not PRICE_SNAPSHOTS_DIR.exists():
        return None
    files = sorted(PRICE_SNAPSHOTS_DIR.glob("ebay_*.json"))
    if len(files) < 2:
        return None
    prev = json.loads(files[-2].read_text())
    curr = json.loads(files[-1].read_text())
    prev_coins = prev.get("coins", {})
    curr_coins = curr.get("coins", {})
    prev_ids = set(prev_coins)
    curr_ids = set(curr_coins)
    stable_ids = prev_ids & curr_ids
    n_new = len(curr_ids - prev_ids)
    n_dropped = len(prev_ids - curr_ids)

    deltas_pct: list[float] = []
    for cid in stable_ids:
        p_prev = prev_coins[cid].get("p50")
        p_curr = curr_coins[cid].get("p50")
        if p_prev and p_curr and p_prev > 0:
            deltas_pct.append((p_curr - p_prev) / p_prev * 100)

    if deltas_pct:
        deltas_pct.sort()
        median = statistics.median(deltas_pct)
        p10 = deltas_pct[max(0, math.floor(0.10 * (len(deltas_pct) - 1)))]
        p90 = deltas_pct[max(0, math.floor(0.90 * (len(deltas_pct) - 1)))]
    else:
        median = p10 = p90 = None
    swing_warning = bool(median is not None and abs(median) > 10.0)

    return {
        "n_stable": len(stable_ids),
        "n_new": n_new,
        "n_dropped": n_dropped,
        "delta_p50_median_pct": round(median, 2) if median is not None else None,
        "delta_p50_p10_pct": round(p10, 2) if p10 is not None else None,
        "delta_p50_p90_pct": round(p90, 2) if p90 is not None else None,
        "swing_warning": swing_warning,
    }


def _temporal_payload(spec: dict, runs: dict) -> dict:
    if spec.get("is_future"):
        return {
            "last_run_at": None,
            "last_run_kind": None,
            "days_since_last_run": None,
            "expected_cadence_days": spec["expected_cadence_days"],
            "overdue": False,
            "delta": None,
        }
    run = runs.get(spec["id"], {})
    last_at = run.get("last_run_at")
    days = _days_since(last_at)
    cadence = spec["expected_cadence_days"]
    overdue = bool(days is not None and days > 1.5 * cadence)

    if spec["id"] == "ebay":
        delta = _ebay_price_delta()
    elif run:
        delta = {
            "n_stable": None,
            "n_new": int(run.get("last_run_added_coins", 0)),
            "n_dropped": 0,
            "delta_p50_median_pct": None,
            "delta_p50_p10_pct": None,
            "delta_p50_p90_pct": None,
            "swing_warning": False,
        }
    else:
        delta = None

    return {
        "last_run_at": last_at,
        "last_run_kind": run.get("last_run_kind"),
        "days_since_last_run": days,
        "expected_cadence_days": cadence,
        "overdue": overdue,
        "delta": delta,
    }


# ── Coverage ────────────────────────────────────────────────────────────────


REFERENTIAL_PATH = ML_DIR / "datasets" / "eurio_referential.json"


def _compute_coverage() -> dict[str, dict[str, int]]:
    """Per-source coverage counts derived from `eurio_referential.json`.

    The referential carries the rich schema (`identity`, `provenance.sources_used`)
    that Supabase doesn't expose — and it's the canonical source of truth for
    "which sources have touched which coin". Zero network calls.
    """
    out: dict[str, dict[str, int]] = {
        "numista_match": {"enriched": 0, "total_target": 0},
        "numista_enrich": {"enriched": 0, "total_target": 0},
        "numista_images": {"enriched": 0, "total_target": 0},
        "ebay": {"enriched": 0, "total_target": 0},
        "lmdlp": {"enriched": 0, "total_target": 0},
        "mdp": {"enriched": 0, "total_target": 0},
        "bce": {"enriched": 0, "total_target": _STATIC_COVERAGE_TARGETS["bce"]},
        "wikipedia": {"enriched": 0, "total_target": _STATIC_COVERAGE_TARGETS["wikipedia"]},
    }
    if not REFERENTIAL_PATH.exists():
        return out
    try:
        raw = json.loads(REFERENTIAL_PATH.read_text())
    except json.JSONDecodeError:
        return out
    entries = raw.get("entries", []) if isinstance(raw, dict) else []

    total_coins = len(entries)
    out["numista_match"]["total_target"] = total_coins

    has_numista = 0
    has_images = 0
    enriched_per: dict[str, int] = {"lmdlp": 0, "mdp": 0, "ebay": 0, "bce": 0}
    commemo_total = 0

    for entry in entries:
        cr = entry.get("cross_refs") or {}
        if cr.get("numista_id"):
            has_numista += 1
        imgs = entry.get("images")
        if isinstance(imgs, dict) and imgs.get("obverse"):
            has_images += 1
        elif isinstance(imgs, list) and any(i.get("url") for i in imgs):
            has_images += 1
        ident = entry.get("identity") or {}
        if ident.get("is_commemorative") and ident.get("face_value") == 2.0 and ident.get("country") != "eu":
            commemo_total += 1
        sources = set((entry.get("provenance") or {}).get("sources_used") or [])
        for src in enriched_per:
            if src in sources or (src == "bce" and "bce_comm" in sources):
                enriched_per[src] += 1

    out["numista_match"]["enriched"] = has_numista
    out["numista_enrich"]["total_target"] = has_numista
    out["numista_enrich"]["enriched"] = has_numista
    out["numista_images"]["total_target"] = has_numista
    out["numista_images"]["enriched"] = has_images

    out["ebay"]["total_target"] = commemo_total
    out["ebay"]["enriched"] = enriched_per["ebay"]
    out["lmdlp"]["total_target"] = commemo_total
    out["lmdlp"]["enriched"] = enriched_per["lmdlp"]
    out["mdp"]["total_target"] = commemo_total
    out["mdp"]["enriched"] = enriched_per["mdp"]
    out["bce"]["enriched"] = enriched_per["bce"]
    return out


def _coverage_payload(spec: dict, coverage_map: dict) -> dict:
    bucket = coverage_map.get(spec["id"], {"enriched": 0, "total_target": 0})
    enriched = int(bucket.get("enriched", 0))
    target = int(bucket.get("total_target", 0))
    pct = round((enriched / target * 100), 1) if target else 0.0
    return {
        "enriched": enriched,
        "total_target": target,
        "pct": pct,
        "unit": spec["coverage_unit"],
    }


# ── Health ──────────────────────────────────────────────────────────────────


def _derive_health(quota: dict | None, temporal: dict, group_quota: dict | None) -> tuple[str, str | None]:
    effective_quota = quota or group_quota
    if effective_quota and effective_quota.get("exhausted"):
        return "error", "Quota épuisé"
    if effective_quota and effective_quota.get("pct_used", 0) > 90:
        return "warning", f"Quota presque épuisé ({effective_quota['calls']}/{effective_quota['limit']})"
    if temporal.get("overdue"):
        return "warning", f"Pas de fetch depuis {temporal.get('days_since_last_run')} jours"
    delta = temporal.get("delta") or {}
    if delta.get("swing_warning"):
        return "warning", "Swing de prix anormal détecté"
    return "healthy", None


# ── Public ──────────────────────────────────────────────────────────────────


def build_status() -> dict:
    """Return the full `/sources/status` payload (filesystem + SQLite only)."""
    runs = read_runs()

    # Coverage cache (referential JSON read is cheap but happens 6×/min via poll;
    # 60s TTL still cuts disk reads ~10× without observably stale data).
    now = time.time()
    if (
        _coverage_cache["data"] is not None
        and (now - _coverage_cache["timestamp"]) < _COVERAGE_TTL_SEC
    ):
        coverage_map = _coverage_cache["data"]
    else:
        coverage_map = _compute_coverage()
        _coverage_cache["data"] = coverage_map
        _coverage_cache["timestamp"] = now

    # Numista group quota — computed once for the response banner
    group_numista = _numista_quota_payload()

    sources: list[dict] = []
    for spec in SOURCES_REGISTRY:
        if spec.get("is_future"):
            sources.append({
                "id": spec["id"],
                "label": spec["label"],
                "subtitle": spec["subtitle"],
                "kind": spec["kind"],
                "quota_group": spec.get("quota_group"),
                "quota": None,
                "health": "healthy",
                "health_reason": None,
                "temporal": _temporal_payload(spec, runs),
                "coverage": _coverage_payload(spec, coverage_map),
                "cli_hints": spec["cli_hints"],
                "is_future": True,
                "future_note": spec["future_note"],
            })
            continue

        quota = _quota_payload(spec)
        temporal = _temporal_payload(spec, runs)
        coverage = _coverage_payload(spec, coverage_map)
        group_quota = group_numista if spec.get("quota_group") == "numista" else None
        health, reason = _derive_health(quota, temporal, group_quota)
        sources.append({
            "id": spec["id"],
            "label": spec["label"],
            "subtitle": spec["subtitle"],
            "kind": spec["kind"],
            "quota_group": spec.get("quota_group"),
            "quota": quota,
            "health": health,
            "health_reason": reason,
            "temporal": temporal,
            "coverage": coverage,
            "cli_hints": spec["cli_hints"],
        })

    return {
        "sources": sources,
        "quota_groups": {"numista": group_numista},
    }
