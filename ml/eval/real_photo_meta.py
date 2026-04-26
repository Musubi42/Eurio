"""Shared metadata parsing for the real-photo hold-out library.

Filename convention (docs/augmentation-benchmark/real-photo-criteria.md) is
lenient — tokens separated by ``_``, matched against vocabularies for the 5
axes (lighting, background, angle, and optional distance/state). Unknown
tokens are ignored.

Consumed by:
- ``check_real_photos.py`` — validator + manifest writer
- ``evaluate_real_photos.py`` — attaches conditions to PhotoResult for
  per-axis R@1 aggregation
"""

from __future__ import annotations

from dataclasses import dataclass

LIGHTING_VALUES = {
    "natural-direct",
    "natural-diffuse",
    "artificial-warm",
    "artificial-cold",
    "mixed",
}

BACKGROUND_VALUES = {"wood", "cloth", "paper", "metal", "hand"}

ANGLE_VALUES = {"0deg", "15deg", "30deg", "45deg"}

DISTANCE_VALUES = {"close", "medium", "far"}

STATE_VALUES = {"clean", "handled", "dirty", "wet", "specular"}


AXES = ("lighting", "background", "angle", "distance", "state")
AXIS_VOCABULARIES: dict[str, set[str]] = {
    "lighting": LIGHTING_VALUES,
    "background": BACKGROUND_VALUES,
    "angle": ANGLE_VALUES,
    "distance": DISTANCE_VALUES,
    "state": STATE_VALUES,
}


@dataclass(frozen=True)
class PhotoConditions:
    lighting: str | None = None
    background: str | None = None
    angle: str | None = None
    distance: str | None = None
    state: str | None = None

    def to_dict(self) -> dict:
        return {
            "lighting": self.lighting,
            "background": self.background,
            "angle": self.angle,
            "distance": self.distance,
            "state": self.state,
        }

    def session_key(self) -> str:
        """Synthesized session identifier — same (lighting, background)
        counts as one shooting session regardless of angle/distance/state.
        """
        return f"{self.lighting or '?'}|{self.background or '?'}"


def parse_filename(stem: str) -> PhotoConditions:
    """Best-effort 5-axis parse. Returns a `PhotoConditions` with ``None``
    for any axis that didn't match a known vocabulary.
    """
    found: dict[str, str] = {}
    for tok in stem.split("_"):
        for axis, vocab in AXIS_VOCABULARIES.items():
            if axis in found:
                continue
            if tok in vocab:
                found[axis] = tok
                break
    return PhotoConditions(
        lighting=found.get("lighting"),
        background=found.get("background"),
        angle=found.get("angle"),
        distance=found.get("distance"),
        state=found.get("state"),
    )
