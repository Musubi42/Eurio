"""Tests pour compute_run_breakdown (ml/api/sources_routes.py).

Modèle (cf. docs/sources-refacto/run-breakdown-kickoff.md) :
- Un seul bloc `per_eurio`, was_targeted=True d'abord puis discovered.
- Pour chaque eurio_id E, deux axes strictement disjoints :
  - Search axis (si.target_eurio_id = E) → n_listings + n_crops_searched
    partitionnés en n_searched_{auto,review_single,review_lot,pending,rejected}.
  - Attribution axis (ia.eurio_id = E AND si.target_eurio_id != E) →
    n_attributed_from_other + via_lot.

Couvre 7 cas :
- 404 si run inconnu
- ciblés vides (les targets remontent avec n_listings=0)
- ciblés auto-résolus + 1 quote
- ciblés en review (single + lot) — exclus de pending
- ciblés en pending sans review_queue
- ciblés rejected
- bonus via lot (eurio non ciblé résolu depuis un listing autre)
- run dry sans filtres → tout en discovered, pas de targeted
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api.sources_routes import compute_run_breakdown
from sources._base.run_logger import start_run
from state import Store


# ── Helpers ───────────────────────────────────────────────────────────────


def _seed_source_image(
    conn, *, sid: str, run_id: str,
    source: str = "ebay",
    source_ref: str | None = None,
    target_eurio_id: str | None = None,
    is_lot_suspected: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, target_eurio_id,
          storage_path, license, is_lot_suspected, run_id
        ) VALUES (?, ?, ?, ?, '/tmp/x.jpg', 'fair_use_research', ?, ?)
        """,
        (sid, source, source_ref or f"{source}_{sid}",
         target_eurio_id, int(is_lot_suspected), run_id),
    )


