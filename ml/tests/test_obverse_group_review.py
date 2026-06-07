"""Tests de la review vision intra-groupe (logique de parsing, chat mocké)."""

from __future__ import annotations

from pathlib import Path

import training.foundation.obverse_group_review as ogr
from shared.ccproxy_client import ChatResult


def _canned(content: str) -> ChatResult:
    return ChatResult(
        content=content, model="claude-sonnet-4-6",
        tokens_in=1, tokens_out=1, cache_creation_tokens=0,
        cache_read_tokens=0, cost_usd=0.001, duration_ms=1,
    )


def _patch_chat(monkeypatch, *, content=None, exc=None) -> None:
    def fake_chat(**kwargs):
        if exc is not None:
            raise exc
        return _canned(content)
    monkeypatch.setattr(ogr, "chat", fake_chat)
    # Évite la lecture disque des images dans image_part.
    monkeypatch.setattr(ogr, "image_part", lambda path: {"type": "image", "path": str(path)})


_MEMBERS = [("be-1999", Path("a.jpg")), ("be-2007", Path("b.jpg"))]


def test_review_coherent(monkeypatch) -> None:
    _patch_chat(monkeypatch, content='{"same_obverse":true,"outlier_index":null,"confidence":0.95}')
    rev = ogr.review_group(group_id="be-2euro-albert-ii-t1", members=_MEMBERS)
    assert rev.ok
    assert rev.same_obverse is True
    assert rev.outlier_index is None
    assert rev.confidence == 0.95


def test_review_outlier_maps_label(monkeypatch) -> None:
    _patch_chat(monkeypatch, content='{"same_obverse":false,"outlier_index":2,"confidence":0.88}')
    rev = ogr.review_group(group_id="g", members=_MEMBERS)
    assert not rev.ok
    assert rev.same_obverse is False
    assert rev.outlier_index == 2
    assert rev.outlier_label == "be-2007"


def test_review_outlier_index_out_of_range_ignored(monkeypatch) -> None:
    _patch_chat(monkeypatch, content='{"same_obverse":false,"outlier_index":9,"confidence":0.5}')
    rev = ogr.review_group(group_id="g", members=_MEMBERS)
    assert rev.outlier_index is None  # 9 hors [1,2]
    assert rev.outlier_label is None


def test_review_ccproxy_down_is_error(monkeypatch) -> None:
    _patch_chat(monkeypatch, exc=ConnectionError("refused"))
    rev = ogr.review_group(group_id="g", members=_MEMBERS)
    assert not rev.ok
    assert rev.error is not None and "ConnectionError" in rev.error


def test_review_parse_fail(monkeypatch) -> None:
    _patch_chat(monkeypatch, content="not json at all")
    rev = ogr.review_group(group_id="g", members=_MEMBERS)
    assert not rev.ok
    assert rev.error == "parse_fail"


def test_canonical_obverse_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ogr, "_DATASETS_DIR", tmp_path)
    (tmp_path / "80").mkdir()
    (tmp_path / "80" / "obverse.jpg").write_bytes(b"x")
    assert ogr.canonical_obverse_path(80) == tmp_path / "80" / "obverse.jpg"
    assert ogr.canonical_obverse_path(None) is None
    assert ogr.canonical_obverse_path(999999) is None  # dossier absent
