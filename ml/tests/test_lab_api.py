"""FastAPI integration tests for /lab/* (Bloc 4).

IterationRunner chain is stubbed — we don't spawn subprocesses in tests.
Instead we verify:
- CRUD + validation + 404/409
- Launch wiring (runner.create_and_launch invoked with right args)
- Trajectory + sensitivity wiring
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


class _StubRunner:
    """Stands in for IterationRunner.

    Captures `create_iteration` calls and persists the row via the real
    Store (so subsequent GETs return it). Does not spawn threads. Tests
    that exercise `launch_training` set `self.busy` directly to simulate
    a runner-already-busy scenario.
    """

    def __init__(self, store):
        self.store = store
        self.busy = False
        self.launched: list[dict] = []
        self.training_launched: list[str] = []

    def is_busy(self) -> bool:
        return self.busy

    def create_iteration(self, **kwargs):
        from store import ExperimentIterationRow
        import uuid

        iid = uuid.uuid4().hex[:12]
        row = ExperimentIterationRow(
            id=iid,
            cohort_id=kwargs["cohort_id"],
            parent_iteration_id=kwargs.get("parent_iteration_id"),
            name=kwargs["name"],
            hypothesis=kwargs.get("hypothesis"),
            recipe_id=kwargs.get("recipe_id"),
            variant_count=kwargs.get("variant_count", 100),
            training_config=kwargs.get("training_config", {}),
            status="pending",
            verdict="pending",
        )
        self.store.create_iteration(row)
        self.launched.append({**kwargs, "iteration_id": iid})
        return row

    def launch_training(self, iteration_id: str):
        if self.busy:
            raise RuntimeError("busy")
        self.training_launched.append(iteration_id)
        return self.store.get_iteration(iteration_id)

    def _snapshot_inputs(self, iteration) -> dict:
        return {
            "recipe": None,
            "variant_count": iteration.variant_count,
            "training_config": iteration.training_config,
        }


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from store import Store
    import serving.lab_routes as lr

    store = Store(tmp_path / "t.db")
    stub = _StubRunner(store)
    lr.bind(store, stub)
    # Ces tests exercent le câblage CRUD/launch, pas le préflight référentiel
    # (`_require_classes_ready` → build_resolver), qui exige un catalogue `coins`
    # peuplé (absent du Store temporaire → RuntimeError 500). Ce préflight a sa
    # propre couverture ; on le neutralise ici pour isoler le câblage.
    monkeypatch.setattr(lr, "_require_classes_ready", lambda cohort: None)

    app = FastAPI()
    app.include_router(lr.router)
    with TestClient(app) as c:
        yield c, store, stub


def _post_cohort(client, name="green-v1", eurio_ids=None, zone="green"):
    c, *_ = client
    return c.post(
        "/lab/cohorts",
        json={
            "name": name,
            "eurio_ids": eurio_ids or ["fr-2007", "de-2005"],
            "zone": zone,
            "description": "test cohort",
        },
    )


# ─── Cohort CRUD ────────────────────────────────────────────────────────────


def test_create_cohort_validates_name(client):
    c, *_ = client
    resp = c.post("/lab/cohorts", json={"name": "Bad Name", "eurio_ids": ["a"]})
    assert resp.status_code == 400


def test_create_cohort_allows_empty_ids(client):
    # Une cohorte peut être créée vide depuis la page « créer cohorte » puis
    # peuplée plus tard (cf. create_cohort, lab_routes.py §draft-cohort).
    c, *_ = client
    resp = c.post("/lab/cohorts", json={"name": "good-name", "eurio_ids": []})
    assert resp.status_code == 200
    assert resp.json()["eurio_ids"] == []


def test_create_cohort_dedups_eurio_ids(client):
    resp = _post_cohort(client, eurio_ids=["fr-2007", "fr-2007", "de-2005"])
    assert resp.status_code == 200
    data = resp.json()
    assert sorted(data["eurio_ids"]) == ["de-2005", "fr-2007"]


def test_create_cohort_duplicate_name_409(client):
    _post_cohort(client)
    resp = _post_cohort(client)
    assert resp.status_code == 409


def test_get_cohort_by_name(client):
    _post_cohort(client, name="green-v1")
    c, *_ = client
    resp = c.get("/lab/cohorts/green-v1")
    assert resp.status_code == 200
    assert resp.json()["name"] == "green-v1"


def test_list_cohorts_filters_zone(client):
    _post_cohort(client, name="g1", zone="green")
    _post_cohort(client, name="r1", zone="red")
    c, *_ = client
    resp = c.get("/lab/cohorts?zone=red")
    assert resp.status_code == 200
    assert [item["name"] for item in resp.json()] == ["r1"]


def test_update_cohort_forbids_name_clash(client):
    _post_cohort(client, name="green-v1")
    _post_cohort(client, name="green-v2")
    c, *_ = client
    cohort = c.get("/lab/cohorts/green-v2").json()
    resp = c.put(f"/lab/cohorts/{cohort['id']}", json={"name": "green-v1"})
    assert resp.status_code == 409


def test_delete_cohort(client):
    _post_cohort(client, name="ephemeral")
    c, *_ = client
    cohort = c.get("/lab/cohorts/ephemeral").json()
    resp = c.delete(f"/lab/cohorts/{cohort['id']}")
    assert resp.status_code == 200
    assert c.get(f"/lab/cohorts/{cohort['id']}").status_code == 404


# ─── Iteration launch ──────────────────────────────────────────────────────


def test_create_iteration_calls_runner(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={
            "name": "baseline",
            "hypothesis": "just wanted a starting point",
            "variant_count": 150,
            "training_config": {"epochs": 40},
        },
    )
    assert resp.status_code == 200
    assert len(stub.launched) == 1
    assert stub.launched[0]["variant_count"] == 150
    assert stub.launched[0]["cohort_id"] == cohort["id"]


def test_create_iteration_rejects_empty_name(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "   "},
    )
    assert resp.status_code == 400


def test_create_iteration_rejects_absurd_variant_count(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "huge", "variant_count": 10000},
    )
    assert resp.status_code == 400


def test_create_iteration_succeeds_when_busy_and_launch_rejects(client):
    """Two-phase flow: creation is always allowed (even when a runner is busy),
    only `launch-training` rejects with 409. Users want the new draft to appear
    immediately so they can pre-bake augmentations while the previous iteration
    is still finishing."""
    _post_cohort(client, name="c1")
    c, store, stub = client
    stub.busy = True
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "late"},
    )
    assert resp.status_code == 200, resp.text
    iid = resp.json()["id"]

    launch = c.post(
        f"/lab/cohorts/{cohort['id']}/iterations/{iid}/launch-training",
    )
    # Stub raises RuntimeError("busy") — route maps that to 409.
    assert launch.status_code == 409


def test_runner_status_endpoint(client):
    c, store, stub = client
    assert c.get("/lab/runner/status").json() == {"busy": False}
    stub.busy = True
    assert c.get("/lab/runner/status").json() == {"busy": True}


# ─── Iteration CRUD + drill-down ───────────────────────────────────────────


def test_update_iteration_accepts_notes_and_verdict_override(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "baseline"},
    )
    iteration = c.get(
        f"/lab/cohorts/{cohort['id']}/iterations"
    ).json()[0]
    resp = c.put(
        f"/lab/cohorts/{cohort['id']}/iterations/{iteration['id']}",
        json={"notes": "résultat inattendu", "verdict_override": "better"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "résultat inattendu"
    assert resp.json()["verdict_override"] == "better"


def test_update_iteration_rejects_invalid_verdict(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "baseline"},
    )
    iteration = c.get(
        f"/lab/cohorts/{cohort['id']}/iterations"
    ).json()[0]
    resp = c.put(
        f"/lab/cohorts/{cohort['id']}/iterations/{iteration['id']}",
        json={"verdict_override": "amazing"},
    )
    assert resp.status_code == 400


def test_delete_iteration_forbidden_while_running(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "baseline"},
    )
    iteration = c.get(
        f"/lab/cohorts/{cohort['id']}/iterations"
    ).json()[0]
    store.update_iteration(iteration["id"], status="training")
    resp = c.delete(
        f"/lab/cohorts/{cohort['id']}/iterations/{iteration['id']}"
    )
    assert resp.status_code == 409


# ─── Trajectory + sensitivity ──────────────────────────────────────────────


def test_trajectory_returns_compact_list(client):
    _post_cohort(client, name="c1")
    c, store, stub = client
    cohort = c.get("/lab/cohorts/c1").json()
    c.post(
        f"/lab/cohorts/{cohort['id']}/iterations",
        json={"name": "baseline"},
    )
    traj = c.get(f"/lab/cohorts/{cohort['id']}/trajectory")
    assert traj.status_code == 200
    data = traj.json()
    assert len(data) == 1
    assert data[0]["name"] == "baseline"
    assert "r_at_1" in data[0]


def test_sensitivity_runs_on_empty_cohort(client):
    _post_cohort(client, name="c1")
    c, *_ = client
    cohort = c.get("/lab/cohorts/c1").json()
    resp = c.get(f"/lab/cohorts/{cohort['id']}/sensitivity")
    assert resp.status_code == 200
    assert resp.json() == []


# ─── Live tests (Sprint 4) ──────────────────────────────────────────────────


import json
from pathlib import Path

import serving.lab_routes as _lr_mod
from store import (
    BenchmarkRunRow,
    ExperimentCohortRow,
    ExperimentIterationRow,
)


@pytest.fixture()
def live_test_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Same wiring as ``client`` but with a redirected LIVE_TEST_LOGS_DIR.

    The default ``ml/state/live_test_logs/`` lives under the repo. We point it
    at a tmp dir for hermetic runs.
    """
    from store import Store
    import serving.lab_routes as lr

    store = Store(tmp_path / "t.db")
    stub = _StubRunner(store)
    lr.bind(store, stub)
    logs_dir = tmp_path / "live_test_logs"
    logs_dir.mkdir()
    monkeypatch.setattr(lr, "LIVE_TEST_LOGS_DIR", logs_dir)

    app = FastAPI()
    app.include_router(lr.router)
    with TestClient(app) as c:
        yield c, store, logs_dir


