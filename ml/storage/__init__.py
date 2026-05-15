"""S3-compatible storage layer for Eurio (MinIO).

The application code never reads/writes MinIO directly. It calls
`local_path(bucket, storage_key)` from `ml.storage.local_cache`, which
handles read-through caching transparently.

Public surface:

- `Bucket`           : Literal type for the 3 bucket names.
- `bucket_for_asset` : derives the bucket of an `image_assets` row from
                       its `source_images.source` value.
- `bucket_for_source_image` : always `enrichment-raws`.
- `public_url`       : URL for a `numista-canonical` object (CDN, no signature).
- `signed_url`       : presigned GET URL for a private bucket object.

See `docs/harmonisation-images/chunk-2-image-keys-schema.md`.
"""

from __future__ import annotations

import os
from typing import Literal

Bucket = Literal["numista-canonical", "enrichment-raws", "enrichment-crops"]

PUBLIC_HOST = "https://eurio-images.musubi.dev"
S3_ENDPOINT = "https://eurio-s3.musubi.dev"

# Default presigned URL TTL (vision §"Décisions actées" #10).
DEFAULT_SIGNED_URL_TTL_SECONDS = 6 * 3600


def bucket_for_asset(source: str) -> Bucket:
    """Bucket for an `image_assets` row, given its `source_images.source`."""
    if source == "numista":
        return "numista-canonical"
    return "enrichment-crops"


def bucket_for_source_image() -> Bucket:
    return "enrichment-raws"


def public_url(storage_key: str) -> str:
    """For `numista-canonical` only. No signature, served via Cloudflare."""
    return f"{PUBLIC_HOST}/{storage_key.lstrip('/')}"


_s3_client = None


def _client():
    """Lazy boto3 client. Reads creds from env (MINIO_ACCESS_KEY / _SECRET_KEY).

    We instantiate lazily so that importing `ml.storage` doesn't fail when
    creds aren't configured (e.g. unit tests that don't touch MinIO).
    """
    global _s3_client
    if _s3_client is None:
        import boto3
        from botocore.client import Config

        _s3_client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("MINIO_ENDPOINT", S3_ENDPOINT),
            aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
            aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
            # Force path-style addressing — virtual-host style requires a
            # wildcard cert per bucket-host, which we don't set up.
            config=Config(s3={"addressing_style": "path"}),
        )
    return _s3_client


def signed_url(
    bucket: Bucket,
    storage_key: str,
    expires_seconds: int = DEFAULT_SIGNED_URL_TTL_SECONDS,
) -> str:
    """Presigned GET URL for a private bucket. Raises for `numista-canonical`."""
    if bucket == "numista-canonical":
        raise ValueError(
            "Use public_url() for numista-canonical (it's anonymous-readable)."
        )
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": storage_key},
        ExpiresIn=expires_seconds,
    )
