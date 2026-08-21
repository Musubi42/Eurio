"""La file de review cadrée sur un ou plusieurs RUNS source (`?run_id=a,b`).

Ce qui est verrouillé :

1. `list_queue(run_ids=…)` ne sert que les crops dont `image_assets.run_id`
   est dans la liste, et ce filtre se COMBINE avec `kind` / `lane` / le tri
   DINO au lieu de les remplacer.
2. `list_lots` / `lot_siblings` suivent le même périmètre — le mode lot d'une
   URL `?run=` ne déborde pas sur les autres runs.
3. `run_progress` compte toutes les rows des runs (ouvert / tranché / passé),
   par kind, et `skip` fait avancer le compteur sans fermer la row.
4. `run_ids=None` ne change RIEN : pas un token `run_id` dans le SQL exécuté,
   et le même résultat qu'une requête qui n'en parle pas — y compris les crops
   sans run (`run_id IS NULL`), que seul un filtre absent peut servir.
5. Les routes HTTP splittent `run_id` comme `review_ids`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from serving.review_queue import repository
from serving.review_queue.router import router as review_router
from shared.verdict_scope import SUGGESTIONS_ANCHORS_KIND, SUGGESTIONS_ENCODER_VERSION
from store import Store

RUN_A = "10408fc2d40945e491d656cb0b75d2b5"
RUN_B = "fc6f11c6d754485997b1dc56a3feac2e"
RUN_C = "cccccccccccccccccccccccccccccccc"  # un run qu'on ne demande jamais


# ─── Seed ───────────────────────────────────────────────────────────────────


def _seed_crop(
    conn, *, ref: str, run_id: str | None, kind: str = "single",
    status: str = "open", notes: str | None = None, lane: str | None = "manual",
    ebay_item: str | None = None, spread: float | None = None,
) -> str:
    """Un crop en file, rattaché (ou non) à un run. Retourne le review_id."""
    si_id = f"si-{ebay_item}" if ebay_item else f"si-{ref}"
    raw = f'{{"ebay_item_id": "{ebay_item}"}}' if ebay_item else None
    conn.execute(
        "INSERT OR IGNORE INTO source_images (id, source, source_ref, run_id, "
        "target_eurio_id, listing_country, listing_year, storage_path, "
        "raw_payload_json) "
        "VALUES (?, 'ebay', ?, ?, 'fr-2015-2eur-paix', 'FR', 2015, 'x.jpg', ?)",
        (si_id, f"r-{si_id}", run_id, raw),
    )
    n = conn.execute(
        "SELECT COUNT(*) AS c FROM image_assets WHERE source_image_id = ?",
        (si_id,),
    ).fetchone()["c"]
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, run_id, crop_index, "
        "storage_path, storage_status, face) "
        "VALUES (?, ?, ?, ?, 'c.jpg', 'present', 'obverse')",
        (f"a-{ref}", si_id, run_id, n),
    )
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status, kind, lane, "
        "priority, enqueued_at, decision_notes) "
        "VALUES (?, ?, ?, ?, ?, 5, ?, ?)",
        (f"rq-{ref}", f"a-{ref}", status, kind, lane,
         f"2026-01-01T00:00:{len(ref):02d}", notes),
    )
    if spread is not None:
        conn.execute(
            "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
            "anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim, "
            "spread) VALUES (?,?,?,?,?,?,?,?)",
            (f"a-{ref}", SUGGESTIONS_ENCODER_VERSION, SUGGESTIONS_ANCHORS_KIND,
             10, "[]", "fr-2015-2eur-paix", 0.8, spread),
        )
    return f"rq-{ref}"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = Store(db)._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    for rid in (RUN_A, RUN_B, RUN_C):
        conn.execute(
            "INSERT INTO source_runs (id, source, kind) VALUES (?, 'ebay', 'run')",
            (rid,),
        )
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative) "
        "VALUES ('fr-2015-2eur-paix', 'FR', 2015, 2.0, 1)",
    )
    # Run A : 3 singles ouverts (un trié par DINO), 1 déjà tranché, 1 passé,
    #         1 lot de 2 crops (ebay_A1)
    _seed_crop(conn, ref="a1", run_id=RUN_A, spread=0.10)
    _seed_crop(conn, ref="a2", run_id=RUN_A, spread=0.30)
    _seed_crop(conn, ref="a3", run_id=RUN_A)
    _seed_crop(conn, ref="a4", run_id=RUN_A, status="done")
    _seed_crop(conn, ref="a5", run_id=RUN_A, notes="skipped")
    _seed_crop(conn, ref="a6", run_id=RUN_A, kind="lot", ebay_item="A1")
    _seed_crop(conn, ref="a7", run_id=RUN_A, kind="lot", ebay_item="A1")
    # Run B : 1 single ouvert (lane auto_accept), 1 lot (ebay_B1)
    _seed_crop(conn, ref="b1", run_id=RUN_B, lane="auto_accept")
    _seed_crop(conn, ref="b2", run_id=RUN_B, kind="lot", ebay_item="B1")
    # Run C (jamais demandé) : 1 single, 1 lot
    _seed_crop(conn, ref="c1", run_id=RUN_C)
    _seed_crop(conn, ref="c2", run_id=RUN_C, kind="lot", ebay_item="C1")
    # Sans run : 1 single, 1 lot — seul un filtre ABSENT peut les servir
    _seed_crop(conn, ref="n1", run_id=None)
    _seed_crop(conn, ref="n2", run_id=None, kind="lot", ebay_item="N1")
    conn.commit()
    return conn, db


def _ids(items) -> set[str]:
    return {it.id for it in items}


def _list(conn, **kw):
    base = dict(
        status="open", limit=200, order="priority", kind="single", lane=None,
        cohort_id=None, eurio_id=None, review_ids=None,
    )
    base.update(kw)
    return repository.list_queue(conn, **base)


# ─── list_queue ─────────────────────────────────────────────────────────────


def test_run_scope_restricts_to_assets_of_those_runs(env):
    conn, _ = env
    assert _ids(_list(conn, run_ids=[RUN_A, RUN_B])) == {
        "rq-a1", "rq-a2", "rq-a3", "rq-a5", "rq-b1",
    }
    assert _ids(_list(conn, run_ids=[RUN_B])) == {"rq-b1"}
    assert _ids(_list(conn, run_ids=["inconnu"])) == set()


def test_run_scope_combines_with_kind_and_lane(env):
    conn, _ = env
    assert _ids(_list(conn, run_ids=[RUN_A, RUN_B], kind="lot")) == {
        "rq-a6", "rq-a7", "rq-b2",
    }
    assert _ids(_list(conn, run_ids=[RUN_A, RUN_B], kind="all")) == {
        "rq-a1", "rq-a2", "rq-a3", "rq-a5", "rq-a6", "rq-a7", "rq-b1", "rq-b2",
    }
    # `lane=manual` écarte b1 (auto_accept) sans toucher au périmètre run.
    assert _ids(_list(conn, run_ids=[RUN_A, RUN_B], lane="manual")) == {
        "rq-a1", "rq-a2", "rq-a3", "rq-a5",
    }


def test_run_scope_is_compatible_with_dino_order(env):
    conn, _ = env
    items = _list(conn, run_ids=[RUN_A], order="dino")
    # Du plus net au plus flou, les non-scorés en queue — et rien d'un autre run.
    assert [it.id for it in items][:2] == ["rq-a2", "rq-a1"]
    assert _ids(items) == {"rq-a1", "rq-a2", "rq-a3", "rq-a5"}


def test_run_scope_combines_with_review_ids(env):
    conn, _ = env
    # Des ids explicites hors du run ne passent pas la porte.
    assert _ids(_list(conn, run_ids=[RUN_A], review_ids=["rq-a1", "rq-c1"])) == {
        "rq-a1",
    }


# ─── run_ids=None : rien ne change ──────────────────────────────────────────


def test_run_ids_none_leaves_sql_and_result_untouched(env):
    conn, _ = env
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    try:
        for kw in (
            {},
            {"kind": "lot"},
            {"kind": "all", "lane": "manual"},
            {"order": "dino"},
            {"review_ids": ["rq-a1", "rq-n1"]},
        ):
            before = [it.model_dump() for it in _list(conn, **kw)]
            after = [it.model_dump() for it in _list(conn, run_ids=None, **kw)]
            assert before == after
            assert before, kw
    finally:
        conn.set_trace_callback(None)
    assert seen
    assert not any("run_id" in sql for sql in seen)
    # Les crops sans run restent servis — c'est ce qu'un filtre absent garantit.
    assert "rq-n1" in _ids(_list(conn))
    assert "rq-n2" in _ids(_list(conn, kind="lot"))


def test_run_ids_empty_list_behaves_like_none(env):
    conn, _ = env
    assert _ids(_list(conn, run_ids=[])) == _ids(_list(conn))


# ─── Lots ───────────────────────────────────────────────────────────────────


def _lot_keys(conn, **kw) -> list[str]:
    base = dict(
        limit=50, offset=0, cohort_id=None, target_eurio_id=None,
        design_group=None,
    )
    base.update(kw)
    items, total = repository.list_lots(conn, **base)
    assert total == len(items)
    return [it.listing_key for it in items]


def test_lots_follow_the_run_scope(env):
    conn, _ = env
    assert _lot_keys(conn, run_ids=[RUN_A, RUN_B]) == ["ebay_A1", "ebay_B1"]
    assert _lot_keys(conn, run_ids=[RUN_B]) == ["ebay_B1"]
    assert set(_lot_keys(conn)) == {"ebay_A1", "ebay_B1", "ebay_C1", "ebay_N1"}
    # Combiné à une cible : la cible seule sert tout, run + cible restreint.
    assert len(_lot_keys(conn, target_eurio_id="fr-2015-2eur-paix")) == 4
    assert _lot_keys(
        conn, target_eurio_id="fr-2015-2eur-paix", run_ids=[RUN_A],
    ) == ["ebay_A1"]


def test_lot_siblings_stay_inside_the_runs(env):
    conn, _ = env
    assert repository.lot_siblings(conn, "ebay_A1", run_ids=[RUN_A, RUN_B]) == (
        None, "ebay_B1",
    )
    assert repository.lot_siblings(conn, "ebay_B1", run_ids=[RUN_A, RUN_B]) == (
        "ebay_A1", None,
    )
    # Un lot hors périmètre n'a pas de voisins : on ne devine pas.
    assert repository.lot_siblings(conn, "ebay_C1", run_ids=[RUN_A, RUN_B]) == (
        None, None,
    )


# ─── run_progress ───────────────────────────────────────────────────────────


def test_run_progress_counts_all_statuses_by_kind(env):
    conn, _ = env
    p = repository.run_progress(conn, [RUN_A, RUN_B])
    assert p.run_ids == [RUN_A, RUN_B]
    assert (p.total, p.open, p.done, p.skipped) == (9, 7, 1, 1)
    s, l = p.by_kind["single"], p.by_kind["lot"]
    assert (s.total, s.open, s.done, s.skipped) == (6, 4, 1, 1)
    assert (l.total, l.open, l.done, l.skipped) == (3, 3, 0, 0)
    assert set(p.by_kind) == {"single", "lot"}


def test_run_progress_moves_on_decide_and_skip(env):
    conn, _ = env
    conn.execute("UPDATE review_queue SET status = 'done' WHERE id = 'rq-a1'")
    conn.execute(
        "UPDATE review_queue SET decision_notes = 'skipped' WHERE id = 'rq-a2'",
    )
    conn.commit()
    p = repository.run_progress(conn, [RUN_A, RUN_B])
    assert (p.total, p.open, p.done, p.skipped) == (9, 5, 2, 2)


def test_run_progress_unknown_run_is_all_zero(env):
    conn, _ = env
    p = repository.run_progress(conn, ["inconnu"])
    assert (p.total, p.open, p.done, p.skipped) == (0, 0, 0, 0)
    assert p.by_kind["single"].total == 0 and p.by_kind["lot"].total == 0


# ─── HTTP ───────────────────────────────────────────────────────────────────


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(review_router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="t", email="t@test.local", roles=["reviewer"],
        scopes={"review:read"}, auth_method="api_token",
    )
    return TestClient(app)


def test_http_run_id_is_split_on_commas(env):
    client = _client()
    r = client.get(
        f"/review-queue?limit=200&lane=manual&run_id={RUN_A},{RUN_B}",
    )
    assert r.status_code == 200, r.text
    assert {it["id"] for it in r.json()} == {"rq-a1", "rq-a2", "rq-a3", "rq-a5"}

    r = client.get(f"/review-queue/lots?run_id={RUN_A},{RUN_B}")
    assert r.status_code == 200, r.text
    assert [it["listing_key"] for it in r.json()["items"]] == ["ebay_A1", "ebay_B1"]
    assert r.json()["total"] == 2

    r = client.get(f"/review-queue/lots/ebay_A1?run_id={RUN_A},{RUN_B}")
    assert r.status_code == 200, r.text
    assert r.json()["next_listing_key"] == "ebay_B1"


def test_http_run_progress(env):
    client = _client()
    r = client.get(f"/review-queue/run-progress?run_id={RUN_A},{RUN_B}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_ids"] == [RUN_A, RUN_B]
    assert (body["total"], body["open"], body["done"], body["skipped"]) == (9, 7, 1, 1)
    assert body["by_kind"]["lot"]["open"] == 3

    assert client.get("/review-queue/run-progress").status_code == 422
    assert client.get("/review-queue/run-progress?run_id=,").status_code == 422