def _seed_cohort_with_completed_iteration(
    store, *, eurio_ids=None, r_at_1=0.92,
):
    eurio_ids = eurio_ids or ["fr-2007", "de-2005"]
    store.create_cohort(ExperimentCohortRow(
        id="c1", name="cohort-x", eurio_ids=eurio_ids, status="frozen",
    ))
    store.create_benchmark_run(BenchmarkRunRow(
        id="b1", model_path="", model_name="m",
        report_path="", status="completed", r_at_1=r_at_1,
    ))
    store.create_iteration(ExperimentIterationRow(
        id="iter1", cohort_id="c1", name="it1",
        status="completed", benchmark_run_id="b1",
    ))


def _line(idx: int, *, eid="fr-2007", cond="bright",
          top1="fr-2007", sim=0.95, correct=True, error=None) -> str:
    return json.dumps({
        "schema_version": 1,
        "test_idx": idx,
        "iteration_id": "iter1",
        "expected_eurio_id": eid,
        "condition": cond,
        "predicted_top3": [{"eurio_id": top1, "similarity": sim}] if top1 else [],
        "predicted_top1": top1,
        "similarity_top1": sim if top1 else None,
        "is_correct": correct,
        "error": error,
        "ts": "2026-04-30T14:00:00Z",
    })


