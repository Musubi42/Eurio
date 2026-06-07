"""Tests pour les endpoints lot review (V1.5) ajoutés dans
ml/api/review_queue_routes.py.

Couvre :
- GET /review-queue : régression du filtre `kind=` (default 'single')
- GET /review-queue/lots : liste groupée par listing_key
- GET /review-queue/lots/{key} : détail
- POST /review-queue/lots/{key}/decide : bulk decide / reject / skip
- Idempotence + validation (asset hors-listing, double décision, etc.)

Cf. docs/sources-refacto/lot-review-kickoff.md §L.A.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from review import review_queue_routes
from review.review_queue_routes import router as review_router
from store import Store


# ── App fixture (avec store override) ─────────────────────────────────────


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """FastAPI app montant le router review-queue, avec un Store sur tmp."""
    store = Store(tmp_path / "t.db")
    monkeypatch.setattr(review_queue_routes, "_store", lambda: store)

    app = FastAPI()
    app.include_router(review_router)
    client = TestClient(app)
    conn = store._connection()
    return store, conn, client


# ── Helpers de seed ───────────────────────────────────────────────────────


def _seed_lot_listing(
    conn,
    *,
    item_id: str = "ITEM_X",
    n_images: int = 2,
    crops_per_image: tuple[int, ...] = (1, 1),
    is_lot_suspected: bool = True,
    target_eurio_id: str | None = "fr-2015-2eur-paix",
    listing_title: str = "Coffret 5 pièces",
    listing_price: float = 25.0,
) -> dict[str, list[str]]:
    """Crée N source_images et leurs crops pour un même eBay item_id.

    Toutes les rows image_assets sont enqueued (kind='lot' status='open').
    Retourne {source_image_id: [asset_id, ...]} pour les assertions.
    """
    assert len(crops_per_image) == n_images
    out: dict[str, list[str]] = {}
    for img_idx in range(n_images):
        si_id = f"SI_{item_id}_{img_idx}"
        conn.execute(
            """
            INSERT INTO source_images (
              id, source, source_ref, target_eurio_id, listing_title,
              listing_price, listing_currency, storage_path, license,
              is_lot_suspected, raw_payload_json
            ) VALUES (?, 'ebay', ?, ?, ?, ?, 'EUR', ?, 'fair_use_research', ?, ?)
            """,
            (
                si_id,
                f"ebay_{item_id}_img{img_idx}",
                target_eurio_id,
                listing_title,
                listing_price,
                f"/tmp/raw_{si_id}.jpg",
                int(is_lot_suspected),
                json.dumps({"image_index": img_idx, "ebay_item_id": item_id}),
            ),
        )
        asset_ids: list[str] = []
        for crop_idx in range(crops_per_image[img_idx]):
            a_id = f"A_{item_id}_{img_idx}_{crop_idx}"
            conn.execute(
                """
                INSERT INTO image_assets (
                  id, source_image_id, crop_index, storage_path,
                  resolution_status, variant_kind, candidate_eurio_ids_json
                ) VALUES (?, ?, ?, ?, 'needs_review', 'auction_listing', ?)
                """,
                (
                    a_id, si_id, crop_idx, f"/tmp/crop_{a_id}.png",
                    json.dumps([{
                        "eurio_id": "fr-2015-2eur-paix",
                        "score": 0.85, "label": "France 2€ Paix 2015",
                        "country": "FR", "denomination": "2eur", "year": 2015,
                    }]),
                ),
            )
            kind = "lot" if (is_lot_suspected or crops_per_image[img_idx] > 1) else "single"
            conn.execute(
                """
                INSERT INTO review_queue (
                  id, image_asset_id, priority, candidate_eurio_ids_json, kind, status
                ) VALUES (?, ?, 100, NULL, ?, 'open')
                """,
                (uuid.uuid4().hex, a_id, kind),
            )
            asset_ids.append(a_id)
        out[si_id] = asset_ids
    return out


def _seed_single_listing(conn, *, sid: str = "SS1") -> str:
    """Crée 1 source_image single-coin, 1 asset, 1 review_queue kind='single'."""
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, target_eurio_id, listing_title,
          listing_price, listing_currency, storage_path, license,
          is_lot_suspected, raw_payload_json
        ) VALUES (?, 'ebay', ?, 'fr-2015-2eur-paix', 'Pièce 2€ FR 2015',
                  10.0, 'EUR', '/tmp/x.jpg', 'fair_use_research', 0, ?)
        """,
        (sid, f"ebay_SINGLE_{sid}_img0", json.dumps({"image_index": 0, "ebay_item_id": f"SINGLE_{sid}"})),
    )
    asset_id = f"A_{sid}"
    conn.execute(
        """
        INSERT INTO image_assets (
          id, source_image_id, crop_index, storage_path, resolution_status, variant_kind
        ) VALUES (?, ?, 0, '/tmp/y.png', 'needs_review', 'auction_listing')
        """,
        (asset_id, sid),
    )
    conn.execute(
        """
        INSERT INTO review_queue (id, image_asset_id, priority, kind, status)
        VALUES (?, ?, 100, 'single', 'open')
        """,
        (uuid.uuid4().hex, asset_id),
    )
    return asset_id


