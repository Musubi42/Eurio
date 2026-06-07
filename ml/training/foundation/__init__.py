"""Foundation embedder utilities — single source of truth for DINOv2.

Used by:
  - eval/confusion_map.py    (a-priori coin similarity / confusion zones)
  - api/distance_logic.py    (aug-vs-real cosine for iteration cards)
  - sources auto-validation  (top-K suggestions on scraped crops)

Re-exports the most common entry-points so callers can write
`from training.foundation import load_encoder, encode_image, top_k_match`.
"""

from training.foundation.anchors import (
    AnchorBank,
    anchor_path,
    build_anchors_2eur_commemo,
    load_anchors,
    save_anchors,
)
from training.foundation.encoder import (
    DEFAULT_ENCODER_VERSION,
    DINOV2_MODEL,
    DINOV2_REPO,
    IMAGENET_MEAN,
    IMAGENET_STD,
    INPUT_SIZE,
    build_transform,
    encode_image,
    encode_paths,
    load_encoder,
    pick_device,
)
from training.foundation.matcher import Match, spread, top_k_match, top_k_match_country

__all__ = [
    "DEFAULT_ENCODER_VERSION",
    "DINOV2_MODEL",
    "DINOV2_REPO",
    "IMAGENET_MEAN",
    "IMAGENET_STD",
    "INPUT_SIZE",
    "AnchorBank",
    "Match",
    "anchor_path",
    "build_anchors_2eur_commemo",
    "build_transform",
    "encode_image",
    "encode_paths",
    "load_anchors",
    "load_encoder",
    "pick_device",
    "save_anchors",
    "spread",
    "top_k_match",
    "top_k_match_country",
]