def test_live_tests_sync_404_when_log_missing(live_test_client):
    c, store, _ = live_test_client
    _seed_cohort_with_completed_iteration(store)
    resp = c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})
    assert resp.status_code == 404
    assert "JSONL absent" in resp.json()["detail"]


def test_live_tests_sync_404_when_iteration_missing(live_test_client):
    c, *_ = live_test_client
    resp = c.post("/lab/cohorts/_/iterations/missing/live-tests/sync", json={})
    assert resp.status_code == 404


def test_live_tests_sync_parses_and_dedups(live_test_client):
    c, store, logs = live_test_client
    _seed_cohort_with_completed_iteration(store)
    (logs / "iter1.jsonl").write_text("\n".join([
        _line(1),
        _line(2, cond="dim", top1="de-2005", sim=0.42, correct=False),
        _line(3, eid="de-2005", cond="tilt", top1=None, sim=0.0,
              correct=False, error="normalize failed"),
        "",
        "not-json",
        json.dumps({"schema_version": 99}),
    ]) + "\n")

    resp = c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["inserted"] == 3
    assert body["skipped_dupe"] == 0
    assert len(body["parse_errors"]) == 2
    assert body["summary"]["total"] == 3
    assert body["summary"]["correct"] == 1
    assert body["summary"]["recall_at_1"] == pytest.approx(1 / 3)
    assert body["summary"]["studio_r_at_1"] == pytest.approx(0.92)
    assert body["summary"]["delta"] == pytest.approx(1 / 3 - 0.92)

    # Resync = idempotent.
    resp2 = c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})
    assert resp2.json()["inserted"] == 0
    assert resp2.json()["skipped_dupe"] == 3


