"""C4a — routage des scripts recrop batch vers `POST /ingest/crops`.

Couvre le helper commun ``client.ingest.push_crops`` (gating ``sync_enabled``,
forme du payload) réutilisé par ``scripts.recrop_ebay_refine``,
``scripts.recrop_lots_per_coin`` et ``scripts.recrop_review_score_guided`` —
les trois scripts délèguent tous leur écriture géométrie à ce helper, donc le
tester couvre le comportement partagé sans avoir à rejouer les pipelines cv2
complets de chaque script.
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


def test_push_crops_noop_when_sync_disabled(monkeypatch):
    monkeypatch.delenv("EURIO_API_URL", raising=False)
    from client.ingest import push_crops

    calls = []
    monkeypatch.setattr("client.http.post_json", lambda *a, **k: calls.append((a, k)))
    result = push_crops([{"asset_id": "a1", "bbox_json": "{}", "detection_method": "x",
                           "width": 1, "height": 1}])
    assert result is None
    assert calls == []


def test_push_crops_noop_when_list_empty(monkeypatch):
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.test")
    from client.ingest import push_crops

    calls = []
    monkeypatch.setattr("client.http.post_json", lambda *a, **k: calls.append((a, k)))
    assert push_crops([]) is None
    assert calls == []


def test_push_crops_posts_ingest_crops_when_enabled(monkeypatch):
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.test")
    from client.ingest import push_crops

    calls = []

    def _fake_post_json(path, payload, **kwargs):
        calls.append((path, payload))
        return {"updated": len(payload["crops"]), "missing": []}

    monkeypatch.setattr("client.http.post_json", _fake_post_json)
    crops = [{"asset_id": "a1", "bbox_json": "{}", "detection_method": "bbox_refine+rimrefine",
              "width": 224, "height": 224, "phash": 42}]
    result = push_crops(crops)
    assert result == {"updated": 1, "missing": []}
    assert len(calls) == 1
    path, payload = calls[0]
    assert path == "/ingest/crops"
    assert payload["crops"] == crops
    assert payload["cache_invalidate"] is True


def test_push_crops_no_cache_invalidate_flag_when_disabled(monkeypatch):
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.test")
    from client.ingest import push_crops

    calls = []
    monkeypatch.setattr(
        "client.http.post_json",
        lambda path, payload, **k: calls.append(payload) or {"updated": 0, "missing": []},
    )
    push_crops([{"asset_id": "a1", "bbox_json": "{}", "detection_method": "x",
                 "width": 1, "height": 1}], cache_invalidate=False)
    assert "cache_invalidate" not in calls[0]


def test_recrop_scripts_import_push_crops_and_sync_enabled():
    """Les 3 scripts C4a délèguent bien au helper partagé (pas de triplication)."""
    import scripts.recrop_ebay_refine as m1
    import scripts.recrop_lots_per_coin as m2
    import scripts.recrop_review_score_guided as m3

    for mod in (m1, m2, m3):
        assert mod.push_crops.__module__ == "client.ingest"
        assert mod.sync_enabled.__module__ == "client.http"
