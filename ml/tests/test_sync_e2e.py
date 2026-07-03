"""Tests e2e local-sync (C5/C8) — Mac ‖ PC ↔ « VPS » in-process.

Trois Stores réels ; le « VPS » est le vrai router ``sync_routes`` monté sur un
TestClient, et ``client.sync`` y est raccordé en monkeypatchant la couche HTTP.
Couvre : aller-retour complet (Mac → VPS → PC), concurrence cas 3 croisée,
offline → rattrapage, rétention (marge d'un cycle), tombstone bout-en-bout,
pas de double-livraison run-batch + sync.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store, emit_field_event, emit_state_event, record_tombstone  # noqa: E402


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


class _Node:
    """Une machine (Store + machine_id forcé par env au moment des writes)."""

    def __init__(self, tmp_path, name):
        self.name = name
        self.store = Store(tmp_path / f"{name}.db")
        self.conn = self.store._connection()  # noqa: SLF001


@pytest.fixture()
def net(tmp_path, monkeypatch):
    """(mac, pc, vps_conn) raccordés : client.http → TestClient du VPS."""
    from serving import sync_routes

    monkeypatch.setenv("EURIO_API_URL", "http://vps.test")
    monkeypatch.delenv("EURIO_SYNC_MODE", raising=False)
    monkeypatch.delenv("EURIO_MACHINE_ID", raising=False)

    vps_store = Store(tmp_path / "vps.db")
    vps_conn = vps_store._connection()  # noqa: SLF001
    _seed(vps_conn, ("a1", "a2"))
    vps_conn.execute(
        "INSERT INTO sync_state (key, value) VALUES ('machine_id', 'vps')"
    )

    app = FastAPI()
    sync_routes.bind(vps_store)
    app.include_router(sync_routes.router)
    for route in app.routes:
        if hasattr(route, "dependant"):
            for d in route.dependant.dependencies:
                app.dependency_overrides[d.call] = lambda: None
    vps_client = TestClient(app)

    import client.http as _http

    def fake_post(path, payload, **kw):
        # Le VPS applique en mode hub (stampe sans outbox).
        import os
        os.environ["EURIO_SYNC_MODE"] = "hub"
        os.environ["EURIO_MACHINE_ID"] = "vps"
        try:
            r = vps_client.post(path, json=payload)
        finally:
            os.environ.pop("EURIO_SYNC_MODE", None)
            os.environ.pop("EURIO_MACHINE_ID", None)
        assert r.status_code == 200, r.text
        return r.json()

    def fake_get(path, **kw):
        r = vps_client.get(path)
        assert r.status_code == 200, r.text
        return r.json()

    monkeypatch.setattr(_http, "post_json", fake_post)
    monkeypatch.setattr(_http, "get_json", fake_get)
    # client.sync importe `from . import http as _http` → même module, patché.

    mac = _Node(tmp_path, "mac")
    _seed(mac.conn, ("a1", "a2"))
    mac.conn.execute("INSERT INTO sync_state (key, value) VALUES ('machine_id', 'mac')")
    pc = _Node(tmp_path, "pc")
    _seed(pc.conn, ("a1", "a2"))
    pc.conn.execute("INSERT INTO sync_state (key, value) VALUES ('machine_id', 'pc')")
    return mac, pc, vps_conn


def _cycle(node):
    from client.sync import run_sync_cycle
    return run_sync_cycle(node.conn)


def test_roundtrip_mac_to_vps_to_pc(net):
    mac, pc, vps_conn = net
    emit_field_event(
        mac.conn, asset_id="a1", reason="training_eligible",
        fields={"image_assets.training_eligible": 0,
                "image_assets.quality_reason": "manual_triage"},
    )
    r1 = _cycle(mac)
    assert r1.ok and r1.pushed == 1

    row = vps_conn.execute(
        "SELECT training_eligible, quality_reason FROM image_assets WHERE id='a1'"
    ).fetchone()
    assert row["training_eligible"] == 0 and row["quality_reason"] == "manual_triage"

    r2 = _cycle(pc)
    assert r2.ok and r2.pulled_events == 1
    row = pc.conn.execute(
        "SELECT training_eligible FROM image_assets WHERE id='a1'"
    ).fetchone()
    assert row["training_eligible"] == 0
    # Pas d'écho : le PC n'a rien mis dans son outbox en recevant.
    assert pc.conn.execute(
        "SELECT COUNT(*) FROM sync_outbox WHERE status='pending'"
    ).fetchone()[0] == 0


def _decide(conn, asset_id, eligible):
    """Simule l'endpoint : UPDATE local + event (comme lab_routes)."""
    conn.execute(
        "UPDATE image_assets SET training_eligible=? WHERE id=?",
        (eligible, asset_id),
    )
    emit_field_event(
        conn, asset_id=asset_id, reason="training_eligible",
        fields={"image_assets.training_eligible": eligible},
    )


def test_case3_cross_machine_last_hlc_wins_everywhere(net):
    mac, pc, vps_conn = net
    _decide(mac.conn, "a1", 1)
    # Le PC décide APRÈS avoir pullé (hlc mergé → supérieur) — scénario réel
    # « je corrige après avoir vu la décision de l'autre machine ».
    _cycle(mac)
    _cycle(pc)  # le pc a maintenant vu l'event mac
    _decide(pc.conn, "a1", 0)
    _cycle(pc)
    _cycle(mac)
    for name, conn in (("mac", mac.conn), ("pc", pc.conn), ("vps", vps_conn)):
        val = conn.execute(
            "SELECT training_eligible FROM image_assets WHERE id='a1'"
        ).fetchone()[0]
        assert val == 0, f"{name} devrait avoir la décision la plus récente"


