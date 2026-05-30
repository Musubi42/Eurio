"""Refresh par (coin × source) — rejoue le fetch ciblé sous UN run unique et
écrit le verdict dans ``coin_source_status``.

- BCE : un seul ``source_runs`` couvre images + i18n + facts (decision 4 du plan
  disponibilité). Verdict dérivé de la donnée DB après coup + signal d'erreur
  réseau : ``empty_upstream`` seulement sur signal positif (404/coin absent, pas
  d'exception), ``error`` sur toute exception, ``ok`` dès qu'un axe a écrit.
- Numista : résout l'eurio_id → numista_id (canonique pour les variantes) puis
  ``refetch_nids``. Pas d'``empty_upstream`` en pratique (un numista_id = page
  existante).

Appelé par l'endpoint ``POST /coins/{id}/refresh`` dans un thread daemon.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sources._base.adapter import SourceQuery
from sources._base.run_logger import start_run
from sources.bce.adapter import BceAdapter
from sources.bce.pipeline import run_bce_steps
from sources.bce.sidecar import RunManifest
from referential.scrape_bce_facts import harvest as facts_harvest
from referential.scrape_bce_i18n import BCE_EU_LANGS, harvest as i18n_harvest
from scripts.refetch_numista_2eur import refetch_nids
from state.source_status import bce_axes as _bce_axes
from state.source_status import jo_axes as _jo_axes
from state.source_status import lmdlp_axes as _lmdlp_axes
from state.source_status import numista_axes as _numista_axes
from state.source_status import upsert_source_status

logger = logging.getLogger(__name__)

_ML_ROOT = Path(__file__).resolve().parents[1]
NUMISTA_CACHE_DIR = _ML_ROOT / "state" / "numista_cache"

VALID_SOURCES = ("bce", "numista", "jo", "lmdlp")
# source court (endpoint/run) → registry id (coin_source_status.source)
_REGISTRY = {"bce": "bce_official", "numista": "numista_api",
             "jo": "eurlex_jo", "lmdlp": "lmdlp"}


def _set_step(conn: sqlite3.Connection, run_id: str, step: str) -> None:
    """current_step d'étapes hors PIPELINE_STEPS générique (i18n/facts/refetch)
    — via SQL direct, comme le pipeline BCE pour 'canonical_promote'."""
    conn.execute("UPDATE source_runs SET current_step = ? WHERE id = ?", (step, run_id))


def _resolve_numista_id(conn: sqlite3.Connection, eurio_id: str) -> int | None:
    """numista_id du coin ; pour une variante, celui de sa canonique
    (decision 2). Fallback coin_source_refs."""
    row = conn.execute(
        "SELECT numista_id, canonical_eurio_id FROM coins WHERE eurio_id=?",
        (eurio_id,),
    ).fetchone()
    if row is None:
        return None
    if row["numista_id"] is not None:
        return int(row["numista_id"])
    if row["canonical_eurio_id"]:
        c = conn.execute("SELECT numista_id FROM coins WHERE eurio_id=?",
                         (row["canonical_eurio_id"],)).fetchone()
        if c and c[0] is not None:
            return int(c[0])
    ref = conn.execute(
        "SELECT source_native_id FROM coin_source_refs "
        "WHERE target_kind='coin' AND target_id=? AND source='numista_api'",
        (eurio_id,),
    ).fetchone()
    if ref and str(ref[0]).isdigit():
        return int(ref[0])
    return None


def refresh_bce_coin(store, eurio_id: str, *, force: bool = False) -> str:
    """Refresh BCE d'un coin (images + i18n + facts) sous 1 run. Retourne run_id."""
    conn = store._connection()  # noqa: SLF001
    row = conn.execute("SELECT year FROM coins WHERE eurio_id=?", (eurio_id,)).fetchone()
    year = row["year"]
    adapter = BceAdapter(conn=conn)
    errors: list[tuple[str, str]] = []

    with start_run(conn, source="bce", kind="run",
                   filters={"eurio_id": eurio_id, "mode": "refresh"}, force=force) as run:
        manifest = RunManifest(
            run_id=run.run_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            kind="run", query={"eurio_id": eurio_id, "mode": "refresh"},
        )
        # 1. Images
        try:
            q = SourceQuery(source_id="bce", year=year, target_eurio_ids=(eurio_id,))
            run_bce_steps(adapter, q, conn=conn, run=run, manifest=manifest)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[refresh] BCE images %s", eurio_id)
            errors.append(("images", str(exc)))
        # 2. i18n
        _set_step(conn, run.run_id, "i18n")
        try:
            i18n_harvest(store, years=[year], langs=list(BCE_EU_LANGS),
                         target_eurio_ids={eurio_id})
        except Exception as exc:  # noqa: BLE001
            logger.exception("[refresh] BCE i18n %s", eurio_id)
            errors.append(("i18n", str(exc)))
        # 3. Facts
        _set_step(conn, run.run_id, "facts")
        try:
            facts_harvest(store, years=[year], target_eurio_ids={eurio_id})
        except Exception as exc:  # noqa: BLE001
            logger.exception("[refresh] BCE facts %s", eurio_id)
            errors.append(("facts", str(exc)))

        # Verdict
        axes = _bce_axes(conn, eurio_id)
        err_msg = "; ".join(f"{a}:{m}" for a, m in errors) or None
        if any(axes.values()):
            state, partial, status = "ok", bool(errors), ("partial" if errors else "success")
        elif errors:
            state, partial, status = "error", False, "failed"
        else:
            state, partial, status = "empty_upstream", False, "success"
        upsert_source_status(conn, eurio_id=eurio_id, source="bce_official",
                             state=state, axes=axes, run_id=run.run_id,
                             error=err_msg, partial=partial)
        manifest.status = status
        manifest.error_summary = err_msg
        manifest.ended_at = datetime.now(timezone.utc).isoformat()
        manifest.write()
        run.end(status, error_summary=err_msg)
    return run.run_id


