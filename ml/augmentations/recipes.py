"""Per-zone augmentation recipes — Phase 2 (Monde A) edition.

Phase 2 (docs/scan-normalization/) flips the augmentation strategy: the heavy
lifting moves to ``scan.normalize_snap`` which produces a tight 224×224 coin
crop on a black background, run identically over studio sources at training
time and over phone snaps at inference. With train/inference perfectly
geometrically aligned, the augmentation pipeline only needs to cover camera
nuisance variability — rotation, color, blur, perspective residue, scale
residue. All of that is now expressed at the torchvision-transform level
(``train_embedder.get_train_transforms``).

The legacy recipe layers (background palette, relighting, overlays) are
removed:
- ``background``: dead — the alpha mask in normalize_snap fixes the bg color.
- ``relighting``: out of D2 scope; can be re-introduced later if ColorJitter
  alone proves insufficient.
- ``overlays``: same — surface-contamination simulation isn't needed until
  we observe the model failing on dirty real coins, which we can't measure
  until detection works at all.

The zone gradation (green/orange/red ``count``) is preserved so red-zone
twins still get more virtual samples per epoch than well-isolated green-zone
classes — confusion-aware sample budgeting outlives the layer redesign.
"""

from __future__ import annotations

ZONE_RECIPES: dict[str, dict] = {
    "green":  {"count": 50,  "layers": []},
    "orange": {"count": 100, "layers": []},
    "red":    {"count": 150, "layers": []},
}

DEFAULT_RECIPE: dict = ZONE_RECIPES["orange"]