def test_offline_then_catchup(net, monkeypatch):
    mac, pc, vps_conn = net
    emit_field_event(
        mac.conn, asset_id="a2", reason="reassign",
        fields={"image_assets.eurio_id": "de-2019-y"},
    )
    import client.http as _http
    real_post = _http.post_json

    def down(*a, **kw):
        raise OSError("network unreachable")

    monkeypatch.setattr(_http, "post_json", down)
    r = _cycle(mac)
    assert not r.ok and "unreachable" in (r.error or "")
    # L'op reste pending (rien de perdu).
    assert mac.conn.execute(
        "SELECT COUNT(*) FROM sync_outbox WHERE status='pending'"
    ).fetchone()[0] == 1

    monkeypatch.setattr(_http, "post_json", real_post)
    r = _cycle(mac)
    assert r.ok and r.pushed == 1
    assert vps_conn.execute(
        "SELECT eurio_id FROM image_assets WHERE id='a2'"
    ).fetchone()[0] == "de-2019-y"


def test_retention_one_cycle_margin(net):
    mac, _pc, _vps = net
    emit_field_event(
        mac.conn, asset_id="a1", reason="training_eligible",
        fields={"image_assets.training_eligible": 0},
    )
    r1 = _cycle(mac)
    assert r1.ok and r1.purged == 0  # pushed pendant CE cycle → survit
    assert mac.conn.execute(
        "SELECT COUNT(*) FROM sync_outbox WHERE status='pushed'"
    ).fetchone()[0] == 1
    # Cycle suivant (fictivement plus tard : on vieillit pushed_at).
    mac.conn.execute(
        "UPDATE sync_outbox SET pushed_at = datetime('now', '-1 hour')"
    )
    r2 = _cycle(mac)
    assert r2.ok and r2.purged == 1
    assert mac.conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == 0
    # Le log d'audit, lui, n'est jamais purgé.
    assert mac.conn.execute(
        "SELECT COUNT(*) FROM image_state_events"
    ).fetchone()[0] == 1


def test_tombstone_end_to_end(net, monkeypatch):
    mac, pc, vps_conn = net
    monkeypatch.setenv("EURIO_MACHINE_ID", "mac")
    record_tombstone(
        mac.conn, asset_id="a2", storage_path="crops/a2.png", reason="manual_delete",
    )
    monkeypatch.delenv("EURIO_MACHINE_ID")
    mac.conn.execute("DELETE FROM image_assets WHERE id='a2'")
    r = _cycle(mac)
    assert r.ok and r.pushed == 1
    assert vps_conn.execute(
        "SELECT COUNT(*) FROM image_assets WHERE id='a2'"
    ).fetchone()[0] == 0
    _cycle(pc)
    assert pc.conn.execute(
        "SELECT COUNT(*) FROM image_assets WHERE id='a2'"
    ).fetchone()[0] == 0
    assert pc.conn.execute(
        "SELECT COUNT(*) FROM sync_tombstones WHERE asset_id='a2'"
    ).fetchone()[0] == 1


def test_orphan_stays_pending_until_asset_known(net):
    """Décision locale sur un asset que le VPS ne connaît pas encore (run pas
    ingéré) : l'op reste pending côté client, repartira plus tard."""
    mac, _pc, vps_conn = net
    mac.conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, storage_path) "
        "VALUES ('local-only', 'si1', 7, 'crops/lo.png')"
    )
    emit_field_event(
        mac.conn, asset_id="local-only", reason="training_eligible",
        fields={"image_assets.training_eligible": 0},
    )
    r = _cycle(mac)
    assert r.ok and r.pushed == 0 and r.remote_orphaned == 1
    assert mac.conn.execute(
        "SELECT COUNT(*) FROM sync_outbox WHERE status='pending'"
    ).fetchone()[0] == 1
    # L'asset arrive côté VPS (ingest run simulé) → le cycle suivant aboutit.
    vps_conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, storage_path) "
        "VALUES ('local-only', 'si1', 7, 'crops/lo.png')"
    )
    r2 = _cycle(mac)
    assert r2.ok and r2.pushed == 1
    # L'orphelin parké côté VPS a été rejoué par l'apply du push.
    assert vps_conn.execute(
        "SELECT training_eligible FROM image_assets WHERE id='local-only'"
    ).fetchone()[0] == 0


def test_vps_review_write_flows_down(net, monkeypatch):
    """Le VPS est aussi un writer (review lean) : ses events descendent au pull."""
    mac, _pc, vps_conn = net
    monkeypatch.setenv("EURIO_SYNC_MODE", "hub")
    monkeypatch.setenv("EURIO_MACHINE_ID", "vps")
    emit_state_event(
        vps_conn, asset_id="a1", to_state="rejected", actor="human",
        reason="rejected",
        detail_fields={
            "image_assets.resolution_status": "rejected",
            "image_assets.training_eligible": 0,
        },
    )
    monkeypatch.delenv("EURIO_SYNC_MODE")
    monkeypatch.delenv("EURIO_MACHINE_ID")
    assert vps_conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == 0

    r = _cycle(mac)
    assert r.ok and r.pulled_events == 1
    row = mac.conn.execute(
        "SELECT resolution_status, training_eligible FROM image_assets WHERE id='a1'"
    ).fetchone()
    assert row["resolution_status"] == "rejected" and row["training_eligible"] == 0
