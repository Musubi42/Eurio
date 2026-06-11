"""Tests du tooling bench chunk-7 : session_io + moteur de replay.

La session device committée (``_bench_fixtures.REAL_SESSION``, schema v1)
sert de fixture d'intégration ; les sémantiques fines des triggers et du
sélecteur D8 sont verrouillées sur des frames synthétiques — cas miroir des
tests Kotlin ``BestFrameSelectorTest`` / triggers.
"""

from __future__ import annotations

import json

import pytest

from bench import replay as rp
from bench.session_io import (
    BenchConfig,
    GroundTruth,
    SessionParseError,
    iter_session_dirs,
    load_ground_truth,
    load_session,
    save_ground_truth,
)
from tests._bench_fixtures import ML_DIR, REAL_SESSION, frame

requires_session = pytest.mark.skipif(
    not (REAL_SESSION / "events.jsonl").exists(),
    reason="session device committée absente",
)


# ── session_io ───────────────────────────────────────────────────────────────


@requires_session
def test_load_real_session_schema_v1():
    s = load_session(REAL_SESSION, device="Pixel9a")
    assert s.schema_version == 1
    assert s.session_id == "20260516_140229_e15a"
    assert s.duration_ms == 10539
    assert s.dropped_lines == 0
    assert len(s.frames) == 24
    assert s.config is not None
    assert s.config.trigger_mode == "BOX_STABILITY"
    assert s.config.burst_size == 5
    # v1 : la clé arcface s'appelle eurio_id mais porte le label modèle —
    # normalisée en class_name.
    first_with_arcface = next(f for f in s.frames if f.arcface_top3)
    assert first_with_arcface.arcface_top3[0].class_name == "113429"
    # v1 : `seq` (timestamp millis) normalisé en frame_id.
    assert s.frames[0].frame_id == 1778932950066


@requires_session
def test_iter_session_dirs_finds_real_session():
    found = list(iter_session_dirs(ML_DIR / "bench" / "sessions"))
    assert ("Pixel9a", REAL_SESSION) in found


def test_load_session_missing_dir_raises(tmp_path):
    with pytest.raises(SessionParseError):
        load_session(tmp_path)


def test_load_session_rejects_future_schema(tmp_path):
    (tmp_path / "events.jsonl").write_text(
        json.dumps(
            {"evt": "session_start", "t": 0.0, "session_id": "x", "schema_version": 99}
        )
        + "\n"
    )
    with pytest.raises(SessionParseError, match="schema_version 99"):
        load_session(tmp_path)


def test_ground_truth_roundtrip(tmp_path):
    gt = GroundTruth(
        human_best_frame_id=42,
        confirmed_eurio_id="es-2018-2eur-asturias",
        model_top1_correct=True,
        condition="dim",
        notes="léger reflet",
    )
    save_ground_truth(tmp_path, gt)
    loaded = load_ground_truth(tmp_path)
    assert loaded is not None
    assert loaded.human_best_frame_id == 42
    assert loaded.confirmed_eurio_id == "es-2018-2eur-asturias"
    assert loaded.condition == "dim"
    assert loaded.annotator == "raphael"


def test_config_overrides_unknown_key_raises():
    cfg = _config()
    with pytest.raises(SessionParseError, match="inconnu"):
        cfg.with_overrides({"sharpnessMin": 40})  # camelCase = faute typique


def _config(**kwargs) -> BenchConfig:
    base = dict(
        trigger_mode="BOX_STABILITY",
        stability_iou_min=0.7,
        stability_n_frames=3,
        yolo_conf_min=0.5,
        burst_size=5,
        rolling_buffer_enabled=True,
        ae_lock_enabled=True,
        af_lock_enabled=True,
        awb_lock_enabled=True,
        sharpness_min=80.0,
        exposure_band_half_width=0.2,
        completeness_min=0.95,
        motion_enabled=False,
        capture_mode="PREVIEW_ONLY",
    )
    base.update(kwargs)
    return BenchConfig(**base)


# ── Triggers (sémantique miroir Kotlin) ──────────────────────────────────────

BOX = (10.0, 10.0, 110.0, 110.0)
POLICY = rp.policy_from_config(_config())


def _observe_all(trigger, frames):
    fires = []
    buffer = []
    for f in frames:
        rf = rp.rescore_frame(f, POLICY)
        if rf.rescored is not None:
            buffer.append(rf)
            if len(buffer) > 5:
                buffer.pop(0)
        fired = trigger.observe(rf, buffer)
        if fired:
            fires.append(fired)
    return fires


def test_box_stability_fires_after_n_consecutive():
    trigger = rp.BoxStabilityTrigger(iou_min=0.7, n_frames_required=3)
    fires = _observe_all(trigger, [frame(i, bbox=BOX) for i in range(1, 6)])
    assert len(fires) == 1  # firedForRun bloque les fires suivants
    assert fires[0].reason == "stable 3f IoU≥0.70"


def test_box_stability_null_detection_cancels_run():
    trigger = rp.BoxStabilityTrigger(iou_min=0.7, n_frames_required=3)
    frames = [
        frame(1, bbox=BOX),
        frame(2, bbox=BOX),
        frame(3),  # détection perdue → reset
        frame(4, bbox=BOX),
        frame(5, bbox=BOX),
    ]
    assert _observe_all(trigger, frames) == []