# ── Tests : filtre kind sur GET /review-queue ─────────────────────────────


def test_list_default_filters_to_single(app_client):
    _, conn, client = app_client
    _seed_single_listing(conn, sid="SS1")
    _seed_lot_listing(conn, item_id="LOT1", n_images=1, crops_per_image=(1,))

    resp = client.get("/review-queue")
    assert resp.status_code == 200
    items = resp.json()
    # Seul l'item single doit remonter (default kind=single).
    assert len(items) == 1
    assert items[0]["source_ref"] == "ebay_SINGLE_SS1_img0"


def test_list_kind_lot_filters_to_lots(app_client):
    _, conn, client = app_client
    _seed_single_listing(conn, sid="SS1")
    _seed_lot_listing(conn, item_id="LOT1", n_images=1, crops_per_image=(1,))

    resp = client.get("/review-queue?kind=lot")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["source_ref"].startswith("ebay_LOT1_")


def test_list_kind_all_returns_both(app_client):
    _, conn, client = app_client
    _seed_single_listing(conn, sid="SS1")
    _seed_lot_listing(conn, item_id="LOT1", n_images=1, crops_per_image=(1,))

    resp = client.get("/review-queue?kind=all")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_kind_invalid_returns_422(app_client):
    _, _, client = app_client
    resp = client.get("/review-queue?kind=banana")
    assert resp.status_code == 422


# ── Tests : GET /review-queue/lots ─────────────────────────────────────────


def test_lots_list_empty(app_client):
    _, _, client = app_client
    resp = client.get("/review-queue/lots")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_lots_list_groups_by_item_id(app_client):
    _, conn, client = app_client
    _seed_lot_listing(conn, item_id="A1", n_images=3, crops_per_image=(1, 1, 2))
    _seed_lot_listing(conn, item_id="A2", n_images=1, crops_per_image=(2,))

    resp = client.get("/review-queue/lots")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    keys = {it["listing_key"] for it in body["items"]}
    assert keys == {"ebay_A1", "ebay_A2"}

    a1 = next(it for it in body["items"] if it["listing_key"] == "ebay_A1")
    assert a1["n_images"] == 3
    assert a1["n_crops_in_review"] == 4  # 1+1+2
    assert a1["thumb_url"].startswith("/sources/ebay/raws/")


def test_lots_list_excludes_done_items(app_client):
    _, conn, client = app_client
    seeded = _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(1,))
    asset_id = list(seeded.values())[0][0]
    # Mark the only crop as done
    conn.execute(
        "UPDATE review_queue SET status='done' WHERE image_asset_id=?",
        (asset_id,),
    )
    resp = client.get("/review-queue/lots")
    assert resp.json()["total"] == 0


# ── Tests : GET /review-queue/lots/{listing_key} ───────────────────────────


def test_lot_detail_404(app_client):
    _, _, client = app_client
    resp = client.get("/review-queue/lots/ebay_NOPE")
    assert resp.status_code == 404