def test_live_tests_sync_verdict_uses_design_group_equivalence(live_test_client):
    """A design_group prediction grades CORRECT against its eurio_id member.

    Régression du faux R@1 strict (project_live_tests_strict_recall_bug) : le
    modèle prédit `xx-2euro-standard-t1` (label de groupe) alors que l'attendu
    est `xx-2014-2eur-standard` — strict=faux mais eq=vrai. La recall §5 doit
    suivre l'eq, pas le strict.
    """
    c, store, logs = live_test_client
    # Seed a coin whose eurio_id maps to a design_group, so build_equivalence_map
    # (reading the bound store DB) resolves the mesh. numista_id required —
    # coin_refs_from_sqlite filters on it. Committed via _writing() because the
    # map reads through a separate RO connection to the same file.
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES (?, ?)",
            ("xx-2euro-standard-t1", "XX 2€ standard type 1"),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO coins (
              eurio_id, country, country_name, year, face_value,
              is_commemorative, numista_id, design_group_id, raw_payload_json
            ) VALUES (?, 'XX', 'XX', 2014, 2.0, 0, 999001, ?, '{}')
            """,
            ("xx-2014-2eur-standard", "xx-2euro-standard-t1"),
        )

    store.create_cohort(ExperimentCohortRow(
        id="c1", name="cohort-eq", eurio_ids=["xx-2014-2eur-standard"],
        status="frozen",
    ))
    store.create_benchmark_run(BenchmarkRunRow(
        id="b1", model_path="", model_name="m",
        report_path="", status="completed", r_at_1=0.90,
    ))
    store.create_iteration(ExperimentIterationRow(
        id="iter1", cohort_id="c1", name="it1",
        status="completed", benchmark_run_id="b1",
    ))
    (logs / "iter1.jsonl").write_text(
        _line(
            1, eid="xx-2014-2eur-standard", top1="xx-2euro-standard-t1",
            sim=0.81, correct=False,  # device said strict-false; server re-grades
        ) + "\n"
    )

    resp = c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})
    assert resp.status_code == 200
    summary = resp.json()["summary"]
    assert summary["correct"] == 1          # eq-aware
    assert summary["correct_strict"] == 0   # strict can't match a group label
    assert summary["recall_at_1"] == pytest.approx(1.0)
    assert summary["recall_at_1_strict"] == pytest.approx(0.0)

    # The matrix cell carries the eq verdict.
    body = c.get("/lab/cohorts/c1/iterations/iter1/live-tests").json()
    cell = body["matrix"]["xx-2014-2eur-standard"]["bright"]
    assert cell["is_correct_eq"] is True
    assert cell["is_correct"] is False


def test_live_tests_get_returns_matrix(live_test_client):
    c, store, logs = live_test_client
    _seed_cohort_with_completed_iteration(store)
    (logs / "iter1.jsonl").write_text("\n".join([
        _line(1),
        _line(2, cond="dim", top1="de-2005", correct=False),
    ]) + "\n")
    c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})

    resp = c.get("/lab/cohorts/c1/iterations/iter1/live-tests")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cohort_name"] == "cohort-x"
    assert body["conditions"] == ["bright", "dim", "tilt"]
    assert "fr-2007" in body["matrix"]
    assert set(body["matrix"]["fr-2007"]) == {"bright", "dim"}
    assert body["summary"]["total"] == 2


def test_live_tests_get_404_on_wrong_cohort(live_test_client):
    c, store, _ = live_test_client
    _seed_cohort_with_completed_iteration(store)
    resp = c.get("/lab/cohorts/missing/iterations/iter1/live-tests")
    assert resp.status_code == 404


def test_live_tests_sync_rejects_iteration_id_mismatch(live_test_client):
    c, store, logs = live_test_client
    _seed_cohort_with_completed_iteration(store)
    bad = json.dumps({
        "schema_version": 1, "test_idx": 1, "iteration_id": "WRONG",
        "expected_eurio_id": "fr-2007", "condition": "bright",
        "predicted_top3": [], "predicted_top1": None,
        "similarity_top1": None, "is_correct": False,
        "ts": "2026-04-30T14:00:00Z",
    })
    (logs / "iter1.jsonl").write_text(bad + "\n")
    resp = c.post("/lab/cohorts/_/iterations/iter1/live-tests/sync", json={})
    assert resp.status_code == 200
    assert resp.json()["inserted"] == 0
    assert any("iteration_id" in e for e in resp.json()["parse_errors"])


# ── QA crops d'entraînement par classe (boucle d'amélioration) ───────────────


def _seed_coin(conn, eurio_id, numista_id, design_group_id):
    conn.execute(
        "INSERT OR REPLACE INTO coins (eurio_id, country, country_name, year, "
        "face_value, is_commemorative, numista_id, design_group_id, "
        "raw_payload_json) VALUES (?, 'XX', 'XX', 2016, 2.0, 1, ?, ?, '{}')",
        (eurio_id, numista_id, design_group_id),
    )


def _seed_crop(conn, eurio_id, *, face, eligible, status, quality, denom="2eur"):
    import uuid
    sid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
        "listing_title) VALUES (?, 'ebay', ?, ?, 'titre')",
        (sid, f"ebay_{sid}", eurio_id),
    )
    aid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, eurio_id, "
        "resolution_status, face, denom, quality_score, training_eligible, "
        "storage_path) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
        (aid, sid, eurio_id, status, face, denom, quality,
         1 if eligible else 0, f"ebay/{sid}/{aid}.png"),
    )
    return aid


def test_cohort_training_crops_rolls_up_design_group_and_ranks(client):
    c, store, _ = client
    # Deux eurio_ids du même design_group → UNE classe.
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES "
            "(?, ?)", ("grp-portrait", "Portrait"),
        )
        _seed_coin(conn, "xx-2016-a", 900101, "grp-portrait")
        _seed_coin(conn, "xx-2016-b", 900102, "grp-portrait")
        # Membre A : 2 obverse eligible, 1 unknown-face eligible (suspect),
        #            1 reverse rejected (non eligible).
        a_obv = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=True,
                           status="manual", quality=0.9)
        _seed_crop(conn, "xx-2016-a", face="obverse", eligible=True,
                   status="manual", quality=0.8)
        _seed_crop(conn, "xx-2016-a", face="unknown", eligible=True,
                   status="manual", quality=0.5)
        _seed_crop(conn, "xx-2016-a", face="reverse", eligible=False,
                   status="rejected", quality=0.2)
        # Membre B : 1 obverse eligible (le rollup doit l'inclure).
        _seed_crop(conn, "xx-2016-b", face="obverse", eligible=True,
                   status="manual", quality=0.7)
    # Cohorte + itération + benchmark avec per_coin (couplage R@1).
    store.create_cohort(ExperimentCohortRow(
        id="cg", name="cohort-grp", eurio_ids=["xx-2016-a", "xx-2016-b"],
        status="frozen",
    ))
    store.create_benchmark_run(BenchmarkRunRow(
        id="bg", model_path="", model_name="m", report_path="",
        status="completed", r_at_1=0.6,
        per_coin=[{"eurio_id": "xx-2016-a", "r_at_1": 0.5}],
    ))
    store.create_iteration(ExperimentIterationRow(
        id="itg", cohort_id="cg", name="it", status="completed",
        benchmark_run_id="bg",
    ))

    resp = c.get("/lab/cohorts/cg/training-crops")
    assert resp.status_code == 200
    body = resp.json()
    assert body["benchmark_run_id"] == "bg"
    assert len(body["classes"]) == 1          # A+B collapsed into grp-portrait
    cls = body["classes"][0]
    assert cls["class_id"] == "grp-portrait"
    assert set(cls["member_eurio_ids"]) == {"xx-2016-a", "xx-2016-b"}
    assert cls["n_eligible"] == 4             # 3 from A + 1 from B
    assert cls["n_unknown_face"] == 1         # the eligible unknown-face crop
    assert cls["n_rejected"] == 1
    assert cls["r_at_1"] == pytest.approx(0.5)
    # Suspect d'abord : la première vignette n'est pas un obverse.
    assert cls["crops"][0]["face"] != "obverse"

    # Toggle : exclure un crop obverse → n_eligible baisse, réversible.
    off = c.post(f"/lab/assets/{a_obv}/training-eligible", json={"eligible": False})
    assert off.status_code == 200
    assert off.json()["training_eligible"] is False
    again = c.get("/lab/cohorts/cg/training-crops").json()["classes"][0]
    assert again["n_eligible"] == 3
    on = c.post(f"/lab/assets/{a_obv}/training-eligible", json={"eligible": True})
    assert on.json()["training_eligible"] is True
    assert c.get("/lab/cohorts/cg/training-crops").json()["classes"][0]["n_eligible"] == 4


def test_set_training_eligible_404_on_unknown_asset(client):
    c, *_ = client
    resp = c.post("/lab/assets/nope/training-eligible", json={"eligible": False})
    assert resp.status_code == 404


def test_cohort_training_crops_404_on_unknown_cohort(client):
    c, *_ = client
    assert c.get("/lab/cohorts/nope/training-crops").status_code == 404


def test_reassign_asset_moves_crop_to_target_coin(client):
    c, store, _ = client
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES "
            "(?, ?), (?, ?)",
            ("grp-a", "A", "grp-b", "B"),
        )
        _seed_coin(conn, "xx-2016-a", 910001, "grp-a")
        _seed_coin(conn, "xx-2016-b", 910002, "grp-b")
        # Un crop bien cadré mais attribué à la mauvaise pièce (grp-a).
        aid = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=True,
                         status="manual", quality=0.9)

    resp = c.post(f"/lab/assets/{aid}/reassign", json={"eurio_id": "xx-2016-b"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["eurio_id"] == "xx-2016-b"
    assert body["previous_eurio_id"] == "xx-2016-a"

    # L'asset a bien migré, training_eligible préservé.
    with store._writing() as conn:
        row = conn.execute(
            "SELECT eurio_id, training_eligible FROM image_assets WHERE id = ?",
            (aid,),
        ).fetchone()
    assert row["eurio_id"] == "xx-2016-b"
    assert row["training_eligible"] == 1


def test_cohort_training_crops_merges_scan_verdicts_and_health(client):
    """P1/P4/P5/P6 : le dernier scan done remonte les intrus en tête, la santé
    par classe est calculée, le Δ R@1 vs l'itération benchée précédente aussi,
    et les confusions du bench sont agrégées à la maille classe."""
    from store import ScanResultRow, training_scan_start, training_scan_finish
    from store import training_scan_upsert_results, local_state_store

    c, store, _ = client
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES "
            "(?, ?), (?, ?)", ("grp-a", "A", "grp-b", "B"),
        )
        _seed_coin(conn, "xx-2016-a", 930001, "grp-a")
        _seed_coin(conn, "xx-2016-b", 930002, "grp-b")
        a1 = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=True,
                        status="manual", quality=0.9)
        a2 = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=True,
                        status="manual", quality=0.95)
        # Un reverse éligible : flaggé, mais HORS bake (P3) → pas dans n_eligible.
        _seed_crop(conn, "xx-2016-a", face="reverse", eligible=True,
                   status="manual", quality=0.4)
        _seed_crop(conn, "xx-2016-b", face="obverse", eligible=True,
                   status="manual", quality=0.8)
    store.create_cohort(ExperimentCohortRow(
        id="cs", name="cohort-scan", eurio_ids=["xx-2016-a", "xx-2016-b"],
        status="frozen",
    ))
    # Deux itérations benchées → P5 (delta) ; per_coin + confusion sur la dernière.
    store.create_benchmark_run(BenchmarkRunRow(
        id="b-prev", model_path="", model_name="m", report_path="",
        status="completed", r_at_1=0.5,
        per_coin=[{"eurio_id": "xx-2016-a", "r_at_1": 0.5}],
    ))
    store.create_benchmark_run(BenchmarkRunRow(
        id="b-last", model_path="", model_name="m", report_path="",
        status="completed", r_at_1=0.75,
        per_coin=[{"eurio_id": "xx-2016-a", "r_at_1": 0.75}],
        confusion={"xx-2016-a": {"xx-2016-a": 3, "xx-2016-b": 2}},
    ))
    store.create_iteration(ExperimentIterationRow(
        id="it-prev", cohort_id="cs", name="prev", status="completed",
        benchmark_run_id="b-prev", finished_at="2026-06-01T00:00:00Z",
    ))
    store.create_iteration(ExperimentIterationRow(
        id="it-last", cohort_id="cs", name="last", status="completed",
        benchmark_run_id="b-last", finished_at="2026-06-20T00:00:00Z",
    ))
    # cohort_training_scans/_results = store d'état LOCAL (split bookkeeping) ;
    # les seeds canoniques (iteration_aug_vs_real) restent sur `conn`.
    lconn = local_state_store()._connection()
    with store._writing() as conn:
        conn.executemany(
            "INSERT INTO iteration_aug_vs_real (iteration_id, eurio_id, "
            "num_real, num_aug, cosine, dino_version) VALUES (?,?,?,?,0.5,'v')",
            [("it-prev", "grp-a", 2, 20), ("it-last", "grp-a", 3, 30)],
        )
    # Scan done : a1 = probable intrus (Dino préfère grp-b), a2 = ok.
    scan_id = training_scan_start(
        lconn, cohort_id="cs", anchors_kind="2eur_all",
        encoder_version="dinov2-vitl14", intruder_margin=0.05, n_total=4,
    )
    training_scan_upsert_results(lconn, scan_id, [
        ScanResultRow(
            asset_id=a1, assigned_class="grp-a", assigned_sim=0.61,
            top1_class="grp-b", top1_eurio_id="xx-2016-b", top1_sim=0.72,
            margin=0.11, is_intruder=True,
        ),
        ScanResultRow(
            asset_id=a2, assigned_class="grp-a", assigned_sim=0.80,
            top1_class="grp-a", top1_eurio_id="xx-2016-a", top1_sim=0.80,
            margin=0.0, is_intruder=False,
        ),
    ])
    training_scan_finish(lconn, scan_id, status="done", n_done=4,
                         n_intruders=1, n_faces_written=0, n_skipped=0)

    body = c.get("/lab/cohorts/cs/training-crops").json()
    assert body["benchmark_run_id"] == "b-last"
    assert body["prev_benchmark_run_id"] == "b-prev"
    assert body["scan"]["n_intruders"] == 1
    cls_a = next(cl for cl in body["classes"] if cl["class_id"] == "grp-a")
    # P3 reflété : le reverse éligible ne compte plus « dans le train ».
    assert cls_a["n_eligible"] == 2
    assert cls_a["n_reverse_flagged"] == 1
    assert cls_a["n_obverse"] == 2
    # P1 : l'intrus est compté ET remonté en tête de grille.
    assert cls_a["n_intruders"] == 1
    assert cls_a["crops"][0]["asset_id"] == a1
    assert cls_a["crops"][0]["intruder_suspect"] is True
    assert cls_a["crops"][0]["intruder_top1_class"] == "grp-b"
    # P5 : delta vs itération benchée précédente + seed réel au bake.
    assert cls_a["r_at_1"] == pytest.approx(0.75)
    assert cls_a["r_at_1_prev"] == pytest.approx(0.5)
    assert cls_a["r_at_1_delta"] == pytest.approx(0.25)
    assert cls_a["n_real_last_bake"] == 3
    assert cls_a["n_real_prev_bake"] == 2
    # P4 : santé — 2 crops < min_real → sous-alimentée, pas de réfs.
    assert cls_a["underfed"] is True
    assert cls_a["has_numista_ref"] is False
    assert cls_a["n_bce_ref"] == 0
    # P6 : confusion agrégée à la classe (self exclu).
    assert cls_a["confused_with"] == [{"class_id": "grp-b", "n": 2}]


def _seed_intruder_scan(client):
    """Cohorte 'ci' : a1 flaggé intrus au train, a2 propre. Retourne (a1, a2)."""
    from store import ScanResultRow, training_scan_start, training_scan_finish
    from store import training_scan_upsert_results, local_state_store

    c, store, _ = client
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES "
            "(?, ?), (?, ?)", ("grp-a", "A", "grp-b", "B"),
        )
        _seed_coin(conn, "xx-2016-a", 930001, "grp-a")
        _seed_coin(conn, "xx-2016-b", 930002, "grp-b")
        a1 = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=True,
                        status="manual", quality=0.9)
        a2 = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=True,
                        status="manual", quality=0.95)
    store.create_cohort(ExperimentCohortRow(
        id="ci", name="cohort-intruder", eurio_ids=["xx-2016-a", "xx-2016-b"],
        status="frozen",
    ))
    lconn = local_state_store()._connection()  # scan bookkeeping = local
    scan_id = training_scan_start(
        lconn, cohort_id="ci", anchors_kind="2eur_all",
        encoder_version="dinov2-vitl14", intruder_margin=0.05, n_total=2,
    )
    training_scan_upsert_results(lconn, scan_id, [
        ScanResultRow(
            asset_id=a1, assigned_class="grp-a", assigned_sim=0.61,
            top1_class="grp-b", top1_eurio_id="xx-2016-b", top1_sim=0.72,
            margin=0.11, is_intruder=True, intruder_reason="margin",
        ),
        ScanResultRow(
            asset_id=a2, assigned_class="grp-a", assigned_sim=0.80,
            top1_class="grp-a", top1_eurio_id="xx-2016-a", top1_sim=0.80,
            margin=0.0, is_intruder=False,
        ),
    ])
    training_scan_finish(lconn, scan_id, status="done", n_done=2,
                         n_intruders=1, n_faces_written=0, n_skipped=0)
    return a1, a2


def test_intruder_dismiss_clears_badge_keeps_eligible(client):
    """« Faux positif — garde-le au train » : dismiss retire le badge et le
    compteur d'intrus SANS toucher training_eligible ni is_intruder (audit)."""
    c, store, _ = client
    a1, _ = _seed_intruder_scan(client)

    before = c.get("/lab/cohorts/ci/training-crops").json()
    cls = next(cl for cl in before["classes"] if cl["class_id"] == "grp-a")
    assert cls["n_intruders"] == 1
    assert cls["crops"][0]["asset_id"] == a1
    assert cls["crops"][0]["intruder_suspect"] is True

    resp = c.post(f"/lab/assets/{a1}/intruder-dismiss?cohort_id=ci")
    assert resp.status_code == 200
    assert resp.json() == {"asset_id": a1, "dismissed": True}

    after = c.get("/lab/cohorts/ci/training-crops").json()
    cls = next(cl for cl in after["classes"] if cl["class_id"] == "grp-a")
    assert cls["n_intruders"] == 0
    a1_crop = next(cr for cr in cls["crops"] if cr["asset_id"] == a1)
    assert a1_crop["intruder_suspect"] is False
    # Toujours au train : le dismiss ne l'exclut pas.
    assert a1_crop["training_eligible"] is True
    # L'audit du scan est intact (is_intruder non réécrit) — table LOCALE.
    from store import local_state_store
    row = local_state_store()._connection().execute(
        "SELECT is_intruder, dismissed FROM cohort_training_scan_results "
        "WHERE asset_id=?", (a1,),
    ).fetchone()
    assert row["is_intruder"] == 1
    assert row["dismissed"] == 1


