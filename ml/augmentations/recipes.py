"""Per-zone augmentation recipes.

Zone semantics come from ``coin_confusion_map.zone`` (see
``ml/confusion_map.py``). Intensity grows from green → orange → red: a
well-isolated design needs fewer/milder augmentations than a quasi-twin pair
where the model must learn invariance to dirt, tilt and lighting.

Layer order matters: ``relighting`` must run *before* ``overlays``. Relighting
simulates how the coin's metal catches a directional light, so it has to be
applied to the clean metal surface. Overlays (dirt, patina, fingerprints)
sit on top as surface contamination — they are not part of the coin's relief
and should not be re-shaded by the synthetic light source.

Relighting is intentionally not enabled for the ``green`` zone: well-isolated
designs don't need it to be learned robustly, and the extra compute would
dominate the per-sample cost for no real gain.

Note: the legacy pipeline (rotation, color jitter, blur, random backgrounds)
is NOT re-declared here. This iteration introduces *additional* layers that
stack on top of the legacy transforms when they are eventually wired into
``train_embedder.py``. Keeping the two concerns separate avoids accidentally
regressing the existing training behavior.
"""

from __future__ import annotations

ZONE_RECIPES: dict[str, dict] = {
    "green": {
        "count": 50,
        "layers": [
            {
                "type": "perspective",
                "max_tilt_degrees": 15,
                "probability": 0.6,
            },
        ],
    },
    "orange": {
        "count": 100,
        "layers": [
            {
                "type": "perspective",
                "max_tilt_degrees": 20,
                "probability": 0.7,
            },
            {
                "type": "relighting",
                "probability": 0.6,
                "ambient": 0.35,
                "max_elevation_deg": 60.0,
                "intensity_range": (0.7, 1.1),
                "normal_strength": 1.3,
            },
            {
                "type": "overlays",
                "categories": ["patina", "dust"],
                "opacity_range": (0.10, 0.30),
                "max_layers": 2,
                "probability": 0.7,
            },
        ],
    },
    "red": {
        "count": 150,
        "layers": [
            {
                "type": "perspective",
                "max_tilt_degrees": 25,
                "probability": 0.8,
            },
            {
                "type": "relighting",
                "probability": 0.7,
                # Smooth aggressively (sigma=5) so that text edges and fine
                # engraving lines don't leak into the normal map — only the
                # coarse relief (portrait bulge, ring/disc boundary on
                # bimetallic coins) contributes to shading.
                "smooth_sigma": 5.0,
                # Weak normal amplification — we're approximating relief from
                # 2D luminance, anything above ~0.8 invents impossible 3D.
                "normal_strength": 0.75,
                # High ambient floor keeps shadows readable; ID features
                # must remain visible on every tile for training to learn them.
                "ambient": 0.55,
                "min_elevation_deg": 25.0,
                "max_elevation_deg": 60.0,
                "intensity_range": (0.85, 1.05),
            },
            {
                "type": "overlays",
                "categories": ["patina", "dust", "scratches", "fingerprints"],
                "opacity_range": (0.15, 0.40),
                "max_layers": 3,
                "probability": 0.85,
            },
        ],
    },
}

DEFAULT_RECIPE: dict = ZONE_RECIPES["orange"]