def _seed_image_asset(
    conn, *, sid: str, source_image_id: str, run_id: str,
    eurio_id: str | None = None,
    resolution_status: str = "pending_match",
    crop_index: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO image_assets (
          id, source_image_id, crop_index, storage_path, resolution_status,
          variant_kind, eurio_id, run_id
        ) VALUES (?, ?, ?, '/tmp/a.png', ?, 'auction_listing', ?, ?)
        """,
        (sid, source_image_id, crop_index, resolution_status, eurio_id, run_id),
    )


def _seed_review(
    conn, *, asset_id: str, kind: str = "single", status: str = "open",
) -> None:
    conn.execute(
        """
        INSERT INTO review_queue (id, image_asset_id, priority, kind, status)
        VALUES (?, ?, 100, ?, ?)
        """,
        (uuid.uuid4().hex, asset_id, kind, status),
    )


def _seed_quote(
    conn, *, eurio_id: str, run_id: str, source: str = "ebay",
) -> None:
    conn.execute(
        """
        INSERT INTO coin_market_quotes (
          id, eurio_id, source, condition_normalized, currency,
          period_start, period_end, run_id
        ) VALUES (?, ?, ?, 'unknown', 'EUR',
                  '2026-05-01', '2026-05-31', ?)
        """,
        (uuid.uuid4().hex, eurio_id, source, run_id),
    )


@pytest.fixture()
def store_run(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    with start_run(
        conn, source="ebay", kind="run",
        filters={"target_eurio_ids": ["eid-A", "eid-B"]},
        force=True,
    ) as run:
        yield store, conn, run


# ── Tests ─────────────────────────────────────────────────────────────────


def test_breakdown_404_when_run_missing(store_run):
    _, conn, _ = store_run
    with pytest.raises(HTTPException) as exc:
        compute_run_breakdown(conn, run_id="ghost", source_id="ebay")
    assert exc.value.status_code == 404


def test_breakdown_lists_targets_with_zero_listings(store_run):
    """Run avec 2 cibles et 0 listing trouvé → les 2 cibles apparaissent
    avec was_targeted=True et tous les compteurs à 0."""
    _, conn, run = store_run
    bd = compute_run_breakdown(conn, run_id=run.run_id, source_id="ebay")
    assert [e.eurio_id for e in bd.per_eurio] == ["eid-A", "eid-B"]
    for e in bd.per_eurio:
        assert e.was_targeted is True
        assert e.n_listings == 0
        assert e.n_crops_searched == 0
        assert e.n_searched_auto == 0
        assert e.n_searched_review_single == 0
        assert e.n_searched_review_lot == 0
        assert e.n_searched_pending == 0
        assert e.n_searched_rejected == 0
        assert e.n_attributed_from_other == 0
        assert e.via_lot is False
        assert e.n_quotes == 0


def test_breakdown_targeted_with_auto_and_quote(store_run):
    """eid-A : 2 listings, 3 crops dont 2 auto_phash + 1 pending + 1 quote."""
    _, conn, run = store_run
    _seed_source_image(conn, sid="S1", run_id=run.run_id,
                       source_ref="ebay_L1_img0", target_eurio_id="eid-A")
    _seed_source_image(conn, sid="S2", run_id=run.run_id,
                       source_ref="ebay_L2_img0", target_eurio_id="eid-A")
    _seed_image_asset(conn, sid="A1", source_image_id="S1", run_id=run.run_id,
                      eurio_id="eid-A", resolution_status="auto_phash")
    _seed_image_asset(conn, sid="A2", source_image_id="S2", run_id=run.run_id,
                      eurio_id="eid-A", resolution_status="auto_phash")
    _seed_image_asset(conn, sid="A3", source_image_id="S2", run_id=run.run_id,
                      crop_index=1, resolution_status="pending_match")
    _seed_quote(conn, eurio_id="eid-A", run_id=run.run_id)

    bd = compute_run_breakdown(conn, run_id=run.run_id, source_id="ebay")
    a = next(e for e in bd.per_eurio if e.eurio_id == "eid-A")
    assert a.n_listings == 2
    assert a.n_crops_searched == 3
    assert a.n_searched_auto == 2
    assert a.n_searched_pending == 1
    assert a.n_searched_review_single == 0
    assert a.n_searched_review_lot == 0
    assert a.n_searched_rejected == 0
    assert a.n_attributed_from_other == 0
    assert a.n_quotes == 1
    # Partition exhaustive : sum = n_crops_searched
    assert (a.n_searched_auto + a.n_searched_review_single
            + a.n_searched_review_lot + a.n_searched_pending
            + a.n_searched_rejected) == a.n_crops_searched


def test_breakdown_targeted_with_review_excluded_from_pending(store_run):
    """Crop en needs_review + row dans review_queue → compté dans
    n_searched_review_*, pas dans n_searched_pending. Partition reste
    exhaustive."""
    _, conn, run = store_run
    _seed_source_image(conn, sid="S1", run_id=run.run_id,
                       source_ref="ebay_L1_img0", target_eurio_id="eid-A")
    _seed_image_asset(conn, sid="A1", source_image_id="S1", run_id=run.run_id,
                      resolution_status="needs_review")
    _seed_image_asset(conn, sid="A2", source_image_id="S1", run_id=run.run_id,
                      crop_index=1, resolution_status="needs_review")
    _seed_image_asset(conn, sid="A3", source_image_id="S1", run_id=run.run_id,
                      crop_index=2, resolution_status="needs_review")
    _seed_review(conn, asset_id="A1", kind="single")
    _seed_review(conn, asset_id="A2", kind="lot")
    # A3 reste needs_review mais pas dans review_queue → pending

    bd = compute_run_breakdown(conn, run_id=run.run_id, source_id="ebay")
    a = next(e for e in bd.per_eurio if e.eurio_id == "eid-A")
    assert a.n_crops_searched == 3
    assert a.n_searched_review_single == 1
    assert a.n_searched_review_lot == 1
    assert a.n_searched_pending == 1
    assert a.n_searched_rejected == 0
    assert a.n_searched_auto == 0
    assert (a.n_searched_auto + a.n_searched_review_single
            + a.n_searched_review_lot + a.n_searched_pending
            + a.n_searched_rejected) == a.n_crops_searched


def test_breakdown_targeted_with_rejected(store_run):
    """eid-A : 1 listing, 2 crops dont 1 rejected."""
    _, conn, run = store_run
    _seed_source_image(conn, sid="S1", run_id=run.run_id,
                       source_ref="ebay_L1_img0", target_eurio_id="eid-A")
    _seed_image_asset(conn, sid="A1", source_image_id="S1", run_id=run.run_id,
                      eurio_id="eid-A", resolution_status="auto_phash")
    _seed_image_asset(conn, sid="A2", source_image_id="S1", run_id=run.run_id,
                      crop_index=1, resolution_status="rejected")

    bd = compute_run_breakdown(conn, run_id=run.run_id, source_id="ebay")
    a = next(e for e in bd.per_eurio if e.eurio_id == "eid-A")
    assert a.n_crops_searched == 2
    assert a.n_searched_auto == 1
    assert a.n_searched_rejected == 1
    assert a.n_searched_pending == 0


def test_breakdown_attribution_axis_via_lot(store_run):
    """Listing cherché pour eid-A, suspect lot. 2 crops résolus à eid-B
    (ciblé) et eid-Z (non ciblé). Sémantique disjointe :
    - eid-A : n_listings=1, n_crops_searched=2, tous comptés en auto
      (puisque auto_phash). n_attributed_from_other=0.
    - eid-B : n_listings=0 (jamais cherché). n_crops_searched=0.
      n_attributed_from_other=1 (1 crop résolu à eid-B depuis listing
      cherché pour eid-A). via_lot=True.
    - eid-Z : was_targeted=False, n_attributed_from_other=1, via_lot=True.
    """
    _, conn, run = store_run
    _seed_source_image(conn, sid="S1", run_id=run.run_id,
                       source_ref="ebay_L1_img0", target_eurio_id="eid-A",
                       is_lot_suspected=True)
    _seed_image_asset(conn, sid="A1", source_image_id="S1", run_id=run.run_id,
                      eurio_id="eid-B", resolution_status="auto_phash")
    _seed_image_asset(conn, sid="A2", source_image_id="S1", run_id=run.run_id,
                      crop_index=1, eurio_id="eid-Z",
                      resolution_status="auto_phash")

    bd = compute_run_breakdown(conn, run_id=run.run_id, source_id="ebay")
    a = next(e for e in bd.per_eurio if e.eurio_id == "eid-A")
    assert a.n_listings == 1
    assert a.n_crops_searched == 2
    assert a.n_searched_auto == 2  # (les crops sont auto, peu importe vers qui)
    assert a.n_attributed_from_other == 0
    # via_lot calculé sur les deux axes : eid-A a cherché un listing
    # is_lot_suspected → flag=True même si l'attribution axis est vide.
    assert a.via_lot is True

    b = next(e for e in bd.per_eurio if e.eurio_id == "eid-B")
    assert b.was_targeted is True
    assert b.n_listings == 0
    assert b.n_crops_searched == 0
    assert b.n_attributed_from_other == 1
    assert b.via_lot is True

    z = next(e for e in bd.per_eurio if e.eurio_id == "eid-Z")
    assert z.was_targeted is False
    assert z.n_listings == 0
    assert z.n_attributed_from_other == 1
    assert z.via_lot is True


def test_breakdown_dry_run_no_filters(tmp_path):
    """Run sans target_eurio_ids → 0 ciblés, 1 discovered."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    with start_run(conn, source="ebay", kind="dry", filters={}, force=True) as run:
        _seed_source_image(conn, sid="S1", run_id=run.run_id,
                           source_ref="ebay_L1_img0", target_eurio_id=None)
        _seed_image_asset(conn, sid="A1", source_image_id="S1", run_id=run.run_id,
                          eurio_id="eid-X", resolution_status="auto_phash")

        bd = compute_run_breakdown(conn, run_id=run.run_id, source_id="ebay")
        assert all(e.was_targeted is False for e in bd.per_eurio)
        assert len(bd.per_eurio) == 1
        x = bd.per_eurio[0]
        assert x.eurio_id == "eid-X"
        assert x.n_attributed_from_other == 1
        assert x.via_lot is False  # 1 seul crop, pas de lot
        assert x.n_listings == 0
        assert x.n_crops_searched == 0


def test_breakdown_grouped_run_targets_group_coins(tmp_path):
    """Run en découverte groupée : « ciblé » = toutes les commémos des
    groupes (denom, pays, année) — même celles sans listing."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    for i in range(2):
        conn.execute(
            "INSERT INTO coins (eurio_id, country, country_name, year, face_value, "
            "is_commemorative, theme, raw_payload_json) VALUES (?,?,?,?,?,?,?,'{}')",
            (f"be-2099-2eur-sib-{i}", "BE", "Belgique", 2099, 2.0, 1, f"t{i}"),
        )
    with start_run(
        conn, source="ebay", kind="run",
        filters={"discovery_groups": [
            {"denomination": 2.0, "country": "BE", "year": 2099},
        ]},
        force=True,
    ) as run:
        bd = compute_run_breakdown(conn, run_id=run.run_id, source_id="ebay")

    assert [e.eurio_id for e in bd.per_eurio] == [
        "be-2099-2eur-sib-0", "be-2099-2eur-sib-1",
    ]
    assert all(e.was_targeted for e in bd.per_eurio)
