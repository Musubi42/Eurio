"""FastAPI integration tests for /benchmark/* (Bloc 3).

Uses a temporary SQLite store and an isolated REAL_PHOTOS_ROOT / THUMBNAIL_ROOT.
`POST /run` spawns a subprocess — we monkeypatch `_launch_run` to avoid that.

Run: `.venv/bin/python -m pytest ml/tests/test_benchmark_api.py -q`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from state import Store
    import api.benchmark_routes as br

    store = Store(tmp_path / "t.db")
    br.bind(store)

    real_photos = (tmp_path / "real_photos").resolve()
    real_photos.mkdir()
    thumbs = tmp_path / "thumbs"
    monkeypatch.setattr(br, "REAL_PHOTOS_ROOT", real_photos)
    monkeypatch.setattr(br, "THUMBNAIL_ROOT", thumbs)

    app = FastAPI()
    app.include_router(br.router)
    with TestClient(app) as c:
        yield c, store, real_photos, br


def _seed_photo(real_photos: Path, eurio_id: str, name: str = "01_natural-direct_wood_0deg.jpg") -> Path:
    coin = real_photos / eurio_id
    coin.mkdir(exist_ok=True)
    path = coin / name
    Image.new("RGB", (1024, 1024), (200, 200, 200)).save(path)
    return path


def _seed_manifest(real_photos: Path, coins: list[dict]) -> None:
    manifest = {
        "summary": {
            "root": str(real_photos),
            "num_coins": len(coins),
            "num_photos": sum(c.get("num_photos", 0) for c in coins),
            "by_zone": {"green": 0, "orange": 0, "red": 0, "unknown": 0},
        },
        "coins": coins,
    }
    (real_photos / "_manifest.json").write_text(json.dumps(manifest))


def test_library_empty(client):
    c, *_ = client
    resp = c.get("/benchmark/library")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["num_coins"] == 0


def test_library_from_manifest(client):
    c, store, real_photos, _ = client
    _seed_manifest(
        real_photos,
        [
            {"eurio_id": "fr-2007", "zone": "green", "num_photos": 5, "num_sessions": 2, "warnings": []},
        ],
    )
    resp = c.get("/benchmark/library")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["coins"][0]["eurio_id"] == "fr-2007"


def test_photos_for_coin_not_found(client):
    c, *_ = client
    resp = c.get("/benchmark/photos/fr-2007")
    assert resp.status_code == 404


def test_photos_for_coin_lists_files(client):
    c, store, real_photos, _ = client
    _seed_photo(real_photos, "fr-2007", "01_natural-direct_wood_0deg.jpg")
    _seed_photo(real_photos, "fr-2007", "02_artificial-warm_cloth_15deg.jpg")
    _seed_manifest(
        real_photos,
        [{"eurio_id": "fr-2007", "zone": "red", "num_photos": 2, "num_sessions": 2, "warnings": []}],
    )
    resp = c.get("/benchmark/photos/fr-2007")
    assert resp.status_code == 200
    data = resp.json()
    assert data["eurio_id"] == "fr-2007"
    assert data["zone"] == "red"
    assert len(data["photos"]) == 2
    assert all("thumbnail_url" in p for p in data["photos"])


def test_thumbnail_rejects_path_traversal(client):
    c, store, real_photos, br = client
    # Exercise the validator directly — TestClient/starlette normalize URLs, so
    # the handler never sees `../`. This is still the guard that matters.
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        br._safe_real_photo_path("../etc/passwd")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException):
        br._safe_real_photo_path("/absolute/path")


def test_thumbnail_serves_jpeg(client):
    c, store, real_photos, _ = client
    _seed_photo(real_photos, "fr-2007")
    resp = c.get("/benchmark/photos/thumbnail/fr-2007/01_natural-direct_wood_0deg.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")


def test_run_rejects_missing_model(client):
    c, *_ = client
    resp = c.post(
        "/benchmark/run",
        json={"model_path": "ml/checkpoints/does_not_exist.pth"},
    )
    assert resp.status_code == 404


def test_run_rejects_invalid_zone(client, tmp_path: Path):
    c, *_ = client
    fake_model = tmp_path / "m.pth"
    fake_model.write_bytes(b"\x00")
    resp = c.post(
        "/benchmark/run",
        json={"model_path": str(fake_model), "zones": ["purple"]},
    )
    assert resp.status_code == 400


def test_run_launches_and_returns_running(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    c, store, real_photos, br = client
    fake_model = tmp_path / "m.pth"
    fake_model.write_bytes(b"\x00")

    launched: list[tuple] = []

    def _fake_launch(payload, run_id):
        launched.append((payload, run_id))
        # Simulate the script inserting the row itself; we insert here instead.
        from state import BenchmarkRunRow
        store.create_benchmark_run(
            BenchmarkRunRow(
                id=run_id,
                model_path=str(fake_model),
                model_name="fake",
                report_path="ml/reports/x.json",
                status="running",
            )
        )

    monkeypatch.setattr(br, "_launch_run", _fake_launch)

    resp = c.post(
        "/benchmark/run",
        json={"model_path": str(fake_model), "run_id": "smoke"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "smoke"
    assert data["status"] == "running"
    assert launched and launched[0][1] == "smoke"


def test_list_and_filter_runs(client):
    c, store, *_ = client
    from state import BenchmarkRunRow

    store.create_benchmark_run(
        BenchmarkRunRow(
            id="x1", model_path="p", model_name="mA",
            zones=["green"], num_photos=5, num_coins=2, status="completed",
            report_path="ml/reports/x1.json",
        )
    )
    store.create_benchmark_run(
        BenchmarkRunRow(
            id="x2", model_path="p", model_name="mB",
            zones=["red"], num_photos=3, num_coins=1, status="completed",
            report_path="ml/reports/x2.json",
        )
    )
    resp = c.get("/benchmark/runs?model_name=mA")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert {r["id"] for r in data["items"]} == {"x1"}


def test_run_detail_and_delete(client):
    c, store, *_ = client
    from state import BenchmarkRunRow

    store.create_benchmark_run(
        BenchmarkRunRow(
            id="dx", model_path="p", model_name="m",
            report_path="ml/reports/dx.json", status="completed",
        )
    )
    resp = c.get("/benchmark/runs/dx")
    assert resp.status_code == 200
    assert resp.json()["id"] == "dx"

    resp = c.delete("/benchmark/runs/dx")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    resp = c.get("/benchmark/runs/dx")
    assert resp.status_code == 404