def test_box_stability_jumping_bbox_restarts_count():
    far = (300.0, 300.0, 400.0, 400.0)
    trigger = rp.BoxStabilityTrigger(iou_min=0.7, n_frames_required=3)
    frames = [
        frame(1, bbox=BOX),
        frame(2, bbox=far),  # IoU 0 → consecutive repart à 1
        frame(3, bbox=far),
        frame(4, bbox=far),
    ]
    fires = _observe_all(trigger, frames)
    assert len(fires) == 1  # 3 frames consécutives sur `far`


def test_yolo_confidence_silent_on_hough():
    trigger = rp.YoloConfidenceTrigger(conf_min=0.5, n_frames_required=2)
    frames = [
        frame(1, bbox=BOX, method="YOLO", conf=0.9),
        frame(2, bbox=BOX, method="HOUGH", conf=0.9),  # reset
        frame(3, bbox=BOX, method="YOLO", conf=0.9),
        frame(4, bbox=BOX, method="YOLO", conf=0.9),
    ]
    fires = _observe_all(trigger, frames)
    assert len(fires) == 1
    assert fires[0].reason == "yolo 2f conf≥0.50"


def test_iou_degenerate_boxes_never_nan():
    assert rp.iou((0, 0, 0, 0), (0, 0, 0, 0)) == 0.0
    assert rp.iou(BOX, BOX) == 1.0


# ── Sélecteur D8 ─────────────────────────────────────────────────────────────


def _replay_frames(frames):
    return [rp.rescore_frame(f, POLICY) for f in frames]


def test_selector_picks_oldest_qualifier():
    snapshot = _replay_frames(
        [
            frame(1, aggregate=0.6, passes_all=False),
            frame(2, aggregate=0.7, passes_all=True),  # plus ancien qualifié
            frame(3, aggregate=0.99, passes_all=True),  # meilleur mais plus récent
        ]
    )
    sel = rp.select_best_frame(snapshot)
    assert sel is not None
    assert sel.frame.frame_id == 2
    assert sel.reason == "PASSED_ALL_GATES"


def test_selector_falls_back_to_max_aggregate():
    snapshot = _replay_frames(
        [
            frame(1, aggregate=0.6, passes_all=False),
            frame(2, aggregate=0.8, passes_all=False),
            frame(3, aggregate=0.7, passes_all=False),
        ]
    )
    sel = rp.select_best_frame(snapshot)
    assert sel is not None
    assert sel.frame.frame_id == 2
    assert sel.reason == "BEST_AGGREGATE_FALLBACK"


def test_selector_empty_returns_none():
    assert rp.select_best_frame([]) is None


# ── Replay end-to-end sur la session réelle ──────────────────────────────────


@requires_session
def test_replay_recorded_config_fires_like_device():
    s = load_session(REAL_SESSION)
    result = rp.replay(s)
    # Le device a enregistré exactement 1 trigger_fire box_stability ; le
    # replay sous la même config doit retrouver un fire box_stability (la
    # reason enregistrée "IoU≥0,70" vient d'un format Kotlin locale FR,
    # corrigé en Locale.US — on ne compare donc pas les strings).
    assert len(result.fires) >= 1
    assert result.fires[0]["reason"].startswith("stable 3f")
    sel = result.fires[0]["selection"]
    assert sel is not None
    assert sel["frame_id"] in [f.frame_id for f in s.frames]


@requires_session
def test_replay_override_changes_gates(tmp_path):
    s = load_session(REAL_SESSION)
    strict = s.config.with_overrides({"sharpness_min": 1e9})
    result = rp.replay(s, strict)
    # Aucune frame ne peut passer un sharpness_min impossible → toute
    # sélection est un fallback aggregate.
    for fire in result.fires:
        if fire["selection"]:
            assert fire["selection"]["selection_reason"] == "BEST_AGGREGATE_FALLBACK"
    rate = result.gates_pass_rate()
    assert rate == 0.0

    out = rp.write_replay_jsonl(s, result, tmp_path / "shadow.jsonl")
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert lines[0]["evt"] == "replay_start"
    assert lines[-1]["evt"] == "replay_summary"
    assert lines[-1]["gates_pass_rate"] == 0.0


@requires_session
def test_replay_default_matches_recorded_pass_rate():
    """Sous la config enregistrée, les gates recalculés == gates enregistrés."""
    s = load_session(REAL_SESSION)
    result = rp.replay(s)
    recorded = [f for f in s.frames if f.score is not None]
    rescored = {f.frame_id: f.rescored for f in result.frames if f.rescored}
    for f in recorded:
        assert rescored[f.frame_id].passes_all == f.score.passes["all"], (
            f"frame {f.frame_id}"
        )


def test_replay_requires_config():
    # Construction directe : Session sans config → erreur explicite.
    from bench.session_io import Session

    empty = Session(
        session_id="x",
        device=None,
        path=REAL_SESSION,
        schema_version=2,
        coin=None,
        condition=None,
        config=None,
        device_info={},
        events=[],
        frames=[],
        duration_ms=None,
        dropped_lines=None,
    )
    with pytest.raises(ValueError, match="sans config_snapshot"):
        rp.replay(empty)
