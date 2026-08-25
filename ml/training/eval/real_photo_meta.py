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

# ⚠️ DEUX vocabulaires cohabitent ici, et c'est délibéré.
#
# Le premier (``natural-direct``, ``wood``, ``0deg``…) vient de la convention
# décrite dans ``docs/augmentation-benchmark/real-photo-criteria.md``, pour la
# librairie manuelle ``ml/data/real_photos/`` — répertoire qui n'existe plus.
#
# Le second est celui que les pulls device utilisent RÉELLEMENT
# (``bright_plain``, ``dim``, ``oblique``, ``glare_specular``…). Il manquait, et
# son absence était muette : mesuré le 2026-08-25, ``parse_filename`` rendait
# ``None`` sur TOUS les axes pour 9 des 11 noms d'étape du corpus device. La
# ventilation ``per_condition`` du benchmark (``evaluate_real_photos.py:661``)
# était donc vide — on photographiait sous trois éclairages sans jamais pouvoir
# noter par éclairage.
LIGHTING_VALUES = {
    # convention real-photos (legacy)
    "natural-direct",
    "natural-diffuse",
    "artificial-warm",
    "artificial-cold",
    "mixed",
    # convention device (pulls avril et juin 2026)
    "bright",
    "dim",
    "daylight",
    "glare",
}

BACKGROUND_VALUES = {
    "wood", "cloth", "paper", "metal", "hand",   # legacy
    "plain", "textured",                          # device
}

ANGLE_VALUES = {
    "0deg", "15deg", "30deg", "45deg",   # legacy
    "oblique", "tilt",                    # device
}

DISTANCE_VALUES = {"close", "medium", "far"}

STATE_VALUES = {"clean", "handled", "dirty", "wet", "specular"}

# Position de la pièce dans le cadre — protocole de juin 2026 (5 conditions
# × 4 positions). Absent = position centrale implicite du protocole d'avril.
POSITION_VALUES = {"p1", "p2", "p3"}

# Protocole de prise de vue. Porté par le PREMIER token du nom de fichier, posé
# par ``vision.sync_eval_real``. Il existe parce que deux pulls partagent des
# noms d'étape (``bright_plain`` et ``bright_textured`` sont dans les deux) :
# sans lui, cumuler les deux corpus écraserait silencieusement les photos
# d'avril. Il permet aussi de noter chaque protocole séparément.
PROTOCOL_VALUES = {"proto-2026-04", "proto-2026-06"}


AXES = (
    "lighting", "background", "angle", "distance", "state",
    "position", "protocol",
)
AXIS_VOCABULARIES: dict[str, set[str]] = {
    "lighting": LIGHTING_VALUES,
    "background": BACKGROUND_VALUES,
    "angle": ANGLE_VALUES,
    "distance": DISTANCE_VALUES,
    "state": STATE_VALUES,
    "position": POSITION_VALUES,
    "protocol": PROTOCOL_VALUES,
}


@dataclass(frozen=True)
class PhotoConditions:
    lighting: str | None = None
    background: str | None = None
    angle: str | None = None
    distance: str | None = None
    state: str | None = None
    position: str | None = None
    protocol: str | None = None

    def to_dict(self) -> dict:
        return {
            "lighting": self.lighting,
            "background": self.background,
            "angle": self.angle,
            "distance": self.distance,
            "state": self.state,
            "position": self.position,
            "protocol": self.protocol,
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
        position=found.get("position"),
        protocol=found.get("protocol"),
    )
