"""S3 keys + local cache paths for source ingestion artifacts.

Le scrape pousse directement dans MinIO via le write-through cache
(`ml.storage.local_cache.upload_through`). Plus de `ml/state/sources/`
filesystem — tout vit dans `~/.cache/eurio/<bucket>/<key>` côté local
et dans MinIO côté autorité.

Convention de clés (alignée sur scripts/migrate_to_minio.py qui reste
en outil utility) :

  raws  : enrichment-raws/{source}/{run_id}/{source_image_id}.{ext}
  crops : enrichment-crops/{source}/{run_id}/{asset_id}.png

Le format des chemins n'a pas vocation à changer après bascule — toute
modification casse les rows DB existantes.
"""

from __future__ import annotations

from pathlib import Path

from shared.storage import Bucket  # noqa: E402
from shared.storage.local_cache import cache_path_for  # noqa: E402


def raw_key(source: str, run_id: str, source_image_id: str,
            ext: str = "jpg") -> str:
    """S3 key for an enrichment-raws object."""
    return f"{source}/{run_id}/{source_image_id}.{ext}"


def crop_key(source: str, run_id: str, asset_id: str) -> str:
    """S3 key for an enrichment-crops object."""
    return f"{source}/{run_id}/{asset_id}.png"


def raw_cache_path(source: str, run_id: str, source_image_id: str,
                   ext: str = "jpg") -> Path:
    """Local cache path corresponding to raw_key()."""
    return cache_path_for("enrichment-raws",
                          raw_key(source, run_id, source_image_id, ext))


def crop_cache_path(source: str, run_id: str, asset_id: str) -> Path:
    """Local cache path corresponding to crop_key()."""
    return cache_path_for("enrichment-crops",
                          crop_key(source, run_id, asset_id))


def bucket_for_raws() -> Bucket:
    return "enrichment-raws"


def bucket_for_crops() -> Bucket:
    return "enrichment-crops"
