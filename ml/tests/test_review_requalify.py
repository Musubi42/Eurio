"""Tests pour la requalification single↔lot + le fix reflag UPSERT.

Couvre :
- reflag (coin_assets) : UPSERT sur un asset déjà reviewé (ligne 'done') —
  régression du bug UNIQUE(image_asset_id) → 500 (la connexion étant en
  autocommit, l'UPDATE passait mais l'INSERT plantait, asset coincé).
- POST /review-queue/{id}/requalify-lot : single → lot, portée listing entier.
- POST /review-queue/lots/{key}/requalify-single : lot → single (inverse).
- POST /review-queue/requalify-lot/batch : dry-run (compte) puis exécution.
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

from serving import coin_assets_routes, review_queue_routes
from serving.coin_assets_routes import router as coins_router
from serving.review_queue_routes import router as review_router
from store import Store


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """App montant les deux routers (review + coins) sur un même Store tmp."""
    store = Store(tmp_path / "t.db")
    monkeypatch.setattr(review_queue_routes, "_store", lambda: store)
    coin_assets_routes.bind(store)

    app = FastAPI()
    app.include_router(review_router)
    app.include_router(coins_router)
    return store, store._connection(), TestClient(app)  # noqa: SLF001


# ── Seed helpers ───────────────────────────────────────────────────────────


def _seed_listing(conn, *, item_id: str, n_crops: int = 1,
                  kind: str = "single") -> tuple[str, list[str], list[str]]:
    """Un eBay item (1 source_image) + n crops + n rows review_queue.

    Retourne (source_image_id, [asset_ids], [review_ids])."""
    si_id = f"SI_{item_id}"
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, target_eurio_id, listing_title,
          listing_price, listing_currency, storage_path, license,
          is_lot_suspected, raw_payload_json
        ) VALUES (?, 'ebay', ?, 'fr-2015-2eur-paix', 'Annonce', 10.0, 'EUR',
                  ?, 'fair_use_research', 0, ?)
        """,
        (si_id, f"ebay_{item_id}", f"/tmp/raw_{si_id}.jpg",
         json.dumps({"image_index": 0, "ebay_item_id": item_id})),
    )
    asset_ids, review_ids = [], []
    for c in range(n_crops):
        a_id = f"A_{item_id}_{c}"
        conn.execute(
            """
            INSERT INTO image_assets (
              id, source_image_id, crop_index, storage_path,
              resolution_status, variant_kind
            ) VALUES (?, ?, ?, ?, 'needs_review', 'auction_listing')
            """,
            (a_id, si_id, c, f"/tmp/crop_{a_id}.png"),
        )
        rq_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO review_queue (id, image_asset_id, priority, kind, status) "
            "VALUES (?, ?, 100, ?, 'open')",
            (rq_id, a_id, kind),
        )
        asset_ids.append(a_id)
        review_ids.append(rq_id)
    return si_id, asset_ids, review_ids


def _seed_lts(conn, si_id: str, listing_kind: str) -> None:
    conn.execute(
        """
        INSERT INTO listing_text_signals (source_image_id, coverage, listing_kind)
        VALUES (?, 'sparse', ?)
        """,
        (si_id, listing_kind),
    )


def _kinds(conn, asset_ids: list[str]) -> list[str]:
    ph = ",".join("?" * len(asset_ids))
    return [
        r["kind"] for r in conn.execute(
            f"SELECT kind FROM review_queue WHERE image_asset_id IN ({ph})",
            asset_ids,
        ).fetchall()
    ]


# ── reflag UPSERT (régression UNIQUE / autocommit) ─────────────────────────


