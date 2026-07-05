"""Tests Lot 1 — ScanCorpusStore (corpus-spec §12).

Store dédié isolé : création DB, upsert idempotent, filtres, corpus_version.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from store.scan_corpus import (
    ScanCapture,
    ScanCorpusStore,
    capture_id_for,
    corpus_version,
)


def _capture(cid: str = "aabbccdd00112233", **kw) -> ScanCapture:
    defaults = dict(
        capture_id=cid,
        eurio_id="fr-2018-2eur-simone-veil",
        condition="bright",
        captured_at="2026-07-04T00:53:00.974Z",
        raw_path=f"frames/{cid}.raw.jpg",
        crop_path=f"frames/{cid}.crop.png",
        cohort_id="b0299ca0252b",
        source_iteration_id="5bf8edb0ad7d",
        bundle_source="lab",
        raw_w=720,
        raw_h=1280,
        crop_w=224,
        crop_h=224,
        device_model="Pixel 9a",
    )
    defaults.update(kw)
    return ScanCapture(**defaults)


@pytest.fixture()
def store(tmp_path: Path) -> ScanCorpusStore:
    return ScanCorpusStore(db_path=tmp_path / "scan_corpus.db")


def test_creates_db_and_table(store: ScanCorpusStore, tmp_path: Path) -> None:
    assert (tmp_path / "scan_corpus.db").exists()
    tables = {
        r[0]
        for r in store.connection().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "scan_corpus" in tables
    # Frames à côté de la DB custom (isolation tests).
    assert store.frames_dir == tmp_path / "scan_corpus" / "frames"


def test_isolated_from_canonical_stores(tmp_path: Path) -> None:
    # Le store ne doit référencer aucun store canonique (eurio.db / replica /
    # local_state_store) : aucun import vers store.connection / store.__init__.
    import ast

    import store.scan_corpus as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(a.name for a in node.names)
    forbidden = {"store", "store.connection", "local_state_store", "resolve_db_path"}
    assert not (imported & forbidden), imported & forbidden


def test_upsert_idempotent(store: ScanCorpusStore) -> None:
    cap = _capture()
    assert store.upsert_capture(cap) is True
    assert store.upsert_capture(cap) is False
    assert store.count() == 1


def test_upsert_relabels_in_place(store: ScanCorpusStore) -> None:
    store.upsert_capture(_capture())
    store.upsert_capture(_capture(condition="glare", notes="re-label"))
    got = store.get_capture("aabbccdd00112233")
    assert got is not None
    assert got.condition == "glare"
    assert got.notes == "re-label"
    assert store.count() == 1


def test_filters(store: ScanCorpusStore) -> None:
    store.upsert_capture(_capture("aa00000000000001", condition="bright"))
    store.upsert_capture(_capture("aa00000000000002", condition="dim"))
    store.upsert_capture(
        _capture("aa00000000000003", condition="tilt", cohort_id="other-cohort")
    )
    store.upsert_capture(
        _capture(
            "aa00000000000004",
            condition="bright",
            captured_at="2026-08-01T00:00:00.000Z",
        )
    )

    assert len(store.list_captures()) == 4
    assert len(store.list_captures(cohort_id="b0299ca0252b")) == 3
    assert len(store.list_captures(conditions=["bright"])) == 2
    assert len(store.list_captures(conditions=["bright", "dim"])) == 3
    assert (
        len(
            store.list_captures(
                cohort_id="b0299ca0252b", captured_before="2026-07-31T00:00:00.000Z"
            )
        )
        == 2
    )
    assert len(store.list_captures(source_iteration_id="nope")) == 0
    # Tri déterministe par capture_id (base du hash de manifeste §5).
    ids = [c.capture_id for c in store.list_captures()]
    assert ids == sorted(ids)


def test_capture_id_and_corpus_version() -> None:
    raw = b"fake-jpeg-bytes"
    cid = capture_id_for(raw)
    assert len(cid) == 16
    assert cid == capture_id_for(raw)  # déterministe

    v1 = corpus_version(["b", "a"])
    assert v1 == corpus_version(["a", "b"])  # insensible à l'ordre
    assert len(v1) == 12
    assert v1 != corpus_version(["a", "b", "c"])


def test_concurrent_open_same_db(tmp_path: Path) -> None:
    db = tmp_path / "scan_corpus.db"
    s1 = ScanCorpusStore(db_path=db)
    s2 = ScanCorpusStore(db_path=db)
    s1.upsert_capture(_capture())
    assert s2.get_capture("aabbccdd00112233") is not None


def test_row_roundtrip_nullables(store: ScanCorpusStore) -> None:
    minimal = ScanCapture(
        capture_id="ff00000000000000",
        eurio_id="x",
        condition="dim",
        captured_at="2026-07-04T00:00:00Z",
        raw_path="frames/ff00000000000000.raw.jpg",
        crop_path="frames/ff00000000000000.crop.png",
    )
    store.upsert_capture(minimal)
    got = store.get_capture("ff00000000000000")
    assert got == minimal
