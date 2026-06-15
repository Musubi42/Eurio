"""Stockage **local** des images canoniques du référentiel.

Architecture (acté 2026-05-24, cf. memory ``feedback_architecture_eurio_db_vs_supabase``):
- ``eurio.db`` = source de vérité dev.
- Images canoniques = locales, sous ``ml/canonical_images/{eurio_id}/``.
- Supabase Storage = miroir poussé manuellement, pas écrit pendant le dev.

Layout aligné avec ``coin_image_storage.storage_key`` côté Storage pour
permettre une copie 1:1 lors du push :

    ml/canonical_images/{eurio_id}/{role}_{source_tag}.webp        # detail (400 px)
    ml/canonical_images/{eurio_id}/{role}_{source_tag}_thumb.webp  # thumb (120 px)

Source tag (court, comme côté Storage) : ``numista`` → "numista",
``bce_comm`` → "bce".

Ce module ne sait que lire/écrire des fichiers et calculer des chemins.
La logique métier (quoi télécharger, quand mettre à jour la DB) vit dans
les scripts qui l'appellent.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .coin_image_storage import (
    DETAIL_QUALITY,
    THUMB_QUALITY,
    THUMB_WIDTH,
    encode_webp,
    source_file_tag,
)

logger = logging.getLogger(__name__)

# MinIO bucket servant les canoniques au CDN admin (décision 2026-06-14,
# harmonisation-images). Le FS reste la source de vérité ; ce write-through
# garde le bucket à jour pour le redirect CDN de ``referential_routes``.
# NB : distinct de Supabase ``coin-images`` (publication Android, inchangée).
_MINIO_CANONICAL_BUCKET = "numista-canonical"
_MINIO_CACHE_CONTROL = "public, max-age=604800, immutable"

# Default detail width — l'écran admin affiche les coins en grille 200-300 px
# côté display, on garde 400 px pour la marge d'agrandissement (modal détail).
DETAIL_WIDTH = 400

# Localisation des fichiers — relatif à la racine du repo Eurio.
# Tous les autres modules ML utilisent ``Path(__file__).resolve().parents[1]``
# comme racine ``ml/``. On reste sur la même convention.
_ML_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = _ML_ROOT / "canonical_images"


def canonical_dir_for(eurio_id: str) -> Path:
    return CANONICAL_DIR / eurio_id


def canonical_path(eurio_id: str, role: str, source: str, *, thumb: bool = False) -> Path:
    """Chemin absolu du fichier WebP attendu pour ce (coin, role, source)."""
    tag = source_file_tag(source)
    suffix = "_thumb" if thumb else ""
    return canonical_dir_for(eurio_id) / f"{role}_{tag}{suffix}.webp"


def relative_path(eurio_id: str, role: str, source: str, *, thumb: bool = False) -> str:
    """Chemin relatif au repo (pour stocker dans ``coin_canonical_images.local_path``)."""
    abs_path = canonical_path(eurio_id, role, source, thumb=thumb)
    return str(abs_path.relative_to(_ML_ROOT.parent))


def _mirror_to_minio(path: Path, data: bytes) -> None:
    """Best-effort push d'un WebP canonique vers ``numista-canonical``.

    Clé = chemin relatif à ``CANONICAL_DIR`` (``{eurio_id}/{role}_{tag}.webp``),
    identique à ``scripts.upload_canonicals_to_minio``. Best-effort : toute
    erreur (MinIO down, pas de creds) est loggée mais ne casse PAS l'écriture
    FS, qui reste la source de vérité. Le script d'upload idempotent rattrape
    les éventuels manques (réconciliation).
    """
    key = path.relative_to(CANONICAL_DIR).as_posix()
    try:
        from shared.storage import _client
        _client().put_object(
            Bucket=_MINIO_CANONICAL_BUCKET,
            Key=key,
            Body=data,
            ContentType="image/webp",
            CacheControl=_MINIO_CACHE_CONTROL,
        )
    except Exception as exc:  # noqa: BLE001 — FS reste la source de vérité
        logger.warning(
            "canonical MinIO write-through failed for %s (served from FS, "
            "reconcile via scripts.upload_canonicals_to_minio): %s", key, exc,
        )


def write_variants(
    eurio_id: str,
    role: str,
    source: str,
    raw_bytes: bytes,
    *,
    detail_width: int = DETAIL_WIDTH,
    mirror_to_minio: bool = True,
) -> dict[str, int]:
    """Encode WebP detail + thumb et écrit sur disque. Retourne metadata.

    Idempotent au sens où re-écrire le même fichier produit le même résultat.
    ``mirror_to_minio`` (défaut True) pousse aussi les deux variants vers le
    bucket CDN ``numista-canonical`` (best-effort) ; le passer à False pour les
    tests / runs offline.
    """
    canonical_dir_for(eurio_id).mkdir(parents=True, exist_ok=True)

    detail_bytes, dw, dh = encode_webp(raw_bytes, max_width=detail_width, quality=DETAIL_QUALITY)
    thumb_bytes, _, _ = encode_webp(raw_bytes, max_width=THUMB_WIDTH, quality=THUMB_QUALITY)

    detail_path = canonical_path(eurio_id, role, source)
    thumb_path = canonical_path(eurio_id, role, source, thumb=True)
    detail_path.write_bytes(detail_bytes)
    thumb_path.write_bytes(thumb_bytes)

    if mirror_to_minio:
        _mirror_to_minio(detail_path, detail_bytes)
        _mirror_to_minio(thumb_path, thumb_bytes)

    return {
        "detail_bytes": len(detail_bytes),
        "thumb_bytes": len(thumb_bytes),
        "width": dw,
        "height": dh,
    }


def exists(eurio_id: str, role: str, source: str) -> bool:
    """Tous les variants (detail + thumb) sont présents."""
    return (
        canonical_path(eurio_id, role, source).is_file()
        and canonical_path(eurio_id, role, source, thumb=True).is_file()
    )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()
