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
6. `need_only` (D2/D3) : seuls les crops dont le top-1 de la banque des
   suggestions tombe dans une classe ENCORE EN BESOIN sont servis — singles,
   lots, voisins. Classe pleine → parqué ; sans prédiction → parqué aussi (on
   ne sait pas). `run_progress(need_only=True)` sort ces parqués à part, et
   `total` reste celui du run entier. `need_only=False` ne change pas un
   caractère du SQL.
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

# Deux classes de banque : l'une à sa cible (8 `fps`, verdict `pleine`),
# l'autre à 2 (verdict `review`/`scrape`) — la seule qui reçoive du travail.
FULL = "fr-2015-2eur-paix"
NEEDY = "de-2016-2eur-sachsen"


# ─── Seed ───────────────────────────────────────────────────────────────────


def _seed_crop(
    conn, *, ref: str, run_id: str | None, kind: str = "single",
    status: str = "open", notes: str | None = None, lane: str | None = "manual",
    ebay_item: str | None = None, spread: float | None = None,
    top1: str | None = None,
) -> str:
    """Un crop en file, rattaché (ou non) à un run. Retourne le review_id.

    `spread` et/ou `top1` posent une prédiction dans la banque des SUGGESTIONS
    (`top1` par défaut : la classe pleine). Ni l'un ni l'autre : pas de
    prédiction — le cas « on ne sait pas ».
    """
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
    if spread is not None or top1 is not None:
        conn.execute(
            "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
            "anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim, "
            "spread) VALUES (?,?,?,?,?,?,?,?)",
            (f"a-{ref}", SUGGESTIONS_ENCODER_VERSION, SUGGESTIONS_ANCHORS_KIND,
             10, "[]", top1 or FULL, 0.8, 0.5 if spread is None else spread),
        )
    return f"rq-{ref}"


def _bank(conn, class_id: str, n_fps: int) -> None:
    """Une classe de la banque des suggestions, avec `n_fps` exemplaires."""
    conn.execute(
        "INSERT INTO dino_class_references (anchors_kind, encoder_version, "
        "class_id, eurio_id, method) VALUES (?,?,?,?,'canonical')",
        (SUGGESTIONS_ANCHORS_KIND, SUGGESTIONS_ENCODER_VERSION, class_id, class_id),
    )
    for i in range(n_fps):
        _fps(conn, class_id, i)


