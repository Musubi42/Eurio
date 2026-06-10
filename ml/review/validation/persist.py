"""Persistance du verdict de consensus (table ``consensus_verdicts``).

Écrit le verdict d'ensemble (``consensus.consensus_verdict``) par image_asset,
versionné par ``rule_version`` : REPLACE au rerun de la même version, coexistence
des versions (audit/replay d'une règle révisée). Snapshote les Signals experts
dans ``signals_json`` pour audit à froid.

Statut : SHADOW. ``upsert_consensus_verdict`` peut être appelée hors-ligne
(scripts/persist_consensus.py) sans toucher la décision de routage live ; le
câblage pipeline (remplacer le kill 2.5 + la branche contradict→divergent) est le
chunk suivant. Lit/écrit via une ``sqlite3.Connection`` brute + ``commit()``
explicite (sûr sous isolation_level='' comme None, cf. feedback_store_autocommit).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from review.validation.consensus import RULE_VERSION, ConsensusVerdict, consensus_verdict
from review.validation.experts import Signal, collect_signals

_UPSERT = """
INSERT INTO consensus_verdicts
  (image_asset_id, rule_version, outcome, lane, confidence, reason, rule,
   signals_json, computed_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
ON CONFLICT(image_asset_id, rule_version) DO UPDATE SET
  outcome      = excluded.outcome,
  lane         = excluded.lane,
  confidence   = excluded.confidence,
  reason       = excluded.reason,
  rule         = excluded.rule,
  signals_json = excluded.signals_json,
  computed_at  = datetime('now')
"""


def _signals_json(signals: list[Signal]) -> str:
    """Snapshot JSON des Signals experts (audit). ``raw`` est déjà JSON-safe."""
    return json.dumps([asdict(s) for s in signals], ensure_ascii=False)


def upsert_consensus_verdict(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    signals: list[Signal] | None = None,
    verdict: ConsensusVerdict | None = None,
    rule_version: int = RULE_VERSION,
    commit: bool = True,
) -> ConsensusVerdict | None:
    """Calcule (si besoin) et persiste le verdict de consensus d'un asset.

    Retourne le ``ConsensusVerdict`` écrit, ou ``None`` si l'asset n'a aucun
    signal exploitable (introuvable / non résolu) — dans ce cas rien n'est écrit.
    Passer ``signals``/``verdict`` pré-calculés évite de re-résoudre (réutilise le
    travail d'un replay/shadow). ``commit=False`` pour batcher plusieurs écritures.
    """
    if signals is None:
        signals = collect_signals(conn, asset_id)
    if not signals:
        return None
    if verdict is None:
        verdict = consensus_verdict(signals)

    conn.execute(
        _UPSERT,
        (
            asset_id,
            rule_version,
            verdict.outcome,
            verdict.lane,
            verdict.confidence,
            verdict.reason,
            verdict.rule,
            _signals_json(signals),
        ),
    )
    if commit:
        conn.commit()
    return verdict


def load_consensus_verdict(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    rule_version: int = RULE_VERSION,
) -> ConsensusVerdict | None:
    """Relit le dernier verdict persisté pour ``(asset, rule_version)`` (ou None)."""
    row = conn.execute(
        "SELECT outcome, lane, confidence, reason, rule "
        "  FROM consensus_verdicts "
        " WHERE image_asset_id = ? AND rule_version = ?",
        (asset_id, rule_version),
    ).fetchone()
    if row is None:
        return None
    return ConsensusVerdict(
        outcome=row[0], lane=row[1], confidence=row[2], reason=row[3], rule=row[4]
    )
