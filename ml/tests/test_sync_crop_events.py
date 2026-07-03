"""Tests crop_edit — les crops manuels émettent des events d'audit.

recrop en place → event ``manual_recrop`` (colonnes + cache_invalidate) ;
add-crop → snapshot INSERT complet en row_ops ; delete → row + events cascadés
(plus de tombstone/outbox depuis le retrait du transport event-log, C6b —
Direction A pousse au VPS via ``POST /ingest/*``). Couches lourdes (MinIO,
Dino, cascade fichier) mockées — on teste le contrat DB/event, pas le
pipeline image.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import cv2

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
        " storage_path, run_id) VALUES ('si1','ebay','ref1','fr-2018-x', "
        " 'raws/si1.png', NULL)"
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, eurio_id, "
        " resolution_status, storage_status) "
        "VALUES ('a1', 'si1', 'crops/a1.png', 'fr-2018-x', 'manual', 'present')"
    )

    # Raw synthétique : disque clair sur fond sombre (le crop mask y trouve
    # une vraie région) — 400×400, cercle r=100 centré.
    raw = np.zeros((400, 400, 3), dtype=np.uint8)
    cv2.circle(raw, (200, 200), 100, (180, 180, 180), -1)
    raw_p = tmp_path / "raw.png"
    cv2.imwrite(str(raw_p), raw)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    import shared.storage.local_cache as lc
    monkeypatch.setattr(lc, "local_path", lambda bucket, key: raw_p)
    monkeypatch.setattr(
        lc, "cache_path_for", lambda bucket, key: cache_dir / key.replace("/", "_")
    )
    monkeypatch.setattr(lc, "upload_through", lambda bucket, key, data: None)

    import sources._base.steps.auto_validate as av
    monkeypatch.setattr(av, "predict_and_persist_kinds", lambda **kw: {})

    import sources._base.storage as sb_storage
    monkeypatch.setattr(
        sb_storage, "crop_cache_path",
        lambda source, run, aid: cache_dir / f"{source}_{run}_{aid}.png",
    )

    return store, conn


def _last_event(conn, asset_id):
    return conn.execute(
        "SELECT * FROM image_state_events WHERE asset_id=? ORDER BY id DESC LIMIT 1",
        (asset_id,),
    ).fetchone()


def test_apply_manual_crop_emits_replayable_event(env):
    from serving.crop_edit import apply_manual_crop

    store, conn = env
    data = apply_manual_crop(store, "a1", 200.0, 200.0, 100.0)
    assert data.minio_ok

    ev = _last_event(conn, "a1")
    assert ev["reason"] == "manual_recrop"
    body = json.loads(ev["detail_json"])
    assert body["cache_invalidate"] == "crops/a1.png"
    f = body["fields"]
    row = conn.execute(
        "SELECT bbox_json, detection_method, width, height, phash "
        "FROM image_assets WHERE id='a1'"
    ).fetchone()
    assert f["image_assets.bbox_json"] == row["bbox_json"]
    assert f["image_assets.detection_method"] == row["detection_method"] == "manual"
    assert f["image_assets.width"] == row["width"]
    assert f["image_assets.height"] == row["height"]
    assert f["image_assets.phash"] == row["phash"]


def test_create_manual_crop_snapshots_full_row(env):
    from serving.crop_edit import create_manual_crop

    store, conn = env
    data = create_manual_crop(store, "si1", 200.0, 200.0, 100.0)

    detected = conn.execute(
        "SELECT * FROM image_state_events WHERE asset_id=? AND reason='manual_add_crop'",
        (data.asset_id,),
    ).fetchone()
    body = json.loads(detected["detail_json"])
    ops = body["row_ops"]
    assert len(ops) == 1 and ops[0]["op"] == "upsert"
    assert ops[0]["table"] == "image_assets"
    assert ops[0]["key"] == {"id": data.asset_id}
    vals = ops[0]["values"]
    row = conn.execute(
        "SELECT * FROM image_assets WHERE id=?", (data.asset_id,),
    ).fetchone()
    # Le snapshot doit suffire à recréer la row à distance.
    for col in ("source_image_id", "crop_index", "detection_method",
                "resolution_status", "phash", "storage_path", "storage_status",
                "width", "height"):
        assert vals[col] == row[col], col

    queued = conn.execute(
        "SELECT * FROM image_state_events WHERE asset_id=? AND reason='manual_add_enqueued'",
        (data.asset_id,),
    ).fetchone()
    f = json.loads(queued["detail_json"])["fields"]
    rq = conn.execute(
        "SELECT * FROM review_queue WHERE image_asset_id=?", (data.asset_id,),
    ).fetchone()
    assert f["review_queue.status"] == rq["status"] == "open"
    assert f["review_queue.kind"] == rq["kind"]
    assert f["review_queue.lane"] == rq["lane"]
    assert f["review_queue.priority"] == rq["priority"]


def test_delete_crop_purges_row_and_cascades(env, monkeypatch):
    import shared.storage.cascade as cascade
    monkeypatch.setattr(
        cascade, "delete_asset_cascade", lambda *a, **kw: None, raising=False,
    )
    from serving.crop_edit import delete_crop
    from store import emit_state_event

    store, conn = env
    emit_state_event(conn, asset_id="a1", to_state="detected", actor="pipeline")
    delete_crop(store, "a1")

    assert conn.execute(
        "SELECT COUNT(*) FROM image_assets WHERE id='a1'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM image_state_events WHERE asset_id='a1'"
    ).fetchone()[0] == 0  # cascadés
