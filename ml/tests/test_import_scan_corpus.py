"""Tests Lot 3 — import_scan_corpus (corpus-spec §6/§12).

Chemin nominal (JSONL + frames archivées Lot 2), vérification de hash
(parité capture_id Kotlin↔Python), idempotence, et backfill photo_snaps.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.import_scan_corpus import (
    ImportStats,
    import_archived,
    import_backfill,
)
from store.scan_corpus import ScanCorpusStore


def _jpeg_bytes(color: tuple[int, int, int], size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _png_bytes(color: tuple[int, int, int], size=(224, 224)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _line(**kw) -> dict:
    base = dict(
        schema_version=1,
        test_idx=1,
        iteration_id="iter01",
        bundle_source="lab",
        expected_eurio_id="fr-2018-2eur-simone-veil",
        condition="bright",
        predicted_top3=[
            {"eurio_id": "a", "similarity": 0.7},
            {"eurio_id": "b", "similarity": 0.5},
            {"eurio_id": "c", "similarity": 0.3},
        ],
        predicted_top1="a",
        similarity_top1=0.7,
        is_correct=False,
        is_correct_eq=True,
        error=None,
        ts="2026-07-04T00:53:00.974Z",
        device_model="Pixel 9a",
    )
    base.update(kw)
    return base


@pytest.fixture()
def store(tmp_path: Path) -> ScanCorpusStore:
    return ScanCorpusStore(db_path=tmp_path / "corpus" / "scan_corpus.db")


def _write_archived_frame(frames_dir: Path, raw: bytes, crop: bytes) -> tuple[str, str, str]:
    raw_sha = hashlib.sha256(raw).hexdigest()
    crop_sha = hashlib.sha256(crop).hexdigest()
    cid = raw_sha[:16]
    frames_dir.mkdir(parents=True, exist_ok=True)
    (frames_dir / f"{cid}.raw.jpg").write_bytes(raw)
    (frames_dir / f"{cid}.crop.png").write_bytes(crop)
    return cid, raw_sha, crop_sha


def test_import_archived_nominal(store: ScanCorpusStore, tmp_path: Path) -> None:
    frames = tmp_path / "pull"
    raw, crop = _jpeg_bytes((200, 10, 10)), _png_bytes((10, 200, 10))
    cid, raw_sha, crop_sha = _write_archived_frame(frames, raw, crop)
    line = _line(raw_sha=raw_sha, crop_sha=crop_sha)

    stats = ImportStats()
    import_archived(store, [line], frames, cohort_id="cohort-x", stats=stats)
    assert (stats.inserted, stats.hash_failures) == (1, 0)

    got = store.get_capture(cid)
    assert got is not None
    assert got.eurio_id == "fr-2018-2eur-simone-veil"
    assert got.cohort_id == "cohort-x"
    assert got.source_iteration_id == "iter01"
    assert got.device_model == "Pixel 9a"
    assert (got.crop_w, got.crop_h) == (224, 224)
    # Fichiers copiés content-addressed dans le corpus.
    assert (store.frames_dir / f"{cid}.raw.jpg").read_bytes() == raw
    assert (store.frames_dir / f"{cid}.crop.png").read_bytes() == crop

    # Idempotent : ré-import = update, pas de doublon.
    stats2 = ImportStats()
    import_archived(store, [line], frames, cohort_id="cohort-x", stats=stats2)
    assert (stats2.inserted, stats2.updated) == (0, 1)
    assert store.count() == 1


def test_import_archived_hash_mismatch(store: ScanCorpusStore, tmp_path: Path) -> None:
    frames = tmp_path / "pull"
    raw, crop = _jpeg_bytes((1, 2, 3)), _png_bytes((4, 5, 6))
    cid, raw_sha, crop_sha = _write_archived_frame(frames, raw, crop)
    # Corrompt le raw après coup → le sha JSONL ne matche plus.
    (frames / f"{cid}.raw.jpg").write_bytes(_jpeg_bytes((9, 9, 9)))

    stats = ImportStats()
    import_archived(
        store, [_line(raw_sha=raw_sha, crop_sha=crop_sha)], frames, None, stats
    )
    assert stats.hash_failures == 1
    assert store.count() == 0


def test_import_archived_skips_error_and_no_sha(store: ScanCorpusStore, tmp_path: Path) -> None:
    frames = tmp_path / "pull"
    frames.mkdir()
    stats = ImportStats()
    import_archived(
        store,
        [_line(error="hough_failed"), _line(test_idx=2)],  # pas de raw_sha
        frames,
        None,
        stats,
    )
    assert (stats.skipped_error, stats.skipped_no_sha, store.count()) == (1, 1, 0)


def test_capture_id_parity_kotlin_python(tmp_path: Path) -> None:
    # Parité §12 Lot 2 : capture_id = sha256 des bytes JPEG exacts écrits,
    # hex lowercase tronqué 16 — recalculable côté PC sur le fichier.
    raw = _jpeg_bytes((42, 42, 42))
    f = tmp_path / "x.raw.jpg"
    f.write_bytes(raw)
    assert hashlib.sha256(f.read_bytes()).hexdigest()[:16] == hashlib.sha256(raw).hexdigest()[:16]


def test_import_backfill_matches_by_top3(store: ScanCorpusStore, tmp_path: Path) -> None:
    snaps = tmp_path / "photo_snaps"
    # Deux snaps avec des prédictions distinctes.
    for name, color, sims in (
        ("snap_20260704_005300_974", (200, 0, 0), [0.7116, 0.5979, 0.5106]),
        ("snap_20260704_005311_695", (0, 200, 0), [0.4867, 0.3001, 0.2951]),
    ):
        d = snaps / name
        d.mkdir(parents=True)
        (d / "raw.jpg").write_bytes(_jpeg_bytes(color))
        buf = io.BytesIO()
        Image.new("RGB", (224, 224), color).save(buf, format="JPEG", quality=95)
        (d / "crop.jpg").write_bytes(buf.getvalue())
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "ts": name[5:],
                    "matches": [
                        {"class": c, "sim": s}
                        for c, s in zip(["a", "b", "c"], sims)
                    ],
                }
            )
        )

    lines = [
        _line(
            test_idx=1,
            predicted_top3=[
                {"eurio_id": "a", "similarity": 0.7116},
                {"eurio_id": "b", "similarity": 0.5979},
                {"eurio_id": "c", "similarity": 0.5106},
            ],
        ),
        _line(
            test_idx=2,
            condition="dim",
            ts="2026-07-04T00:53:11.695Z",
            predicted_top3=[
                {"eurio_id": "a", "similarity": 0.4867},
                {"eurio_id": "b", "similarity": 0.3001},
                {"eurio_id": "c", "similarity": 0.2951},
            ],
        ),
    ]
    stats = ImportStats()
    import_backfill(store, lines, snaps, cohort_id="cohort-x", stats=stats)
    assert stats.inserted == 2
    assert stats.skipped_unmatched == 0
    caps = store.list_captures()
    assert {c.condition for c in caps} == {"bright", "dim"}
    for c in caps:
        # capture_id recalculé du raw copié == PK (invariant content-addressed).
        raw_file = store.frames_root / c.raw_path
        assert hashlib.sha256(raw_file.read_bytes()).hexdigest()[:16] == c.capture_id
        # Crop transcodé en PNG 224² + provenance tracée.
        assert c.crop_path.endswith(".crop.png")
        assert c.notes and "backfill" in c.notes


def test_import_backfill_unmatched_line_counted(store: ScanCorpusStore, tmp_path: Path) -> None:
    snaps = tmp_path / "photo_snaps"
    snaps.mkdir()
    stats = ImportStats()
    import_backfill(store, [_line()], snaps, None, stats)
    assert stats.inserted == 0
    assert stats.skipped_unmatched == 1
