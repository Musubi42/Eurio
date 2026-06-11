"""Fixtures partagées des tests bench (best-frame-capture chunk 7)."""

from __future__ import annotations

from pathlib import Path

from bench.session_io import Detection, FrameEvent, RecordedScore

ML_DIR = Path(__file__).resolve().parent.parent
REAL_SESSION = (
    ML_DIR / "bench" / "sessions" / "Pixel9a" / "sessions" / "20260516_140229_e15a"
)


def frame(
    frame_id: int,
    bbox: tuple[float, float, float, float] | None = None,
    method: str = "YOLO",
    conf: float | None = None,
    aggregate: float = 0.9,
    passes_all: bool = True,
    with_score: bool = True,
) -> FrameEvent:
    """Frame synthétique minimale pour les tests trigger/selector."""
    detection = (
        Detection(method=method, bbox=bbox, yolo_conf=conf)
        if bbox is not None or conf is not None
        else None
    )
    score = None
    if with_score:
        score = RecordedScore(
            sharpness=aggregate,
            sharpness_raw=aggregate * 400.0,
            exposure=aggregate,
            mean_luminance=0.5,
            clipping_ratio=0.0,
            completeness=1.0 if passes_all else 0.0,
            motion=None,
            aggregate=aggregate,
            passes={
                "sharpness": True,
                "exposure": True,
                "completeness": passes_all,
                "motion": None,
                "all": passes_all,
            },
        )
    return FrameEvent(
        t=float(frame_id),
        frame_id=frame_id,
        detection=detection,
        score=score,
        arcface_top3=(),
        timings_ms={},
    )
