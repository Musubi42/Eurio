"""Foundation embedder utilities — single source of truth for DINOv2.

Used by:
  - eval/confusion_map.py    (a-priori coin similarity / confusion zones)
  - api/distance_logic.py    (aug-vs-real cosine for iteration cards)
  - sources auto-validation  (top-K suggestions on scraped crops)

Re-exports the most common entry-points so callers can write
`from training.foundation import load_encoder, encode_image, top_k_match`.
"""

from training.foundation.anchors import (
    CONSENSUS_ANCHORS_KIND,
    REVERSE_ANCHORS_KIND,
    SUGGESTIONS_ANCHORS_KIND,
    AnchorBank,
    anchor_path,
    build_anchors_2eur_all,
    build_anchors_2eur_commemo,
    build_anchors_2eur_standard,
    build_anchors_reverse_2eur,
    encoder_version_for_kind,
    load_anchors,
    save_anchors,
)
from training.foundation.encoder import (
    DEFAULT_ENCODER_VERSION,
    DINOV2_MODEL,
    DINOV2_REPO,
    ENCODER_HUB_MODELS,
    IMAGENET_MEAN,
    IMAGENET_STD,
    INPUT_SIZE,
    SUGGESTIONS_ENCODER_VERSION,
    bake_pos_encoding,
    build_transform,
    encode_image,
    encode_paths,
    load_encoder,
    pick_device,
)
from training.foundation.matcher import Match, spread, top_k_match, top_k_match_country

__all__ = [
    "CONSENSUS_ANCHORS_KIND",
    "REVERSE_ANCHORS_KIND",
    "DEFAULT_ENCODER_VERSION",
    "DINOV2_MODEL",
    "DINOV2_REPO",
    "ENCODER_HUB_MODELS",
    "IMAGENET_MEAN",
    "IMAGENET_STD",
    "INPUT_SIZE",
    "SUGGESTIONS_ANCHORS_KIND",
    "SUGGESTIONS_ENCODER_VERSION",
    "AnchorBank",
    "Match",
    "anchor_path",
    "bake_pos_encoding",
    "build_anchors_2eur_all",
    "build_anchors_2eur_commemo",
    "build_anchors_2eur_standard",
    "build_anchors_reverse_2eur",
    "build_transform",
    "encode_image",
    "encode_paths",
    "encoder_version_for_kind",
    "load_anchors",
    "load_encoder",
    "pick_device",
    "save_anchors",
    "spread",
    "top_k_match",
    "top_k_match_country",
]
