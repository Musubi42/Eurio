"""C2a — filet de parité de l'extraction `store.decisions`.

Teste directement les helpers SQL-purs (source unique partagée local ↔ lean) :
apply_accept_training / apply_reopen_review / apply_set_training_eligible /
apply_reassign / apply_lot_decide. Prouve que la logique extraite de
`lab_routes`/`review_queue_routes` produit l'état attendu (image_assets +
review_queue + image_state_events).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from store import Store
from store.decisions import (
    DecisionError,
    apply_accept_training,
    apply_lot_decide,
    apply_reassign,
    apply_reopen_review,
    apply_set_training_eligible,
)


def _coin(conn, eurio_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO coins (eurio_id, country, year, face_value) "
        "VALUES (?, 'FR', 2001, 2.0)",
        (eurio_id,),
    )


def _seed_asset(conn, asset_id="a1", eurio_id="fr-2001-2eur-x",
                status="needs_review", training=0, rq_status="open",
                ebay_item=None, si_id=None, crop_index=0) -> str:
    conn.execute(
        "INSERT OR IGNORE INTO source_runs (id, source, kind) VALUES ('r1','ebay','run')"
    )
    _coin(conn, eurio_id)
    si_id = si_id or f"si_{asset_id}"
    raw = json.dumps({"ebay_item_id": ebay_item}) if ebay_item else None
    conn.execute(
        "INSERT OR IGNORE INTO source_images (id, source, source_ref, run_id, raw_payload_json) "
        "VALUES (?, 'ebay', ?, 'r1', ?)",
        (si_id, f"ref_{si_id}", raw),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, run_id, crop_index, "
        "storage_path, eurio_id, face, resolution_status, training_eligible) "
        "VALUES (?, ?, 'r1', ?, ?, ?, 'obverse', ?, ?)",
        (asset_id, si_id, crop_index, f"ebay/{asset_id}.png", eurio_id, status, training),
    )
    conn.execute(
        "INSERT INTO image_state_current (asset_id, current_state) VALUES (?, 'queued')",
        (asset_id,),
    )
    if rq_status:
        conn.execute(
            "INSERT INTO review_queue (id, image_asset_id, status, priority, "
            "enqueued_at, kind, lane, lane_source) "
            "VALUES (?, ?, ?, 100, '2026-01-01T00:00:00Z', 'single', 'manual', 'human')",
            (f"rq_{asset_id}", asset_id, rq_status),
        )
    return asset_id


@pytest.fixture()
def conn(tmp_path):
    return Store(tmp_path / "t.db")._connection()  # noqa: SLF001


def _row(conn, asset_id):
    return conn.execute(
        "SELECT resolution_status, training_eligible, quality_reason, eurio_id, "
        "resolved_at FROM image_assets WHERE id = ?", (asset_id,),
    ).fetchone()


def test_accept_training(conn):
    _seed_asset(conn, "a1", eurio_id="fr-2001-2eur-x")
    out = apply_accept_training(conn, "a1")
    r = _row(conn, "a1")
    assert r["resolution_status"] == "manual"
    assert r["training_eligible"] == 1
    assert r["resolved_at"] is not None
    assert out["training_eligible"] is True
    rq = conn.execute("SELECT status, decided_by FROM review_queue WHERE image_asset_id='a1'").fetchone()
    assert rq["status"] == "done" and rq["decided_by"] == "human"
    ev = conn.execute(
        "SELECT reason FROM image_state_events WHERE asset_id='a1' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert ev["reason"] == "accepted_from_training_set"


def test_reopen_review(conn):
    _seed_asset(conn, "a2", status="manual", training=1, rq_status="done")
    out = apply_reopen_review(conn, "a2")
    r = _row(conn, "a2")
    assert r["resolution_status"] == "needs_review"
    assert r["training_eligible"] == 0
    assert r["resolved_at"] is None
    rq = conn.execute("SELECT status, lane FROM review_queue WHERE image_asset_id='a2'").fetchone()
    assert rq["status"] == "open" and rq["lane"] == "manual"
    assert out["review_id"] == "rq_a2"  # UPSERT garde l'id existant


def test_set_training_eligible_toggle(conn):
    _seed_asset(conn, "a3", training=1)
    apply_set_training_eligible(conn, "a3", False)
    r = _row(conn, "a3")
    assert r["training_eligible"] == 0 and r["quality_reason"] == "manual_triage"
    apply_set_training_eligible(conn, "a3", True)
    r = _row(conn, "a3")
    assert r["training_eligible"] == 1 and r["quality_reason"] is None


def test_reassign(conn):
    _seed_asset(conn, "a4", eurio_id="fr-2001-2eur-x")
    _coin(conn, "fr-2002-2eur-y")
    out = apply_reassign(conn, "a4", "fr-2002-2eur-y")
    assert _row(conn, "a4")["eurio_id"] == "fr-2002-2eur-y"
    assert out["previous_eurio_id"] == "fr-2001-2eur-x"


def test_reassign_errors(conn):
    _seed_asset(conn, "a5")
    with pytest.raises(DecisionError) as e1:
        apply_reassign(conn, "a5", "  ")
    assert e1.value.status_code == 422
    with pytest.raises(DecisionError) as e2:
        apply_reassign(conn, "a5", "coin-does-not-exist")
    assert e2.value.status_code == 404
    with pytest.raises(DecisionError) as e3:
        apply_accept_training(conn, "nope")
    assert e3.value.status_code == 404


def test_lot_decide(conn):
    # 3 crops sur un même listing eBay (item 55).
    for i in range(3):
        _seed_asset(conn, f"L{i}", eurio_id="fr-2001-2eur-x", ebay_item="55",
                    si_id="si_lot", crop_index=i)
    _coin(conn, "fr-2003-2eur-z")

    class A:
        def __init__(self, **k):
            self.asset_id = k["asset_id"]
            self.eurio_id = k.get("eurio_id")
            self.face = k.get("face")
            self.variant_kind = k.get("variant_kind")
            self.reject_reason = k.get("reject_reason")
            self.skip = k.get("skip", False)

    out = apply_lot_decide(conn, "ebay_55", [
        A(asset_id="L0", eurio_id="fr-2003-2eur-z", face="obverse"),
        A(asset_id="L1", reject_reason="not_a_coin"),
        A(asset_id="L2", skip=True),
    ])
    assert out == {"done": 1, "rejected": 1, "skipped": 1, "errors": []}
    assert _row(conn, "L0")["resolution_status"] == "manual"
    assert _row(conn, "L0")["eurio_id"] == "fr-2003-2eur-z"
    assert _row(conn, "L1")["resolution_status"] == "rejected"
    assert conn.execute("SELECT status FROM review_queue WHERE image_asset_id='L2'").fetchone()["status"] == "skipped"


def test_lot_decide_refus_porte_son_asset_et_n_ecrit_rien(conn):
    """Le refus du serveur est la seule trace d'une décision perdue.

    Une row déjà `done` ne se réécrit pas : l'humain a tranché, rien n'est
    écrit, et `done` reste à 0. L'entrée d'`errors` doit désigner l'asset —
    sinon l'écran ne peut ni le dire ni rendre la décision à rejouer.
    """
    _seed_asset(conn, "D0", ebay_item="77", si_id="si_d", crop_index=0,
                rq_status="done")
    _seed_asset(conn, "D1", ebay_item="77", si_id="si_d", crop_index=1)
    _coin(conn, "fr-2003-2eur-z")

    class A:
        def __init__(self, **k):
            self.asset_id = k["asset_id"]
            self.eurio_id = k.get("eurio_id")
            self.face = k.get("face")
            self.variant_kind = k.get("variant_kind")
            self.reject_reason = k.get("reject_reason")
            self.skip = k.get("skip", False)

    avant = _row(conn, "D0")["eurio_id"]
    out = apply_lot_decide(conn, "ebay_77", [
        A(asset_id="D0", eurio_id="fr-2003-2eur-z", face="obverse"),
        A(asset_id="D1", eurio_id="fr-2003-2eur-z", face="obverse"),
    ])

    assert out["done"] == 1, "seul le crop encore ouvert doit être écrit"
    assert [e["asset_id"] for e in out["errors"]] == ["D0"]
    assert "déjà done" in out["errors"][0]["message"]
    # Et la row close n'a pas bougé : le refus n'est pas un demi-succès.
    assert _row(conn, "D0")["eurio_id"] == avant


def test_lot_decide_unknown_listing(conn):
    with pytest.raises(DecisionError) as e:
        apply_lot_decide(conn, "ebay_does_not_exist", [type("A", (), {"asset_id": "x", "eurio_id": None, "face": None, "variant_kind": None, "reject_reason": None, "skip": True})()])
    assert e.value.status_code == 404


def test_lot_decide_empty(conn):
    assert apply_lot_decide(conn, "whatever", []) == {"done": 0, "rejected": 0, "skipped": 0, "errors": []}