def test_training_crops_reconciles_unrouted_needs_review(client):
    """C · réconciliation C4↔C5 : un needs_review sans row review_queue ouverte
    est compté `n_review_unrouted` (routed=False) ; un needs_review avec une row
    ouverte est routed=True et n'est PAS compté (il atteindra l'écran de review)."""
    import uuid
    c, store, _ = client
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES (?, ?)",
            ("grp-r", "R"),
        )
        _seed_coin(conn, "xx-2016-a", 930010, "grp-r")
        routed = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=False,
                            status="needs_review", quality=0.5)
        _unrouted = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=False,
                               status="needs_review", quality=0.5)
        # Seule la 1ʳᵉ est enfilée (row review_queue ouverte).
        conn.execute(
            "INSERT INTO review_queue (id, image_asset_id, status, lane) "
            "VALUES (?, ?, 'open', 'manual')", (uuid.uuid4().hex, routed),
        )
    store.create_cohort(ExperimentCohortRow(
        id="cr", name="cohort-reconcile", eurio_ids=["xx-2016-a"],
        status="frozen",
    ))
    body = c.get("/lab/cohorts/cr/training-crops").json()
    cls = next(cl for cl in body["classes"] if cl["class_id"] == "grp-r")
    assert cls["n_review_unrouted"] == 1
    by_id = {cr["asset_id"]: cr for cr in cls["crops"]}
    assert by_id[routed]["routed"] is True
    assert by_id[_unrouted]["routed"] is False