def _fps(conn, class_id: str, i: int) -> None:
    """Un exemplaire `fps` de plus, adossé à un asset (l'index unique de la
    table ne tolère qu'une row sans asset par classe : le canonique)."""
    si_id, aid = f"si-ref-{class_id}-{i}", f"a-ref-{class_id}-{i}"
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, storage_path) "
        "VALUES (?, 'ebay', ?, 'x.jpg')",
        (si_id, f"r-{si_id}"),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, "
        "storage_status) VALUES (?, ?, 'c.jpg', 'present')",
        (aid, si_id),
    )
    conn.execute(
        "INSERT INTO dino_class_references (anchors_kind, encoder_version, "
        "class_id, eurio_id, asset_id, method, rank) VALUES (?,?,?,?,?,'fps',?)",
        (SUGGESTIONS_ANCHORS_KIND, SUGGESTIONS_ENCODER_VERSION, class_id,
         class_id, aid, i),
    )


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
    for eid, cc, year in ((FULL, "FR", 2015), (NEEDY, "DE", 2016)):
        conn.execute(
            "INSERT INTO coins (eurio_id, country, country_name, year, face_value, "
            "is_commemorative, theme) VALUES (?, ?, ?, ?, 2.0, 1, 'thème')",
            (eid, cc, cc, year),
        )
    _bank(conn, FULL, 8)   # à la cible → `pleine`, parquée
    _bank(conn, NEEDY, 2)  # en besoin → servie
    # Run A : 3 singles ouverts (deux prédits — l'un en besoin, l'autre en
    #         classe pleine — le 3e sans prédiction), 1 déjà tranché, 1 passé,
    #         1 lot de 2 crops (ebay_A1 : un en besoin, un en classe pleine)
    _seed_crop(conn, ref="a1", run_id=RUN_A, spread=0.10, top1=NEEDY)
    _seed_crop(conn, ref="a2", run_id=RUN_A, spread=0.30, top1=FULL)
    _seed_crop(conn, ref="a3", run_id=RUN_A)
    _seed_crop(conn, ref="a4", run_id=RUN_A, status="done")
    _seed_crop(conn, ref="a5", run_id=RUN_A, notes="skipped")
    _seed_crop(conn, ref="a6", run_id=RUN_A, kind="lot", ebay_item="A1", top1=NEEDY)
    _seed_crop(conn, ref="a7", run_id=RUN_A, kind="lot", ebay_item="A1", top1=FULL)
    # Run B : 1 single ouvert (lane auto_accept, sans prédiction),
    #         1 lot (ebay_B1, en besoin)
    _seed_crop(conn, ref="b1", run_id=RUN_B, lane="auto_accept")
    _seed_crop(conn, ref="b2", run_id=RUN_B, kind="lot", ebay_item="B1", top1=NEEDY)
    # Run C (jamais demandé) : 1 single, 1 lot — en besoin, pour vérifier que
    # le périmètre run tient encore sous need_only
    _seed_crop(conn, ref="c1", run_id=RUN_C, top1=NEEDY)
    _seed_crop(conn, ref="c2", run_id=RUN_C, kind="lot", ebay_item="C1", top1=NEEDY)
    # Sans run : 1 single, 1 lot — seul un filtre ABSENT peut les servir
    _seed_crop(conn, ref="n1", run_id=None, top1=NEEDY)
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
            after = [
                it.model_dump()
                for it in _list(conn, run_ids=None, need_only=False, **kw)
            ]
            assert before == after
            assert before, kw
    finally:
        conn.set_trace_callback(None)
    assert seen
    assert not any("run_id" in sql for sql in seen)
    # `need_p` est l'alias réservé au filtre par besoin : absent, le filtre
    # n'a touché ni la requête ni la base (pas même un calcul du besoin).
    assert not any("need_p" in sql or "dino_class_references" in sql for sql in seen)
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


# ─── need_only (D2 / D3) ────────────────────────────────────────────────────


def test_deficient_class_ids_reads_class_need(env):
    conn, _ = env
    assert repository.deficient_class_ids(conn) == [NEEDY]


def test_need_only_hides_full_class_and_unpredicted_singles(env):
    conn, _ = env
    # a2 (classe pleine), a3 / a5 / b1 (sans prédiction) sortent ; a1 reste.
    assert _ids(_list(conn, run_ids=[RUN_A, RUN_B], need_only=True)) == {"rq-a1"}
    # Sans périmètre run : tout ce qui est en besoin, c1 et n1 compris.
    assert _ids(_list(conn, need_only=True)) == {"rq-a1", "rq-c1", "rq-n1"}
    # Se combine au tri DINO et à `kind`.
    assert _ids(_list(conn, need_only=True, order="dino", kind="all")) == {
        "rq-a1", "rq-c1", "rq-n1", "rq-a6", "rq-b2", "rq-c2",
    }


def test_need_only_lots_keep_only_listings_with_a_needed_crop(env):
    conn, _ = env
    # A1 garde son crop en besoin (a6), B1 aussi ; C1 hors run, N1 sans
    # prédiction.
    assert _lot_keys(conn, run_ids=[RUN_A, RUN_B], need_only=True) == [
        "ebay_A1", "ebay_B1",
    ]
    assert set(_lot_keys(conn, need_only=True)) == {"ebay_A1", "ebay_B1", "ebay_C1"}
    # Avec une cible en plus : toujours un ET.
    assert _lot_keys(
        conn, target_eurio_id=FULL, run_ids=[RUN_B], need_only=True,
    ) == ["ebay_B1"]