def test_lot_detail_returns_images_and_crops(app_client):
    _, conn, client = app_client
    seeded = _seed_lot_listing(conn, item_id="A1", n_images=2, crops_per_image=(1, 2))

    resp = client.get("/review-queue/lots/ebay_A1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["listing_key"] == "ebay_A1"
    assert body["source"] == "ebay"
    assert body["is_lot_suspected"] is True
    assert body["is_multi_crop_single"] is False
    assert len(body["images"]) == 2
    # Image 0 a 1 crop, image 1 a 2 crops
    img0 = next(im for im in body["images"] if im["image_index"] == 0)
    img1 = next(im for im in body["images"] if im["image_index"] == 1)
    assert len(img0["crops"]) == 1
    assert len(img1["crops"]) == 2
    # Vérifie que les URLs sont là
    assert img0["raw_url"].startswith("/sources/ebay/raws/")
    assert img0["crops"][0]["crop_url"].startswith("/sources/ebay/assets/")


def test_lot_detail_flags_multi_crop_single(app_client):
    """Listing pas lot mais ≥1 image multi-crop → is_multi_crop_single=True."""
    _, conn, client = app_client
    _seed_lot_listing(
        conn, item_id="A1", n_images=1, crops_per_image=(2,),
        is_lot_suspected=False,
    )
    resp = client.get("/review-queue/lots/ebay_A1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_lot_suspected"] is False
    assert body["is_multi_crop_single"] is True


# ── Tests : POST /review-queue/lots/{listing_key}/decide ───────────────────


def test_decide_lot_assigns_eurio_id_and_rejects_and_skips(app_client):
    _, conn, client = app_client
    seeded = _seed_lot_listing(conn, item_id="A1", n_images=2, crops_per_image=(1, 2))
    flat = [a for assets in seeded.values() for a in assets]
    assert len(flat) == 3

    resp = client.post(
        "/review-queue/lots/ebay_A1/decide",
        json={
            "assignments": [
                {"asset_id": flat[0], "eurio_id": "fr-2015-2eur-paix", "face": "obverse"},
                {"asset_id": flat[1], "reject_reason": "not_a_coin"},
                {"asset_id": flat[2], "skip": True},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"done": 1, "rejected": 1, "skipped": 1, "errors": []}

    # DB checks
    a0 = conn.execute(
        "SELECT eurio_id, resolution_status, face FROM image_assets WHERE id=?",
        (flat[0],),
    ).fetchone()
    assert a0["eurio_id"] == "fr-2015-2eur-paix"
    assert a0["resolution_status"] == "manual"
    assert a0["face"] == "obverse"

    a1 = conn.execute(
        "SELECT resolution_status FROM image_assets WHERE id=?", (flat[1],),
    ).fetchone()
    assert a1["resolution_status"] == "rejected"

    rq2 = conn.execute(
        "SELECT status FROM review_queue WHERE image_asset_id=?", (flat[2],),
    ).fetchone()
    assert rq2["status"] == "skipped"


def test_decide_lot_rejects_invalid_reason(app_client):
    _, conn, client = app_client
    seeded = _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(1,))
    asset_id = list(seeded.values())[0][0]

    resp = client.post(
        "/review-queue/lots/ebay_A1/decide",
        json={"assignments": [
            {"asset_id": asset_id, "reject_reason": "made_up_reason"},
        ]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["done"] == 0
    assert body["rejected"] == 0
    assert len(body["errors"]) == 1
    assert "made_up_reason" in body["errors"][0]


def test_decide_lot_rejects_asset_not_in_listing(app_client):
    _, conn, client = app_client
    _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(1,))
    other = _seed_lot_listing(conn, item_id="A2", n_images=1, crops_per_image=(1,))
    other_asset = list(other.values())[0][0]

    resp = client.post(
        "/review-queue/lots/ebay_A1/decide",
        json={"assignments": [
            {"asset_id": other_asset, "eurio_id": "fr-2015-2eur-paix", "face": "obverse"},
        ]},
    )
    body = resp.json()
    assert body["done"] == 0
    assert any("does not belong to lot" in e for e in body["errors"])


def test_decide_lot_idempotent_on_already_done(app_client):
    """Re-decide d'un asset déjà 'done' → erreur listée, pas d'écrasement."""
    _, conn, client = app_client
    seeded = _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(1,))
    asset_id = list(seeded.values())[0][0]

    # Première décision OK
    r1 = client.post(
        "/review-queue/lots/ebay_A1/decide",
        json={"assignments": [
            {"asset_id": asset_id, "eurio_id": "fr-2015-2eur-paix", "face": "obverse"},
        ]},
    )
    assert r1.json()["done"] == 1

    # Deuxième tentative → already done
    r2 = client.post(
        "/review-queue/lots/ebay_A1/decide",
        json={"assignments": [
            {"asset_id": asset_id, "eurio_id": "fr-2015-2eur-paix", "face": "reverse"},
        ]},
    )
    body = r2.json()
    assert body["done"] == 0
    assert any("already done" in e for e in body["errors"])
    # face inchangée
    a = conn.execute(
        "SELECT face FROM image_assets WHERE id=?", (asset_id,),
    ).fetchone()
    assert a["face"] == "obverse"


def test_decide_lot_404_when_listing_unknown(app_client):
    _, _, client = app_client
    resp = client.post(
        "/review-queue/lots/ebay_DOES_NOT_EXIST/decide",
        json={"assignments": [{"asset_id": "X", "skip": True}]},
    )
    assert resp.status_code == 404


# ── Tests : detections + nav prev/next (Chunk 3) ──────────────────────────


def test_lot_detail_includes_raw_dimensions(app_client):
    """`raw_width` / `raw_height` exposés par image (vient de source_images)."""
    _, conn, client = app_client
    _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(2,))
    # Patch source_images for measurable dimensions.
    conn.execute(
        "UPDATE source_images SET width=2400, height=1800 WHERE id=?",
        ("SI_A1_0",),
    )
    body = client.get("/review-queue/lots/ebay_A1").json()
    assert len(body["images"]) == 1
    im = body["images"][0]
    assert im["raw_width"] == 2400
    assert im["raw_height"] == 1800
    # detections list is exposed even when raw file is absent (empty in this case).
    assert "detections" in im
    assert isinstance(im["detections"], list)


def test_lot_detail_detections_empty_when_json_null(app_client):
    """detections_json NULL (listing pré-backfill) → detections = [] (plate
    vide jusqu'au backfill ou re-détection manuelle, pas une erreur)."""
    _, conn, client = app_client
    _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(1,))
    body = client.get("/review-queue/lots/ebay_A1").json()
    im = body["images"][0]
    assert im["detections"] == []