def test_intruder_dismiss_404_on_unknown_asset(client):
    c, _, _ = client
    assert c.post("/lab/assets/nope/intruder-dismiss").status_code == 404


def test_reassign_clears_stale_intruder_verdict(client):
    """Réassigner (même vers la même classe = override du choix Dino) périme le
    verdict → le badge intrus disparaît au read suivant."""
    c, _, _ = client
    a1, _ = _seed_intruder_scan(client)
    # Réassigner a1 vers grp-b (la classe que Dino préférait).
    resp = c.post(f"/lab/assets/{a1}/reassign", json={"eurio_id": "xx-2016-b"})
    assert resp.status_code == 200
    body = c.get("/lab/cohorts/ci/training-crops").json()
    # a1 a quitté grp-a ; où qu'il soit, plus de badge intrus (verdict périmé).
    for cl in body["classes"]:
        for cr in cl["crops"]:
            if cr["asset_id"] == a1:
                assert cr["intruder_suspect"] is False


def test_training_scan_status_idle_then_running(client):
    from store import training_scan_start, local_state_store

    c, store, _ = client
    store.create_cohort(ExperimentCohortRow(
        id="ct", name="cohort-t", eurio_ids=["xx-1"], status="frozen",
    ))
    assert c.get("/lab/cohorts/ct/training-scan/status").json() == {
        "status": "idle",
    }
    # cohort_training_scans = store d'état LOCAL (split bookkeeping).
    training_scan_start(
        local_state_store()._connection(), cohort_id="ct", anchors_kind="2eur_all",
        encoder_version="dinov2-vitl14", intruder_margin=0.05, n_total=7,
    )
    body = c.get("/lab/cohorts/ct/training-scan/status").json()
    assert body["status"] == "running"
    assert body["n_total"] == 7
    # Un scan déjà en cours bloque un nouveau lancement (409).
    resp = c.post("/lab/cohorts/ct/training-scan")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "training_scan_already_running"