def refresh_numista_coin(store, eurio_id: str, *, force: bool = False) -> str:
    """Refresh Numista d'un coin (resolve nid → refetch). Retourne run_id."""
    conn = store._connection()  # noqa: SLF001
    nid = _resolve_numista_id(conn, eurio_id)

    with start_run(conn, source="numista", kind="run",
                   filters={"eurio_id": eurio_id, "mode": "refresh"}, force=force) as run:
        if nid is None:
            upsert_source_status(conn, eurio_id=eurio_id, source="numista_api",
                                 state="error", axes={}, run_id=run.run_id,
                                 error="no_numista_id")
            run.end("failed", error_summary="no_numista_id")
            return run.run_id
        _set_step(conn, run.run_id, "refetch")
        try:
            result = refetch_nids([nid], cache_dir=NUMISTA_CACHE_DIR, db_path=store.db_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[refresh] Numista %s (nid=%s)", eurio_id, nid)
            result = {"ok": False, "error": str(exc)}
        axes = _numista_axes(conn, eurio_id)
        if result.get("ok") and any(axes.values()):
            state, status, err = "ok", "success", None
        else:
            state, status, err = "error", "failed", result.get("error", "refetch_failed")
        upsert_source_status(conn, eurio_id=eurio_id, source="numista_api",
                             state=state, axes=axes, run_id=run.run_id, error=err)
        run.end(status, error_summary=err)
    return run.run_id


def refresh_jo_coin(store, eurio_id: str, *, force: bool = False) -> str:
    """Refresh JO/EUR-Lex d'un coin : rejoue le pipeline ciblé sur l'eurio_id.

    Le pipeline écrit ``coin_source_status='ok'`` quand l'avis est trouvé +
    promu. Si aucun avis ne matche (pièce absente du JO), on pose
    ``empty_upstream`` — signal positif « la source n'a rien pour ce coin »."""
    from sources.jo.adapter import JoAdapter
    from sources.jo.pipeline import run_jo_pipeline

    conn = store._connection()  # noqa: SLF001
    adapter = JoAdapter(conn=conn)
    q = SourceQuery(source_id="jo", target_eurio_ids=(eurio_id,))
    run_id = run_jo_pipeline(adapter, q, store=store, force=force)

    axes = _jo_axes(conn, eurio_id)
    if not any(axes.values()):
        upsert_source_status(conn, eurio_id=eurio_id, source="eurlex_jo",
                             state="empty_upstream", axes=axes, run_id=run_id)
    return run_id


def refresh_lmdlp_coin(store, eurio_id: str, *, force: bool = False) -> str:
    """Refresh LMDLP d'un coin : rejoue le pipeline ciblé sur l'eurio_id.

    Réutilise le snapshot du jour (cache) → pas de re-pagination du shop. Le
    pipeline écrit ``coin_source_status='ok'`` quand des quotes sont promues ;
    si la boutique n'a aucun produit matchant ce coin, on pose
    ``empty_upstream`` (signal positif « rien chez LMDLP pour ce coin »)."""
    from sources.lmdlp import LmdlpAdapter
    from sources.lmdlp.pipeline import run_lmdlp_pipeline

    conn = store._connection()  # noqa: SLF001
    adapter = LmdlpAdapter(conn=conn)
    q = SourceQuery(source_id="lmdlp", target_eurio_ids=(eurio_id,))
    run_id = run_lmdlp_pipeline(adapter, q, store=store, force=force)

    axes = _lmdlp_axes(conn, eurio_id)
    if not any(axes.values()):
        upsert_source_status(conn, eurio_id=eurio_id, source="lmdlp",
                             state="empty_upstream", axes=axes, run_id=run_id)
    return run_id


def refresh_coin(store, eurio_id: str, source: str, *, force: bool = False) -> str:
    if source == "bce":
        return refresh_bce_coin(store, eurio_id, force=force)
    if source == "numista":
        return refresh_numista_coin(store, eurio_id, force=force)
    if source == "jo":
        return refresh_jo_coin(store, eurio_id, force=force)
    if source == "lmdlp":
        return refresh_lmdlp_coin(store, eurio_id, force=force)
    raise ValueError(f"source non supportée: {source!r}")
