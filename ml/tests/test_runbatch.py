"""Tests pour le run-batch export/ingest (Modèle B, chunk C1).

Couvre :
- **Parité** : un run exporté d'une DB → ingéré dans une DB VIERGE → contenu
  identique sur les 9 tables (le serveur canonique reconstruit le run à l'identique).
- **Idempotence** : ré-ingérer le même batch = no-op total (``already_applied``),
  comptages stables, aucun doublon (y compris ``image_state_events`` sans clé
  naturelle).
- **Scoping** : un autre run n'est pas aspiré ; les events de review postérieurs
  (run_id NULL) ne sont pas écrasés par un ré-ingest.

Cf. docs/work-in-progress/model-b/DESIGN.md §C1.
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from client.runbatch import export_run, ingest_run
from store import Store

RUN = "run_test_1"
_HEAVY_TABLES = [
    "source_runs", "source_images", "image_assets", "listing_text_signals",
    "image_asset_dino_predictions", "review_queue", "consensus_verdicts",
    "coin_market_quotes", "image_state_events",
]


def _seed_run(conn, run_id=RUN, *, item_offset=0) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO source_registry (id, display_name, kind) "
        "VALUES ('ebay','eBay','marketplace')"
    )
    conn.execute(
        "INSERT INTO source_runs (id, source, kind) VALUES (?, 'ebay', 'run')",
        (run_id,),
    )
    for i in (item_offset, item_offset + 1):
        si = f"si_{run_id}_{i}"
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref, run_id, listing_title) "
            "VALUES (?, 'ebay', ?, ?, ?)",
            (si, f"ebay_item_{i}", run_id, f"Lot {i}"),
        )
        conn.execute(
            "INSERT INTO listing_text_signals (source_image_id, coverage) VALUES (?, 'rich')",
            (si,),
        )
        for c in (0, 1):
            aid = f"a_{run_id}_{i}_{c}"
            conn.execute(
                "INSERT INTO image_assets (id, source_image_id, run_id, crop_index, "
                "storage_path) VALUES (?, ?, ?, ?, ?)",
                (aid, si, run_id, c, f"ebay/{aid}.png"),
            )
            conn.execute(
                "INSERT INTO image_asset_dino_predictions "
                "(asset_id, encoder_version, anchors_kind, anchors_count, top_k_json) "
                "VALUES (?, 'dinov2-vits14', '2eur_commemo', 10, '[]')",
                (aid,),
            )
            conn.execute(
                "INSERT INTO review_queue (id, image_asset_id, status) VALUES (?, ?, 'open')",
                (f"rq_{aid}", aid),
            )
            conn.execute(
                "INSERT INTO consensus_verdicts "
                "(image_asset_id, rule_version, outcome, lane, rule) "
                "VALUES (?, 1, 'needs_review', 'manual', 'r1')",
                (aid,),
            )
            conn.execute(
                "INSERT INTO image_state_events (asset_id, to_state, actor, run_id) "
                "VALUES (?, 'queued', 'pipeline', ?)",
                (aid, run_id),
            )
    conn.execute(
        "INSERT INTO coin_market_quotes "
        "(id, eurio_id, source, run_id, period_start, period_end, condition_raw) "
        "VALUES (?, ?, 'ebay', ?, '2026-06-01', '2026-06-07', 'UNC')",
        (f"q_{run_id}", f"be-2007-{run_id}", run_id),
    )


def _dump(conn, run_id=RUN) -> dict[str, list[dict]]:
    """Snapshot comparable des 9 tables pour ce run (events sans l'id autoinc)."""
    b = export_run(conn, run_id)
    return b["tables"]


def test_export_collects_full_run(tmp_path):
    store = Store(tmp_path / "a.db")
    conn = store._connection()  # noqa: SLF001
    _seed_run(conn)
    tables = export_run(conn, RUN)["tables"]
    assert len(tables["source_images"]) == 2
    assert len(tables["image_assets"]) == 4
    assert len(tables["listing_text_signals"]) == 2
    assert len(tables["image_asset_dino_predictions"]) == 4
    assert len(tables["review_queue"]) == 4
    assert len(tables["consensus_verdicts"]) == 4
    assert len(tables["coin_market_quotes"]) == 1
    assert len(tables["image_state_events"]) == 4
    # l'id AUTOINCREMENT des events n'est pas transporté
    assert all("id" not in e for e in tables["image_state_events"])


def test_parity_export_then_ingest_into_fresh_db(tmp_path):
    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    _seed_run(sconn)
    batch = export_run(sconn, RUN)

    dst = Store(tmp_path / "dst.db")
    dconn = dst._connection()  # noqa: SLF001
    res = ingest_run(dconn, batch)
    assert res["already_applied"] is False

    # Contenu identique sur les 9 tables (le canonique reconstruit le run).
    assert _dump(dconn) == _dump(sconn)
    for t in _HEAVY_TABLES:
        n_src = sconn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        n_dst = dconn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        assert n_dst == n_src, t
    # run journalisé
    assert dconn.execute(
        "SELECT COUNT(*) FROM ingested_runs WHERE run_id=?", (RUN,)
    ).fetchone()[0] == 1


def test_ingest_is_idempotent(tmp_path):
    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    _seed_run(sconn)
    batch = export_run(sconn, RUN)

    dst = Store(tmp_path / "dst.db")
    dconn = dst._connection()  # noqa: SLF001
    ingest_run(dconn, batch)
    before = _dump(dconn)

    res2 = ingest_run(dconn, batch)
    assert res2["already_applied"] is True
    after = _dump(dconn)
    assert after == before  # aucun doublon, y compris image_state_events
    for t in _HEAVY_TABLES:
        assert dconn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == len(before[t])


def test_ingest_scopes_to_run_and_preserves_later_events(tmp_path):
    src = Store(tmp_path / "src.db")
    sconn = src._connection()  # noqa: SLF001
    _seed_run(sconn)
    batch = export_run(sconn, RUN)

    dst = Store(tmp_path / "dst.db")
    dconn = dst._connection()  # noqa: SLF001
    ingest_run(dconn, batch)

    # Un autre run présent dans le canonique ne doit pas être touché par le ré-ingest.
    _seed_run(dconn, run_id="other_run", item_offset=100)
    # Un event de REVIEW postérieur (run_id NULL) sur un asset du run ingéré.
    dconn.execute(
        "INSERT INTO image_state_events (asset_id, to_state, actor, run_id) "
        "VALUES (?, 'resolved', 'human', NULL)",
        (f"a_{RUN}_0_0",),
    )
    later_events = dconn.execute(
        "SELECT COUNT(*) FROM image_state_events WHERE run_id IS NULL"
    ).fetchone()[0]

    # Ré-ingest du run (sha inchangé → no-op) : l'event review survit.
    ingest_run(dconn, batch)
    assert dconn.execute(
        "SELECT COUNT(*) FROM image_state_events WHERE run_id IS NULL"
    ).fetchone()[0] == later_events
    # l'autre run intact
    assert dconn.execute(
        "SELECT COUNT(*) FROM source_images WHERE run_id='other_run'"
    ).fetchone()[0] == 2
