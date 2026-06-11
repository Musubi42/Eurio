"""DINOv2 wrapper — single source of truth.

Owns the model load (lazy, singleton-per-device), the preprocessing
transform, and the encode entry-points. Other consumers
(eval/confusion_map.py, api/distance_logic.py, sources auto-validation)
import from here so the version strings and preprocessing stay in
sync across the codebase.

Deux tailles vivent en prod (bench Phase 2.4, dino-suggestions) :
  - ``dinov2-vits14`` — couche CONSENSUS (seuils C0–C5 calibrés dessus).
  - ``dinov2-vitl14`` — couche SUGGESTIONS (+22 pts recall@1 global,
    4× le coût d'encodage). Même transform 224 / ImageNet pour les deux.

DINOv2 was pretrained with ImageNet normalization and 14-multiple input
sizes; 224 is divisible by 14 and matches the standard eval resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms

logger = logging.getLogger(__name__)

DEFAULT_ENCODER_VERSION = "dinov2-vits14"
SUGGESTIONS_ENCODER_VERSION = "dinov2-vitl14"
DINOV2_REPO = "facebookresearch/dinov2"
DINOV2_MODEL = "dinov2_vits14"

# encoder_version (tracé en DB / .npz) → nom de modèle torch.hub.
ENCODER_HUB_MODELS = {
    "dinov2-vits14": "dinov2_vits14",
    "dinov2-vitl14": "dinov2_vitl14",
}

INPUT_SIZE = 224
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def pick_device() -> torch.device:
    """CUDA on NixOS+NVIDIA, MPS on Apple Silicon, CPU otherwise."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_encoder(
    device: torch.device | None = None,
    *,
    encoder_version: str = DEFAULT_ENCODER_VERSION,
) -> tuple[torch.nn.Module, torch.device]:
    """Load a DINOv2 encoder via torch.hub. First call downloads weights.

    Returns (model, device) — pass ``device=None`` to auto-pick.
    """
    hub_model = ENCODER_HUB_MODELS.get(encoder_version)
    if hub_model is None:
        raise ValueError(
            f"Unknown encoder_version {encoder_version!r} — "
            f"known: {sorted(ENCODER_HUB_MODELS)}"
        )
    if device is None:
        device = pick_device()
    logger.info("Loading DINOv2 encoder (%s) on %s…", hub_model, device)
    model = torch.hub.load(DINOV2_REPO, hub_model, pretrained=True)
    model.eval()
    model.to(device)
    return model, device


def bake_pos_encoding(model: torch.nn.Module, px: int = INPUT_SIZE) -> None:
    """Fige le pos_embed DINOv2 à ``px`` (in-place, idempotent).

    Le checkpoint embarque un pos_embed 518px (1370 tokens) interpolé en
    bicubique à CHAQUE forward — chemin dynamique que torch.export ne
    digère pas (bloquant LiteRT) et coût inutile à résolution fixe. On
    pré-calcule via ``interpolate_pos_encoding`` du modèle lui-même →
    équivalence numérique exacte avec l'eager (validé au spike LiteRT,
    cosine 1.000000). À ré-appliquer après chaque fine-tune AVANT export.
    """
    n_tokens = (px // model.patch_embed.patch_size[0]) ** 2 + 1
    if model.pos_embed.shape[1] == n_tokens:
        return
    dummy = torch.zeros(1, n_tokens, model.embed_dim)
    with torch.no_grad():
        baked = model.interpolate_pos_encoding(dummy, px, px)
    model.pos_embed = torch.nn.Parameter(baked.float())


def build_transform() -> transforms.Compose:
    """Standard ImageNet preprocessing for DINOv2 inputs."""
    return transforms.Compose(
        [
            transforms.Resize(
                INPUT_SIZE, interpolation=transforms.InterpolationMode.BICUBIC
            ),
            transforms.CenterCrop(INPUT_SIZE),
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]
    )


def _load_pil(image: Image.Image | Path | str) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    path = Path(image)
    with Image.open(path) as img:
        return img.convert("RGB")


@torch.no_grad()
def encode_image(
    image: Image.Image | Path | str,
    *,
    encoder: torch.nn.Module | None = None,
    device: torch.device | None = None,
    transform: transforms.Compose | None = None,
) -> np.ndarray:
    """Encode one image into a (D,) float32 L2-normalized vector.

    For repeated calls, pass a pre-loaded ``encoder`` + ``device`` +
    ``transform`` to avoid re-allocating per call.
    """
    if encoder is None or device is None:
        encoder, device = load_encoder(device)
    if transform is None:
        transform = build_transform()

    pil = _load_pil(image)
    tensor = transform(pil).unsqueeze(0).to(device)
    feat = encoder(tensor)
    feat = F.normalize(feat, dim=1)
    return feat.squeeze(0).detach().cpu().numpy().astype(np.float32)


@torch.no_grad()
def encode_paths(
    paths: Iterable[Path | str],
    *,
    encoder: torch.nn.Module | None = None,
    device: torch.device | None = None,
    transform: transforms.Compose | None = None,
    batch_size: int = 32,
) -> tuple[list[Path], np.ndarray]:
    """Batched encode of N images. Returns (kept_paths, matrix (N, D)).

    Paths that fail to load are silently skipped (logged at WARNING)
    and not included in the output. The output matrix is always
    L2-normalized along axis=1.
    """
    if encoder is None or device is None:
        encoder, device = load_encoder(device)
    if transform is None:
        transform = build_transform()

    kept: list[Path] = []
    tensors: list[torch.Tensor] = []
    for p in paths:
        path = Path(p)
        try:
            pil = _load_pil(path)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to load %s: %s", path, exc)
            continue
        tensors.append(transform(pil))
        kept.append(path)

    if not tensors:
        return [], np.zeros((0, 0), dtype=np.float32)

    out: list[np.ndarray] = []
    for i in range(0, len(tensors), batch_size):
        batch = torch.stack(tensors[i : i + batch_size]).to(device)
        feat = encoder(batch)
        feat = F.normalize(feat, dim=1)
        out.append(feat.detach().cpu().numpy().astype(np.float32))
    matrix = np.vstack(out)
    return kept, matrix
