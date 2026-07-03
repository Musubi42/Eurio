"""Tests fondation local-sync (C1) — HLC, stamping des events, outbox, tombstones.

Vérifie : monotonie du HLC (rafale, horloge qui recule, restart), hlc_merge
(causalité au pull), estampillage op_id/machine/hlc par emit_state_event +
enfilage outbox, mode hub (VPS : stampe sans enfiler), record_tombstone,
et migration additive d'une DB antérieure (colonnes posées au boot).
"""

from __future__ import annotations

import sqlite3

import pytest

from store import (
    Store,
    emit_state_event,
    hlc_merge,
    hlc_now,
    hlc_parse,
    machine_id,
    record_tombstone,
)
from store.hlc import hlc_encode


def _seed_asset(conn, *, asset_id="a1", target="fr-2018-x"):
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id) "
        "VALUES ('si1','ebay','ref1',?)",
        (target,),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path) "
        "VALUES (?, 'si1', 'crops/x.jpg')",
        (asset_id,),
    )


@pytest.fixture()
def conn(tmp_path):
    store = Store(tmp_path / "t.db")
    c = store._connection()  # noqa: SLF001
    _seed_asset(c)
    return c


# ─── HLC ──────────────────────────────────────────────────────────────────────


def test_hlc_monotone_burst(conn):
    machine = machine_id(conn)
    stamps = [hlc_now(conn, machine) for _ in range(50)]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == 50


def test_hlc_monotone_wall_clock_backwards(conn, monkeypatch):
    machine = machine_id(conn)
    first = hlc_now(conn, machine)
    ts, _count, _m = hlc_parse(first)
    # Horloge murale qui recule d'une heure : le HLC continue d'avancer.
    monkeypatch.setattr("store.hlc.time.time", lambda: (ts - 3_600_000) / 1000)
    second = hlc_now(conn, machine)
    assert second > first
    ts2, count2, _ = hlc_parse(second)
    assert ts2 == ts
    assert count2 >= 1


def test_hlc_survives_restart(tmp_path):
    db = tmp_path / "t.db"
    store = Store(db)
    c = store._connection()  # noqa: SLF001
    machine = machine_id(c)
    first = hlc_now(c, machine)
    # « Restart » : nouvelle connexion sur le même fichier (hlc_last persisté).
    c2 = sqlite3.connect(db)
    c2.row_factory = sqlite3.Row
    second = hlc_now(c2, machine)
    assert second > first


def test_hlc_merge_advances_clock(conn):
    machine = machine_id(conn)
    local = hlc_now(conn, machine)
    ts, _c, _m = hlc_parse(local)
    remote = hlc_encode(ts + 60_000, 7, "other-machine")
    hlc_merge(conn, remote)
    nxt = hlc_now(conn, machine)
    assert nxt > remote  # tout event local futur ordonne APRÈS ce qu'on a vu


def test_hlc_merge_ignores_older(conn):
    machine = machine_id(conn)
    local = hlc_now(conn, machine)
    hlc_merge(conn, hlc_encode(0, 0, "old"))
    nxt = hlc_now(conn, machine)
    assert nxt > local


def test_machine_id_stable_and_env_override(conn, monkeypatch):
    first = machine_id(conn)
    assert machine_id(conn) == first  # stable par base
    monkeypatch.setenv("EURIO_MACHINE_ID", "VPS")
    assert machine_id(conn) == "vps"  # override env, sanitisé


# ─── Stamping emit_state_event + outbox ──────────────────────────────────────


def test_emit_stamps_and_enqueues(conn):
    eid = emit_state_event(
        conn, asset_id="a1", to_state="detected", actor="pipeline",
        reason="crop_detected", detail_fields={"image_assets.training_eligible": 1},
    )
    ev = conn.execute(
        "SELECT * FROM image_state_events WHERE id=?", (eid,)
    ).fetchone()
    assert ev["op_id"] and len(ev["op_id"]) == 32
    assert ev["machine"] == machine_id(conn)
    assert ev["hlc"] and ev["hlc"].endswith(ev["machine"])
    import json
    body = json.loads(ev["detail_json"])
    assert body["v"] == 1
    assert body["fields"] == {"image_assets.training_eligible": 1}

    ob = conn.execute(
        "SELECT * FROM sync_outbox WHERE op_id=?", (ev["op_id"],)
    ).fetchone()
    assert ob["kind"] == "event"
    assert ob["event_id"] == eid
    assert ob["status"] == "pending"


def test_emit_without_fields_keeps_detail(conn):
    eid = emit_state_event(
        conn, asset_id="a1", to_state="detected", actor="pipeline",
        detail={"sim": 0.9},
    )
    ev = conn.execute(
        "SELECT detail_json, op_id FROM image_state_events WHERE id=?", (eid,)
    ).fetchone()
    import json
    assert json.loads(ev["detail_json"]) == {"sim": 0.9}
    assert ev["op_id"] is not None


