"""Tests C3 local-sync — replay déterministe (apply_remote).

Propriétés vérifiées : convergence (2 ordres d'application → même état),
idempotence (rejouer = no-op), les 3 cas de concurrence du handoff §5,
tombstone terminal, parking/rejeu des orphelins, pas d'écho outbox,
UPSERT review_queue.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store, apply_remote  # noqa: E402
from store.hlc import hlc_encode  # noqa: E402


def _seed(conn, asset_ids=("a1",)):
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id) "
        "VALUES ('si1','ebay','ref1','fr-2018-x')"
    )
    for i, aid in enumerate(asset_ids):
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, "
            " storage_path, eurio_id, resolution_status, training_eligible) "
            "VALUES (?, 'si1', ?, ?, 'fr-2018-x', 'needs_review', 1)",
            (aid, i, f"crops/{aid}.png"),
        )


def _mk_store(tmp_path, name, asset_ids=("a1",)):
    store = Store(tmp_path / name)
    conn = store._connection()  # noqa: SLF001
    _seed(conn, asset_ids)
    return conn


_TS = 1_800_000_000_000  # base ts fictive (ms)


def _ev(asset_id, *, machine, ts_off=0, count=0, fields=None, to_state="resolved",
        reason="test", row_ops=None, eurio_id=None):
    body = {}
    if fields is not None:
        body["v"] = 1
        body["fields"] = fields
    if row_ops is not None:
        body["row_ops"] = row_ops
    return {
        "op_id": uuid.uuid4().hex,
        "asset_id": asset_id,
        "from_state": None,
        "to_state": to_state,
        "actor": "human",
        "reason": reason,
        "eurio_id": eurio_id,
        "target_eurio_id": None,
        "run_id": None,
        "detail_json": json.dumps(body) if body else None,
        "created_at": "2027-01-01T00:00:00Z",
        "machine": machine,
        "hlc": hlc_encode(_TS + ts_off, count, machine),
    }


def _ts(asset_id, *, machine, ts_off=0, storage_path=None):
    return {
        "op_id": uuid.uuid4().hex,
        "asset_id": asset_id,
        "machine": machine,
        "hlc": hlc_encode(_TS + ts_off, 0, machine),
        "storage_path": storage_path,
        "reason": "manual_delete",
        "created_at": "2027-01-01T00:00:00Z",
    }


def _dump(conn):
    """État matérialisé comparable entre deux DB (sans les id autoinc)."""
    assets = [
        tuple(r) for r in conn.execute(
            "SELECT id, eurio_id, resolution_status, training_eligible, "
            "quality_reason FROM image_assets ORDER BY id"
        )
    ]
    rq = [
        tuple(r) for r in conn.execute(
            "SELECT image_asset_id, status, priority, kind, lane "
            "FROM review_queue ORDER BY image_asset_id"
        )
    ]
    cur = [
        tuple(r) for r in conn.execute(
            "SELECT asset_id, current_state, eurio_id FROM image_state_current "
            "ORDER BY asset_id"
        )
    ]
    return assets, rq, cur


# ─── Convergence & idempotence ───────────────────────────────────────────────


def test_convergence_two_application_orders(tmp_path):
    mac = [_ev("a1", machine="mac", ts_off=0,
               fields={"image_assets.training_eligible": 0}),
           _ev("a1", machine="mac", ts_off=2000,
               fields={"image_assets.quality_reason": "manual_triage"})]
    pc = [_ev("a1", machine="pc", ts_off=1000,
              fields={"image_assets.eurio_id": "de-2019-y"})]

    c1 = _mk_store(tmp_path, "one.db")
    apply_remote(c1, events=mac)
    apply_remote(c1, events=pc)

    c2 = _mk_store(tmp_path, "two.db")
    apply_remote(c2, events=pc)
    apply_remote(c2, events=mac)

    assert _dump(c1) == _dump(c2)


def test_idempotence(tmp_path):
    conn = _mk_store(tmp_path, "i.db")
    evs = [_ev("a1", machine="mac", fields={"image_assets.training_eligible": 0})]
    s1 = apply_remote(conn, events=evs)
    before = _dump(conn)
    s2 = apply_remote(conn, events=evs)
    assert s1.inserted == 1 and s2.inserted == 0 and s2.duplicates == 1
    assert _dump(conn) == before


# ─── Les 3 cas du handoff §5 ─────────────────────────────────────────────────


def test_case1_distinct_assets_union(tmp_path):
    conn = _mk_store(tmp_path, "c1.db", asset_ids=("a1", "a2"))
    apply_remote(conn, events=[
        _ev("a1", machine="mac", fields={"image_assets.training_eligible": 0}),
        _ev("a2", machine="pc", fields={"image_assets.training_eligible": 0}),
    ])
    rows = conn.execute(
        "SELECT id, training_eligible FROM image_assets ORDER BY id"
    ).fetchall()
    assert [r["training_eligible"] for r in rows] == [0, 0]


def test_case2_same_asset_different_fields_both_apply(tmp_path):
    conn = _mk_store(tmp_path, "c2.db")
    apply_remote(conn, events=[
        _ev("a1", machine="mac", ts_off=0,
            fields={"image_assets.eurio_id": "de-2019-y"}),
        _ev("a1", machine="pc", ts_off=1,
            fields={"image_assets.training_eligible": 0}),
    ])
    row = conn.execute(
        "SELECT eurio_id, training_eligible FROM image_assets WHERE id='a1'"
    ).fetchone()
    assert row["eurio_id"] == "de-2019-y"
    assert row["training_eligible"] == 0


def test_case3_same_field_last_hlc_wins_loser_kept_in_log(tmp_path):
    conn = _mk_store(tmp_path, "c3.db")
    older = _ev("a1", machine="mac", ts_off=0,
                fields={"image_assets.training_eligible": 1})
    newer = _ev("a1", machine="pc", ts_off=5000,
                fields={"image_assets.training_eligible": 0})
    # Application dans l'ordre INVERSE de l'HLC : le plus récent doit gagner
    # quand même (relecture ordonnée, pas ordre d'arrivée).
    apply_remote(conn, events=[newer])
    apply_remote(conn, events=[older])
    row = conn.execute(
        "SELECT training_eligible FROM image_assets WHERE id='a1'"
    ).fetchone()
    assert row["training_eligible"] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM image_state_events WHERE asset_id='a1'"
    ).fetchone()[0] == 2  # l'événement perdant reste (audit)


# ─── Tombstones ──────────────────────────────────────────────────────────────


def test_tombstone_deletes_and_blocks_later_events(tmp_path):
    conn = _mk_store(tmp_path, "t.db")
    apply_remote(conn, tombstones=[_ts("a1", machine="pc", storage_path="crops/a1.png")],
                 events=[])
    assert conn.execute(
        "SELECT COUNT(*) FROM image_assets WHERE id='a1'"
    ).fetchone()[0] == 0
    # Un event ultérieur (même plus récent HLC) est ignoré : delete terminal.
    stats = apply_remote(conn, events=[
        _ev("a1", machine="mac", ts_off=99000,
            fields={"image_assets.training_eligible": 0}),
    ])
    assert stats.skipped_dead == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM image_assets WHERE id='a1'"
    ).fetchone()[0] == 0


# ─── Orphelins ───────────────────────────────────────────────────────────────


def test_orphan_parked_then_replayed(tmp_path):
    conn = _mk_store(tmp_path, "o.db")
    ev = _ev("ghost", machine="pc", fields={"image_assets.training_eligible": 0})
    s1 = apply_remote(conn, events=[ev])
    assert s1.orphaned == 1
    assert conn.execute("SELECT COUNT(*) FROM sync_orphan_events").fetchone()[0] == 1

    # L'asset arrive (via pull-replica / ingest simulé) → le prochain apply rejoue.
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, storage_path, "
        " training_eligible) VALUES ('ghost', 'si1', 9, 'crops/g.png', 1)"
    )
    s2 = apply_remote(conn, events=[])
    assert s2.orphans_retried == 1 and s2.inserted == 1
    assert conn.execute(
        "SELECT training_eligible FROM image_assets WHERE id='ghost'"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sync_orphan_events").fetchone()[0] == 0


def test_add_crop_snapshot_creates_row(tmp_path):
    conn = _mk_store(tmp_path, "s.db")
    ev = _ev(
        "newborn", machine="mac", reason="manual_add_crop", to_state="detected",
        fields={},
        row_ops=[{
            "op": "upsert", "table": "image_assets", "key": {"id": "newborn"},
            "values": {
                "source_image_id": "si1", "crop_index": 3,
                "bbox_json": "{}", "detection_method": "manual_add",
                "resolution_status": "needs_review", "phash": "abcd",
                "storage_path": "crops/newborn.png", "storage_status": "present",
                "width": 224, "height": 224,
            },
        }],
    )
    stats = apply_remote(conn, events=[ev])
    assert stats.inserted == 1 and stats.orphaned == 0
    row = conn.execute(
        "SELECT * FROM image_assets WHERE id='newborn'"
    ).fetchone()
    assert row is not None and row["detection_method"] == "manual_add"


# ─── Pas d'écho + UPSERT review_queue ────────────────────────────────────────


def test_no_outbox_echo(tmp_path):
    conn = _mk_store(tmp_path, "e.db")
    apply_remote(conn, events=[
        _ev("a1", machine="pc", fields={"image_assets.training_eligible": 0}),
    ])
    assert conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == 0


def test_review_queue_upserted_from_fields(tmp_path):
    conn = _mk_store(tmp_path, "rq.db")
    # Pas de row review_queue locale → les fields la créent.
    apply_remote(conn, events=[
        _ev("a1", machine="pc", to_state="queued", reason="reopened",
            fields={
                "review_queue.status": "open",
                "review_queue.priority": 100,
                "review_queue.kind": "single",
                "review_queue.lane": "manual",
                "review_queue.lane_source": "human",
            }),
    ])
    rq = conn.execute(
        "SELECT * FROM review_queue WHERE image_asset_id='a1'"
    ).fetchone()
    assert rq is not None and rq["status"] == "open" and rq["lane"] == "manual"
    assert rq["enqueued_at"]  # NOT NULL posé par le replay

    # Row existante → mise à jour, pas de doublon.
    apply_remote(conn, events=[
        _ev("a1", machine="mac", ts_off=1000, to_state="resolved", reason="decided",
            fields={"review_queue.status": "done"}),
    ])
    rows = conn.execute(
        "SELECT status FROM review_queue WHERE image_asset_id='a1'"
    ).fetchall()
    assert len(rows) == 1 and rows[0]["status"] == "done"


def test_state_current_follows_hlc_order(tmp_path):
    conn = _mk_store(tmp_path, "sc.db")
    newer = _ev("a1", machine="pc", ts_off=5000, to_state="rejected",
                reason="rejected", fields={"image_assets.resolution_status": "rejected"})
    older = _ev("a1", machine="mac", ts_off=0, to_state="resolved",
                reason="decided", fields={"image_assets.resolution_status": "manual"})
    apply_remote(conn, events=[newer])
    apply_remote(conn, events=[older])
    cur = conn.execute(
        "SELECT current_state FROM image_state_current WHERE asset_id='a1'"
    ).fetchone()
    assert cur["current_state"] == "rejected"  # le plus récent HLC, pas le dernier arrivé