def test_lot_detail_detections_read_from_persisted_json(app_client):
    """get_lot LIT `source_images.detections_json` (persisté au scrape) — plus
    aucun recompute live (c'était la cause des ~67s). Les cercles ACCEPTÉS
    sont mappés aux `crop_index` des image_assets par ordre.
    """
    import json

    _, conn, client = app_client
    _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(2,))

    # 2 acceptés (→ crop_index 0,1) + 1 rejeté (crop_index None).
    persisted = [
        {"cx": 350, "cy": 450, "r": 200, "method": "yolo+hough",
         "accepted": True, "reject_reason": None},
        {"cx": 850, "cy": 450, "r": 200, "method": "yolo+hough",
         "accepted": True, "reject_reason": None},
        {"cx": 1100, "cy": 100, "r": 40, "method": "yolo+bbox",
         "accepted": False, "reject_reason": "radius_too_small"},
    ]
    conn.execute(
        "UPDATE source_images SET detections_json=? WHERE id=?",
        (json.dumps(persisted), "SI_A1_0"),
    )

    body = client.get("/review-queue/lots/ebay_A1").json()
    im = body["images"][0]
    assert len(im["detections"]) == 3
    accepted = [d for d in im["detections"] if d["accepted"]]
    assert len(accepted) == 2
    db_crop_indices = {c["crop_index"] for c in im["crops"]}
    for det in accepted:
        assert det["crop_index"] in db_crop_indices
    # Le rejeté n'a pas de crop_index.
    rejected = [d for d in im["detections"] if not d["accepted"]]
    assert rejected[0]["crop_index"] is None
    assert rejected[0]["reject_reason"] == "radius_too_small"
    # Schéma exposé.
    for det in im["detections"]:
        assert {"cx", "cy", "r", "accepted", "reject_reason", "method"} <= set(det)


def test_detect_lot_image_404_when_image_not_in_lot(app_client):
    """POST /detect sur une source_image absente du listing → 404."""
    _, conn, client = app_client
    _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(2,))
    resp = client.post("/review-queue/lots/ebay_A1/images/SI_NOPE_0/detect")
    assert resp.status_code == 404


def test_detect_lot_image_persists_and_returns(app_client, monkeypatch):
    """POST /detect relance la détection (Chunk C), persiste detections_json,
    renvoie les cercles. `_compute_detections` monkeypatché (pas de YOLO/raw).
    """
    from review.review_queue_routes import LotDetection

    _, conn, client = app_client
    _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(2,))

    fake = [
        LotDetection(cx=350, cy=450, r=200, accepted=True,
                     reject_reason=None, method="yolo+hough", crop_index=0),
        LotDetection(cx=850, cy=450, r=200, accepted=True,
                     reject_reason=None, method="yolo+hough", crop_index=1),
        LotDetection(cx=1100, cy=100, r=40, accepted=False,
                     reject_reason="radius_too_small", method="yolo+bbox",
                     crop_index=None),
    ]
    monkeypatch.setattr(review_queue_routes, "_compute_detections",
                        lambda *a, **k: fake)

    resp = client.post("/review-queue/lots/ebay_A1/images/SI_A1_0/detect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_image_id"] == "SI_A1_0"
    assert len(body["detections"]) == 3
    assert sum(1 for d in body["detections"] if d["accepted"]) == 2

    # detections_json persisté (sans crop_index — dérivé à la lecture).
    persisted = conn.execute(
        "SELECT detections_json FROM source_images WHERE id='SI_A1_0'",
    ).fetchone()["detections_json"]
    parsed = json.loads(persisted)
    assert len(parsed) == 3
    assert "crop_index" not in parsed[0]
    assert {"cx", "cy", "r", "accepted", "reject_reason", "method"} == set(parsed[0])

    # get_lot relit le JSON fraîchement persisté → mêmes 3 cercles.
    im = client.get("/review-queue/lots/ebay_A1").json()["images"][0]
    assert len(im["detections"]) == 3


