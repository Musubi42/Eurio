"""P6-5 — la route d'ingest du banc, le client, et le garde « image lean ».

Sous Direction A, Mac/PC lisent une réplique en lecture seule : la seule façon
d'écrire un résultat de banc est ce POST. Un `INSERT` local échouerait à la
DERNIÈRE ligne, après tout le calcul — c'est le bug qui a fait perdre la trace
de tous les builds d'ancres pendant des semaines (cf. en-tête de
``0007_dino_reference_traceability.sql``).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from serving.deps import db_connection
from store import Store
from store.encoder_bench import SCHEMA_SQL

_RUN = {
    "run_id": "bench-1",
    "created_at": "2026-08-19T10:00:00Z",
    "gold_version": "abc123def456",
    "gold_n_crops": 1911,
    "anchors_kind": "2eur_all",
    "encoder_spec": "timm:vit_small_patch16_dinov3.lvd1689m",
    "encoder_version": "dinov3-vits16",
    "n_in_scope": 1800,
    "recall1": 0.77,
    "provisional_reason": "P3: 12454 predictions anterieures au build courant",
}
_PREDS = [
    {"asset_id": "a1", "truth_class_id": "fr-1999-2eur", "correct": 1, "in_top5": 1},
    {"asset_id": "a2", "truth_class_id": "de-2002-2eur", "correct": 0, "in_top5": 1,
     "spread": 0.012},
]


def _principal(scopes):
    return Principal(
        user_id="t", email="t@test.local", roles=["owner"],
        scopes=set(scopes), auth_method="api_token",
    )


@pytest.fixture()
def env(tmp_path):
    from serving import ingest_routes

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    conn.executescript(SCHEMA_SQL)
    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"ingest:write"})
    return conn, TestClient(app)


def test_endpoint_ecrit_run_et_predictions(env):
    conn, client = env
    r = client.post("/ingest/encoder-bench", json={"run": _RUN, "predictions": _PREDS})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["run_id"], body["n_predictions"], body["predictions_replaced"]) == (
        "bench-1", 2, True,
    )
    # M2 — la route mesure ses bloqueurs et les REMONTE. Sur cette base de test,
    # ni build d'ancres ni references : le run reste provisoire, et il le dit.
    assert body["provisional"] == 1
    assert any(b.startswith("P3:") for b in body["blockers"]), body

    row = conn.execute(
        "SELECT * FROM encoder_bench_runs WHERE run_id='bench-1'"
    ).fetchone()
    assert row["encoder_version"] == "dinov3-vits16"
    # Le défaut est provisional=1 : le payload ne l'a pas envoyé.
    assert row["provisional"] == 1
    n = conn.execute(
        "SELECT COUNT(*) FROM encoder_bench_predictions WHERE run_id='bench-1'"
    ).fetchone()[0]
    assert n == 2


def test_endpoint_est_idempotent(env):
    conn, client = env
    body = {"run": _RUN, "predictions": _PREDS}
    client.post("/ingest/encoder-bench", json=body)
    r = client.post("/ingest/encoder-bench", json=body)
    assert r.status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM encoder_bench_runs").fetchone()[0] == 1
    assert (
        conn.execute("SELECT COUNT(*) FROM encoder_bench_predictions").fetchone()[0] == 2
    )


def test_renvoyer_un_run_sans_predictions_ne_les_efface_pas(env):
    """D9 — le geste réel : repousser un run pour corriger sa ``note``.

    Le payload déclare ``predictions: list[...] = []`` ; avec le DELETE
    inconditionnel du store, ce POST à 200 renvoyait ``n_predictions: 0``
    APRÈS avoir effacé les 2 lignes par crop du run — la seule chose qui rend
    l'apparié rejouable sans ré-encoder.
    """
    conn, client = env
    client.post("/ingest/encoder-bench", json={"run": _RUN, "predictions": _PREDS})
    r = client.post(
        "/ingest/encoder-bench",
        json={"run": dict(_RUN, note="corrige a la main"), "predictions": []},
    )
    assert r.status_code == 200, r.text
    # `n_predictions: 0` seul est ambigu : « rien reçu » ou « tout effacé » ?
    # `predictions_replaced` tranche, dans la réponse même.
    body = r.json()
    assert (body["run_id"], body["n_predictions"], body["predictions_replaced"]) == (
        "bench-1", 0, False,
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM encoder_bench_predictions WHERE run_id='bench-1'"
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT note FROM encoder_bench_runs WHERE run_id='bench-1'"
    ).fetchone()[0] == "corrige a la main"


def test_la_reponse_distingue_remplacement_et_abstention(env):
    """Le POST qui fournit des prédictions annonce `predictions_replaced=True`.

    Sans ce champ, la page admin (et l'opérateur qui relit un log d'ingest) ne
    peut pas distinguer un run poussé sans prédictions d'un run dont les
    prédictions viennent d'être remplacées par une liste vide — la panne muette
    que D9 décrit. Contre-épreuve du test précédent : si le drapeau valait
    toujours False, il ne prouverait rien.
    """
    _conn, client = env
    r = client.post(
        "/ingest/encoder-bench", json={"run": _RUN, "predictions": _PREDS}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["run_id"], body["n_predictions"], body["predictions_replaced"]) == (
        "bench-1", 2, True,
    )


def test_endpoint_exige_le_scope(tmp_path):
    from serving import ingest_routes

    store = Store(tmp_path / "t.db")
    store._connection().executescript(SCHEMA_SQL)  # noqa: SLF001
    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"ingest:run"})
    r = TestClient(app).post(
        "/ingest/encoder-bench", json={"run": _RUN, "predictions": []}
    )
    assert r.status_code == 403


# ─── Lecture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def read_env(tmp_path):
    from serving import encoder_bench_routes

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    conn.executescript(SCHEMA_SQL)
    app = FastAPI()
    app.include_router(encoder_bench_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"lab:read"})
    app.dependency_overrides[db_connection] = lambda: conn
    return conn, TestClient(app)


def test_lecture_remonte_provisional_en_tete(read_env):
    conn, client = read_env
    run = dict(_RUN, sweep_json='[{"threshold":0.02,"precision":0.97}]')
    from store.encoder_bench import EncoderBenchRun, record_run

    record_run(conn, EncoderBenchRun(**run))

    body = client.get("/lab/encoder-bench/runs/bench-1").json()
    assert list(body)[0] == "provisional"
    assert body["provisional"] is True
    assert body["sweep"] == [{"threshold": 0.02, "precision": 0.97}]
    assert "sweep_json" not in body["run"]

    liste = client.get(
        "/lab/encoder-bench/runs", params={"encoder_version": "dinov3-vits16"}
    ).json()
    assert liste["n"] == 1
    assert client.get(
        "/lab/encoder-bench/runs", params={"encoder_version": "autre"}
    ).json()["n"] == 0
    assert client.get("/lab/encoder-bench/runs/absent").status_code == 404


def test_sweep_illisible_est_journalise_et_signale(read_env, caplog):
    """D15 — une courbe corrompue ne doit pas se faire passer pour une absence
    de courbe : elle est journalisée ET signalée dans la réponse.

    Avant : ``except (TypeError, ValueError): sweep = None``, sans logger dans
    le module — indistinguable d'un run sans balayage, côté page comme côté logs.
    """
    conn, client = read_env
    from store.encoder_bench import EncoderBenchRun, record_run

    record_run(conn, EncoderBenchRun(**dict(_RUN, sweep_json="{pas du json")))

    with caplog.at_level("ERROR"):
        body = client.get("/lab/encoder-bench/runs/bench-1").json()

    assert body["sweep"] is None
    assert body["sweep_error"], body
    assert any(
        "bench-1" in r.getMessage() and "sweep_json" in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_sweep_absent_ne_signale_aucune_erreur(read_env):
    conn, client = read_env
    from store.encoder_bench import EncoderBenchRun, record_run

    record_run(conn, EncoderBenchRun(**dict(_RUN, sweep_json=None)))
    body = client.get("/lab/encoder-bench/runs/bench-1").json()
    assert body["sweep"] is None
    assert body["sweep_error"] is None


# ─── Client (Direction A / Model A) ───────────────────────────────────────────


def test_push_noop_quand_sync_desactivee(monkeypatch):
    from client import ingest as client_ingest

    monkeypatch.delenv("EURIO_API_URL", raising=False)
    assert client_ingest.push_encoder_bench(_RUN, _PREDS) is None


def test_push_appelle_la_bonne_route(monkeypatch):
    from client import http as client_http
    from client import ingest as client_ingest

    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.test")
    seen = {}
    monkeypatch.setattr(
        client_http, "post_json",
        lambda path, payload: seen.update(path=path, payload=payload) or {"ok": 1},
    )
    assert client_ingest.push_encoder_bench(_RUN, _PREDS) == {"ok": 1}
    assert seen["path"] == "/ingest/encoder-bench"
    assert seen["payload"]["run"]["run_id"] == "bench-1"


# ─── Garde « image lean » ─────────────────────────────────────────────────────

_LEAN_PROBE = """
import sys
sys.path.insert(0, {ml!r})
import importlib
importlib.import_module("store.encoder_bench")
importlib.import_module("shared.stats.paired")
importlib.import_module("shared.stats.sweep")
importlib.import_module("serving.encoder_bench_routes")
heavy = sorted(m for m in ("torch", "cv2", "numpy", "timm") if m in sys.modules)
print(",".join(heavy))
"""


def test_aucun_import_lourd():
    """Sur l'image lean du VPS, ni cv2 ni torch ne sont installés : un import
    lourd au niveau module ferait skipper le routeur ENTIER, en silence.

    Le sous-process est indispensable — dans le process pytest, numpy est déjà
    chargé par d'autres tests et l'assertion serait tautologiquement fausse.
    """
    out = subprocess.run(
        [sys.executable, "-c", _LEAN_PROBE.format(ml=str(ML_DIR))],
        capture_output=True, text=True, cwd=str(ML_DIR),
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"imports lourds tirés : {out.stdout.strip()}"
