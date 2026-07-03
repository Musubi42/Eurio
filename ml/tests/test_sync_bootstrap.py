"""Tests C7 local-sync — bootstrap backfill + garde pull-replica."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store, emit_field_event  # noqa: E402


def _seed(conn, *, eligible=1, status="needs_review"):
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref) VALUES ('si1','ebay','r1')"
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, eurio_id, "
        " resolution_status, training_eligible) "
        "VALUES ('a1', 'si1', 'c/a1.png', 'fr-2018-x', ?, ?)",
        (status, eligible),
    )


def test_diff_detects_local_divergence(tmp_path):
    from client.sync_bootstrap import _connect_ro, _diff

    local_store = Store(tmp_path / "local.db")
    lc = local_store._connection()  # noqa: SLF001
    _seed(lc, eligible=0, status="manual")  # décisions locales
    lc.execute(
        "INSERT INTO review_queue (id, image_asset_id, status, priority, "
        "enqueued_at, kind) VALUES ('rq1','a1','done',10,datetime('now'),'single')"
    )

    canon_store = Store(tmp_path / "canon.db")
    cc = canon_store._connection()  # noqa: SLF001
    _seed(cc)  # état canonique d'avant les décisions

    diff = _diff(_connect_ro(tmp_path / "local.db"), _connect_ro(tmp_path / "canon.db"))
    assert "a1" in diff
    f = diff["a1"]
    assert f["image_assets.training_eligible"] == 0
    assert f["image_assets.resolution_status"] == "manual"
    assert f["review_queue.status"] == "done"  # row locale absente du canonique
    # Champ identique → pas de bruit.
    assert "image_assets.eurio_id" not in f


def test_pull_replica_refuses_pending_ops(tmp_path):
    from client.replica import pull_replica

    db = tmp_path / "work.db"
    store = Store(db)
    conn = store._connection()  # noqa: SLF001
    _seed(conn)
    emit_field_event(
        conn, asset_id="a1", reason="training_eligible",
        fields={"image_assets.training_eligible": 0},
    )
    with pytest.raises(RuntimeError, match="non poussée"):
        pull_replica(db)