def test_hub_mode_stamps_without_outbox(conn, monkeypatch):
    monkeypatch.setenv("EURIO_SYNC_MODE", "hub")
    eid = emit_state_event(
        conn, asset_id="a1", to_state="detected", actor="pipeline",
    )
    ev = conn.execute(
        "SELECT op_id, hlc FROM image_state_events WHERE id=?", (eid,)
    ).fetchone()
    assert ev["op_id"] and ev["hlc"]
    assert conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == 0


def test_events_hlc_ordered_within_machine(conn):
    ids = [
        emit_state_event(conn, asset_id="a1", to_state=s, actor="pipeline")
        for s in ("detected", "queued", "resolved")
    ]
    rows = conn.execute(
        "SELECT hlc FROM image_state_events WHERE id IN (?,?,?) ORDER BY id",
        ids,
    ).fetchall()
    hlcs = [r["hlc"] for r in rows]
    assert hlcs == sorted(hlcs)


# ─── Tombstones ──────────────────────────────────────────────────────────────


def test_record_tombstone_then_delete_keeps_tombstone(conn):
    emit_state_event(conn, asset_id="a1", to_state="detected", actor="pipeline")
    op = record_tombstone(
        conn, asset_id="a1", storage_path="crops/x.jpg", reason="manual_delete",
    )
    conn.execute("DELETE FROM image_assets WHERE id='a1'")
    # Les events de l'asset sont cascadés, le tombstone survit.
    assert conn.execute(
        "SELECT COUNT(*) FROM image_state_events WHERE asset_id='a1'"
    ).fetchone()[0] == 0
    ts = conn.execute(
        "SELECT * FROM sync_tombstones WHERE asset_id='a1'"
    ).fetchone()
    assert ts["op_id"] == op
    assert ts["storage_path"] == "crops/x.jpg"
    # L'entrée outbox de l'event est cascadée, celle du tombstone survit.
    kinds = {
        r["kind"]
        for r in conn.execute("SELECT kind FROM sync_outbox").fetchall()
    }
    assert kinds == {"tombstone"}


def test_record_tombstone_idempotent_per_asset(conn):
    record_tombstone(conn, asset_id="a1", reason="first")
    op2 = record_tombstone(conn, asset_id="a1", reason="second")
    rows = conn.execute(
        "SELECT * FROM sync_tombstones WHERE asset_id='a1'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["op_id"] == op2


# ─── Migration DB antérieure ─────────────────────────────────────────────────


def test_boot_migrates_pre_sync_db(tmp_path):
    """Une DB qui a image_state_events SANS les colonnes sync boote et migre.

    Simulée en dégradant une DB réelle : DROP des colonnes/index/tables sync
    (l'état exact d'une base d'avant le chantier local-sync).
    """
    db = tmp_path / "old.db"
    store = Store(db)
    c = store._connection()  # noqa: SLF001
    _seed_asset(c, asset_id="legacy")
    c.execute(
        "INSERT INTO image_state_events (asset_id, to_state, actor) "
        "VALUES ('legacy', 'detected', 'pipeline')"
    )
    c.close()
    raw = sqlite3.connect(db)
    raw.executescript(
        """
        PRAGMA foreign_keys=OFF;
        DROP INDEX IF EXISTS idx_ise_op_id;
        DROP INDEX IF EXISTS idx_ise_hlc;
        CREATE TABLE ise_old (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          asset_id TEXT NOT NULL REFERENCES image_assets(id) ON DELETE CASCADE,
          from_state TEXT, to_state TEXT NOT NULL, actor TEXT NOT NULL,
          reason TEXT, eurio_id TEXT, target_eurio_id TEXT, run_id TEXT,
          detail_json TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO ise_old (id, asset_id, from_state, to_state, actor, reason,
                             eurio_id, target_eurio_id, run_id, detail_json, created_at)
          SELECT id, asset_id, from_state, to_state, actor, reason,
                 eurio_id, target_eurio_id, run_id, detail_json, created_at
          FROM image_state_events;
        DROP TABLE image_state_events;
        ALTER TABLE ise_old RENAME TO image_state_events;
        DROP TABLE IF EXISTS sync_outbox;
        DROP TABLE IF EXISTS sync_tombstones;
        DROP TABLE IF EXISTS sync_state;
        """
    )
    raw.close()
    store = Store(db)
    c = store._connection()  # noqa: SLF001
    cols = {r[1] for r in c.execute("PRAGMA table_info(image_state_events)")}
    assert {"op_id", "machine", "hlc"} <= cols
    legacy = c.execute(
        "SELECT op_id, hlc FROM image_state_events WHERE asset_id='legacy'"
    ).fetchone()
    assert legacy["op_id"] is None and legacy["hlc"] is None  # jamais rétro-stampé
    for table in ("sync_outbox", "sync_tombstones", "sync_state"):
        assert c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone(), table