def test_need_only_siblings_follow_the_same_scope(env):
    conn, _ = env
    assert repository.lot_siblings(
        conn, "ebay_A1", run_ids=[RUN_A, RUN_B], need_only=True,
    ) == (None, "ebay_B1")
    # N1 n'a aucun crop prédit : hors périmètre, donc pas de voisins.
    assert repository.lot_siblings(conn, "ebay_N1", need_only=True) == (None, None)
    assert repository.lot_siblings(conn, "ebay_N1") == ("ebay_C1", None)


def test_need_only_when_the_class_fills_up(env):
    conn, _ = env
    # 6 exemplaires de plus : la classe atteint sa cible, plus rien n'est servi.
    for i in range(2, 8):
        _fps(conn, NEEDY, i)
    conn.commit()
    assert repository.deficient_class_ids(conn) == []
    assert _ids(_list(conn, need_only=True)) == set()
    assert _lot_keys(conn, need_only=True) == []
    p = repository.run_progress(conn, [RUN_A, RUN_B], need_only=True)
    # Les 5 rows ouvertes prédites (a1, a2, a6, a7, b2) sont toutes en classe
    # pleine ; a3 et b1 restent sans prédiction.
    assert (p.open, p.parked.full_class, p.parked.no_prediction) == (0, 5, 2)


def test_run_progress_need_only_parks_instead_of_counting_open(env):
    conn, _ = env
    p = repository.run_progress(conn, [RUN_A, RUN_B], need_only=True)
    assert p.need_only is True
    # total / done / skipped : ceux du run entier, inchangés.
    assert (p.total, p.done, p.skipped) == (9, 1, 1)
    # Ouvert = ce que la file servira : a1 (single), a6 + b2 (lots).
    assert p.open == 3
    assert (p.by_kind["single"].open, p.by_kind["lot"].open) == (1, 2)
    # Parqués : a2 + a7 (classe pleine) ; a3 + b1 (sans prédiction).
    assert p.parked is not None
    assert (p.parked.full_class, p.parked.no_prediction) == (2, 2)
    assert p.total == p.open + p.done + p.skipped + p.parked.full_class + p.parked.no_prediction
    # Sans le filtre : pas de `parked`, et l'ouvert d'avant.
    q = repository.run_progress(conn, [RUN_A, RUN_B])
    assert q.parked is None and q.need_only is False and q.open == 7


def test_run_progress_need_only_false_sql_unchanged(env):
    conn, _ = env
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    try:
        a = repository.run_progress(conn, [RUN_A, RUN_B])
        b = repository.run_progress(conn, [RUN_A, RUN_B], need_only=False)
    finally:
        conn.set_trace_callback(None)
    assert a == b
    assert len(seen) == 2 and seen[0] == seen[1]
    assert "need_p" not in seen[0]


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


def test_http_need_only_on_every_route(env):
    client = _client()
    q = f"run_id={RUN_A},{RUN_B}&need_only=true"
    r = client.get(f"/review-queue?limit=200&{q}")
    assert r.status_code == 200, r.text
    assert {it["id"] for it in r.json()} == {"rq-a1"}

    r = client.get(f"/review-queue/lots?{q}")
    assert r.status_code == 200, r.text
    assert [it["listing_key"] for it in r.json()["items"]] == ["ebay_A1", "ebay_B1"]

    r = client.get(f"/review-queue/lots/ebay_A1?{q}")
    assert r.status_code == 200, r.text
    assert r.json()["next_listing_key"] == "ebay_B1"

    r = client.get(f"/review-queue/run-progress?{q}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["need_only"] is True
    assert (body["total"], body["open"], body["done"], body["skipped"]) == (9, 3, 1, 1)
    assert body["parked"] == {"full_class": 2, "no_prediction": 2}

    # Sans le flag : `parked` est nul, l'ouvert est celui du run entier.
    body = client.get(f"/review-queue/run-progress?run_id={RUN_A},{RUN_B}").json()
    assert body["parked"] is None and body["open"] == 7
