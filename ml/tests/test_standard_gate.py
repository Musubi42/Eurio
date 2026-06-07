"""Tests du gate vision standard : classification + chemin de rejet réversible."""

from __future__ import annotations

from pathlib import Path

import foundation.standard_gate_review as sgr
from ccproxy_client import ChatResult
from scripts.gate_standard_vision import _reject
from state.store import Store


# --- classify_crop (chat mocké) ---

def _patch(monkeypatch, *, content=None, exc=None):
    def fake_chat(**kw):
        if exc:
            raise exc
        return ChatResult(content=content, model="m", tokens_in=1, tokens_out=1,
                          cache_creation_tokens=0, cache_read_tokens=0,
                          cost_usd=0.001, duration_ms=1)
    monkeypatch.setattr(sgr, "chat", fake_chat)
    monkeypatch.setattr(sgr, "image_part", lambda p: {"image": str(p)})


_CANON = [Path("c1.jpg")]


def test_classify_correct(monkeypatch):
    _patch(monkeypatch, content='{"label":"correct","confidence":0.95}')
    v = sgr.classify_crop(canonical_paths=_CANON, crop_path=Path("x.jpg"),
                          group_label="g", year_range="1999-2007", listing_title="t")
    assert v.label == "correct" and v.confidence == 0.95 and v.error is None


def test_classify_wrong_coin(monkeypatch):
    _patch(monkeypatch, content='{"label":"wrong_coin","confidence":0.9}')
    v = sgr.classify_crop(canonical_paths=_CANON, crop_path=Path("x.jpg"),
                          group_label="g", year_range="r", listing_title="t")
    assert v.label == "wrong_coin"


def test_classify_no_canonical(monkeypatch):
    _patch(monkeypatch, content='{"label":"correct","confidence":1}')
    v = sgr.classify_crop(canonical_paths=[], crop_path=Path("x.jpg"),
                          group_label="g", year_range="r", listing_title="t")
    assert v.error == "no_canonical"


def test_classify_parse_fail(monkeypatch):
    _patch(monkeypatch, content="not json")
    v = sgr.classify_crop(canonical_paths=_CANON, crop_path=Path("x.jpg"),
                          group_label="g", year_range="r", listing_title="t")
    assert v.error == "parse_fail" and v.label is None


def test_classify_ccproxy_down(monkeypatch):
    _patch(monkeypatch, exc=ConnectionError("refused"))
    v = sgr.classify_crop(canonical_paths=_CANON, crop_path=Path("x.jpg"),
                          group_label="g", year_range="r", listing_title="t")
    assert v.error and "ConnectionError" in v.error


# --- _reject (chemin de rejet réversible) ---

def _seed_open_review(store: Store) -> tuple[str, str]:
    conn = store._connection()
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative) "
        "VALUES ('be-2014-2eur-standard-philippe','BE',2014,2.0,0)"
    )
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id) "
        "VALUES ('si1','ebay','si1','be-2014-2eur-standard-philippe')"
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, storage_path, "
        "resolution_status, training_eligible) VALUES "
        "('ia1','si1',0,'p.png','needs_review',1)"
    )
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status) VALUES ('rq1','ia1','open')"
    )
    return "rq1", "ia1"


def test_reject_marks_rejected_and_closes_review(tmp_path):
    store = Store(tmp_path / "t.db")
    rq, ia = _seed_open_review(store)
    ok = _reject(store._connection(), review_id=rq, asset_id=ia, label="wrong_coin", conf=0.9)
    assert ok
    conn = store._connection()
    asset = conn.execute(
        "SELECT resolution_status, training_eligible, quality_reason FROM image_assets WHERE id=?", (ia,)
    ).fetchone()
    assert asset["resolution_status"] == "rejected"
    assert asset["training_eligible"] == 0
    assert asset["quality_reason"] == "vision_standard_gate"
    review = conn.execute("SELECT status, decided_by FROM review_queue WHERE id=?", (rq,)).fetchone()
    assert review["status"] == "done"
    assert review["decided_by"] == "vision_gate"
    # event d'état tracé
    ev = conn.execute(
        "SELECT to_state, actor FROM image_state_events WHERE asset_id=? ORDER BY id DESC LIMIT 1", (ia,)
    ).fetchone()
    assert ev["to_state"] == "rejected" and ev["actor"] == "ccproxy"


def test_reject_is_idempotent_on_closed_review(tmp_path):
    store = Store(tmp_path / "t.db")
    rq, ia = _seed_open_review(store)
    assert _reject(store._connection(), review_id=rq, asset_id=ia, label="junk", conf=0.9)
    # 2e passe : review déjà 'done' → pas de double rejet
    assert not _reject(store._connection(), review_id=rq, asset_id=ia, label="junk", conf=0.9)