def test_add_lot_crop_404_when_image_not_in_lot(app_client):
    """POST /crops sur une source_image absente du listing → 404."""
    _, conn, client = app_client
    _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(1,))
    resp = client.post(
        "/review-queue/lots/ebay_A1/images/SI_NOPE_0/crops",
        json={"cx": 100, "cy": 100, "r": 50},
    )
    assert resp.status_code == 404


def test_add_lot_crop_returns_new_crop(app_client, monkeypatch):
    """POST /crops crée un crop (Chunk D) et renvoie le LotCrop enrichi.
    `create_manual_crop` monkeypatché (pas de raw/MinIO/Dino dans le test)."""
    from serving.crop_edit import NewCropData

    _, conn, client = app_client
    _seed_lot_listing(conn, item_id="A1", n_images=1, crops_per_image=(1,))

    def fake_create(store, source_image_id, cx, cy, r):
        return NewCropData(
            asset_id="NEW_ASSET", review_id="NEW_REVIEW",
            source_image_id=source_image_id, crop_index=1,
            bbox={"x": cx - r, "y": cy - r, "w": 2 * r, "h": 2 * r},
            width=224, height=224, phash=123,
            storage_path="ebay/run/NEW_ASSET.png",
            candidate_eurio_ids=[{"eurio_id": "fr-2015-2eur-paix"}],
            minio_ok=True, dino_recomputed=False,
        )
    import serving.crop_edit as crop_edit_mod
    monkeypatch.setattr(crop_edit_mod, "create_manual_crop", fake_create)

    resp = client.post(
        "/review-queue/lots/ebay_A1/images/SI_A1_0/crops",
        json={"cx": 350, "cy": 450, "r": 200},
    )
    assert resp.status_code == 200, resp.text
    crop = resp.json()
    assert crop["asset_id"] == "NEW_ASSET"
    assert crop["review_id"] == "NEW_REVIEW"
    assert crop["crop_index"] == 1
    assert "/assets/NEW_ASSET/file" in crop["crop_url"]
    assert crop["bbox"]["w"] == 400
    # candidat enrichi (eurio_id présent au minimum).
    assert crop["candidate_eurio_ids"][0]["eurio_id"] == "fr-2015-2eur-paix"


def test_lot_detail_prev_next_listing_keys(app_client):
    """`prev_listing_key` / `next_listing_key` dérivés de l'ordre enqueued_at ASC."""
    _, conn, client = app_client
    # 3 lots avec enqueue dans l'ordre LOT_A → LOT_B → LOT_C
    seeds = []
    for item in ("LOT_A", "LOT_B", "LOT_C"):
        seeds.append(_seed_lot_listing(conn, item_id=item, n_images=1, crops_per_image=(1,)))
    # On s'assure d'un ordre temporel stable (le seed met enqueued_at = now).
    # Forcer des enqueued_at distincts pour éviter les ex-aequo de tri.
    for i, item in enumerate(("LOT_A", "LOT_B", "LOT_C")):
        conn.execute(
            f"""
            UPDATE review_queue
               SET enqueued_at = datetime('now', '+{i} seconds')
             WHERE image_asset_id IN (
               SELECT a.id FROM image_assets a
                 JOIN source_images si ON si.id = a.source_image_id
                WHERE si.source_ref = ?
             )
            """,
            (f"ebay_{item}_img0",),
        )

    body_a = client.get("/review-queue/lots/ebay_LOT_A").json()
    body_b = client.get("/review-queue/lots/ebay_LOT_B").json()
    body_c = client.get("/review-queue/lots/ebay_LOT_C").json()

    assert body_a["prev_listing_key"] is None
    assert body_a["next_listing_key"] == "ebay_LOT_B"
    assert body_b["prev_listing_key"] == "ebay_LOT_A"
    assert body_b["next_listing_key"] == "ebay_LOT_C"
    assert body_c["prev_listing_key"] == "ebay_LOT_B"
    assert body_c["next_listing_key"] is None