def test_reflag_reopens_existing_done_row(app_client):
    """Un asset déjà reviewé (ligne 'done') doit être RÉ-OUVERT, pas dupliqué.
    L'ancien code faisait un 2ᵉ INSERT → UNIQUE(image_asset_id) → 500."""
    store, conn, client = app_client
    _si, [a_id], [rq_id] = _seed_listing(conn, item_id="DONE1")
    # Simule un asset déjà décidé : ligne 'done' + asset résolu 'manual'.
    conn.execute("UPDATE review_queue SET status='done' WHERE id=?", (rq_id,))
    conn.execute("UPDATE image_assets SET resolution_status='manual' WHERE id=?", (a_id,))

    resp = client.post("/coins/assets/reflag-needs-review", json={"asset_ids": [a_id]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["n_reflagged"] == 1
    # La ligne existante est ré-ouverte (même id) — pas un nouvel INSERT.
    assert body["review_ids"] == [rq_id]

    rows = conn.execute(
        "SELECT status FROM review_queue WHERE image_asset_id=?", (a_id,),
    ).fetchall()
    assert len(rows) == 1                       # toujours UNE ligne (UNIQUE respecté)
    assert rows[0]["status"] == "open"          # ré-ouverte
    asset = conn.execute(
        "SELECT resolution_status FROM image_assets WHERE id=?", (a_id,),
    ).fetchone()
    assert asset["resolution_status"] == "needs_review"


# ── requalify-lot (single → lot) ───────────────────────────────────────────


def test_requalify_lot_flips_whole_listing(app_client):
    store, conn, client = app_client
    si_id, asset_ids, review_ids = _seed_listing(conn, item_id="LOT1", n_crops=2)
    _seed_lts(conn, si_id, "single")

    resp = client.post(f"/review-queue/{review_ids[0]}/requalify-lot")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["n_requalified"] == 2           # les DEUX crops du listing
    assert body["listing_key"] == "ebay_LOT1"
    assert _kinds(conn, asset_ids) == ["lot", "lot"]
    lk = conn.execute(
        "SELECT listing_kind FROM listing_text_signals WHERE source_image_id=?",
        (si_id,),
    ).fetchone()["listing_kind"]
    assert lk == "lot"


# ── requalify-single (lot → single, inverse) ───────────────────────────────


def test_requalify_single_flips_back(app_client):
    store, conn, client = app_client
    si_id, asset_ids, _ = _seed_listing(conn, item_id="BACK1", n_crops=2, kind="lot")
    _seed_lts(conn, si_id, "lot")

    resp = client.post("/review-queue/lots/ebay_BACK1/requalify-single")
    assert resp.status_code == 200, resp.text
    assert resp.json()["n_requalified"] == 2
    assert _kinds(conn, asset_ids) == ["single", "single"]
    lk = conn.execute(
        "SELECT listing_kind FROM listing_text_signals WHERE source_image_id=?",
        (si_id,),
    ).fetchone()["listing_kind"]
    assert lk == "single"


# ── batch requalify-lot (dry-run puis exécution) ───────────────────────────


def test_batch_requalify_dry_run_then_execute(app_client):
    store, conn, client = app_client
    # Un coffret (2 crops, classé coffret) + un vrai single (1 crop, single).
    si_c, coffret_assets, _ = _seed_listing(conn, item_id="COF1", n_crops=2)
    _seed_lts(conn, si_c, "coffret")
    si_s, single_assets, _ = _seed_listing(conn, item_id="SGL1", n_crops=1)
    _seed_lts(conn, si_s, "single")

    # Dry-run : compte mais n'écrit rien.
    dry = client.post("/review-queue/requalify-lot/batch?dry_run=true").json()
    assert dry["dry_run"] is True
    assert dry["n_rows"] == 2
    assert dry["n_listings"] == 1
    assert dry["by_listing_kind"] == {"coffret": 2}
    assert _kinds(conn, coffret_assets) == ["single", "single"]   # inchangé

    # Exécution : bascule les 2 crops coffret, laisse le single.
    run = client.post("/review-queue/requalify-lot/batch?dry_run=false").json()
    assert run["dry_run"] is False
    assert run["n_rows"] == 2
    assert _kinds(conn, coffret_assets) == ["lot", "lot"]
    assert _kinds(conn, single_assets) == ["single"]

    # Idempotent : un 2ᵉ run ne trouve plus rien.
    again = client.post("/review-queue/requalify-lot/batch?dry_run=false").json()
    assert again["n_rows"] == 0