def test_training_scan_404_on_unknown_cohort(client):
    c, *_ = client
    assert c.post("/lab/cohorts/nope/training-scan").status_code == 404
    assert c.get("/lab/cohorts/nope/training-scan/status").json() == {
        "status": "idle",
    }


def test_reassign_asset_404_on_unknown_asset(client):
    c, *_ = client
    resp = c.post("/lab/assets/nope/reassign", json={"eurio_id": "xx-2016-a"})
    assert resp.status_code == 404


def test_reassign_asset_404_on_unknown_target_coin(client):
    c, store, _ = client
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES (?, ?)",
            ("grp-a", "A"),
        )
        _seed_coin(conn, "xx-2016-a", 920001, "grp-a")
        aid = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=True,
                         status="manual", quality=0.9)
    resp = c.post(f"/lab/assets/{aid}/reassign", json={"eurio_id": "does-not-exist"})
    assert resp.status_code == 404


def test_reopen_review_demotes_train_crop_and_requeues(client):
    """« Repasser en reviewer » : un crop au train (manual/eligible) redevient
    needs_review + training_eligible=0 ET obtient une row review_queue OUVERTE
    (réapparaît dans l'écran Review)."""
    c, store, _ = client
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES (?, ?)",
            ("grp-a", "A"),
        )
        _seed_coin(conn, "xx-2016-a", 930001, "grp-a")
        aid = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=True,
                         status="manual", quality=0.9)

    resp = c.post(f"/lab/assets/{aid}/reopen-review")
    assert resp.status_code == 200
    body = resp.json()
    assert body["asset_id"] == aid
    assert body["review_id"]

    with store._writing() as conn:
        row = conn.execute(
            "SELECT resolution_status, training_eligible, resolved_at "
            "FROM image_assets WHERE id = ?", (aid,),
        ).fetchone()
        assert row["resolution_status"] == "needs_review"
        assert row["training_eligible"] == 0
        assert row["resolved_at"] is None
        rq = conn.execute(
            "SELECT status FROM review_queue WHERE image_asset_id = ?", (aid,),
        ).fetchone()
        assert rq is not None
        assert rq["status"] == "open"


def test_reopen_review_upserts_existing_done_row(client):
    """Un crop déjà tranché porte une row review_queue 'done' → l'UPSERT la
    ré-ouvre au lieu de violer UNIQUE(image_asset_id)."""
    c, store, _ = client
    import uuid
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES (?, ?)",
            ("grp-a", "A"),
        )
        _seed_coin(conn, "xx-2016-a", 930002, "grp-a")
        aid = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=True,
                         status="manual", quality=0.9)
        conn.execute(
            "INSERT INTO review_queue (id, image_asset_id, status, priority, "
            "enqueued_at, kind, lane, lane_source) VALUES "
            "(?, ?, 'done', 100, '2026-01-01', 'single', 'manual', 'human')",
            (uuid.uuid4().hex, aid),
        )

    resp = c.post(f"/lab/assets/{aid}/reopen-review")
    assert resp.status_code == 200
    with store._writing() as conn:
        rows = conn.execute(
            "SELECT status FROM review_queue WHERE image_asset_id = ?", (aid,),
        ).fetchall()
    assert len(rows) == 1              # UPSERT, pas une 2ᵉ ligne
    assert rows[0]["status"] == "open"


def test_reopen_review_404_on_unknown_asset(client):
    c, *_ = client
    assert c.post("/lab/assets/nope/reopen-review").status_code == 404


def test_accept_training_promotes_needs_review_crop(client):
    """« Accepter au train » un crop needs_review : passe manual + eligible et
    ferme sa file de review → il sort de « À reviewer » vers « Au train »."""
    c, store, _ = client
    import uuid
    with store._writing() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES (?, ?)",
            ("grp-a", "A"),
        )
        _seed_coin(conn, "xx-2016-a", 940001, "grp-a")
        # Crop encore à reviewer (needs_review), non éligible.
        aid = _seed_crop(conn, "xx-2016-a", face="obverse", eligible=False,
                         status="needs_review", quality=0.8)
        conn.execute(
            "INSERT INTO review_queue (id, image_asset_id, status, priority, "
            "enqueued_at, kind, lane, lane_source) VALUES "
            "(?, ?, 'open', 100, '2026-01-01', 'single', 'manual', 'human')",
            (uuid.uuid4().hex, aid),
        )

    resp = c.post(f"/lab/assets/{aid}/accept-training")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolution_status"] == "manual"
    assert body["training_eligible"] is True

    with store._writing() as conn:
        row = conn.execute(
            "SELECT resolution_status, training_eligible, resolved_at "
            "FROM image_assets WHERE id = ?", (aid,),
        ).fetchone()
        assert row["resolution_status"] == "manual"
        assert row["training_eligible"] == 1
        assert row["resolved_at"] is not None
        rq = conn.execute(
            "SELECT status FROM review_queue WHERE image_asset_id = ?", (aid,),
        ).fetchone()
        assert rq["status"] == "done"


def test_accept_training_404_on_unknown_asset(client):
    c, *_ = client
    assert c.post("/lab/assets/nope/accept-training").status_code == 404
