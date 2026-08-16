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

Bucket = Literal[
    "numista-canonical",
    "enrichment-raws",
    "enrichment-crops",
    # Artefacts de build épinglés par shared/model-assets.json (modèles TFLite,
    # centroïdes, meta). Privé : ce ne sont pas des images publiques.
    # Versionné par la CLÉ d'objet — le versioning S3 est banni côté MinIO
    # (cf. infra/minio/README.md §Anti-patterns).
    "model-artifacts",
]

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
_s3_public_client = None


def _endpoint_url(host: str, use_ssl_default: str = "true", ssl_var: str = "MINIO_USE_SSL") -> str:
    """`MINIO_ENDPOINT` est host-only (ex. « eurio-s3.musubi.dev ») par
    compatibilité SDK (le SDK Go de MinIO refuse un schéma/chemin). boto3 veut
    une URL complète — on la reconstruit ici."""
    if "://" in host:
        return host
    use_ssl = os.environ.get(ssl_var, use_ssl_default).lower() == "true"
    return f"{'https' if use_ssl else 'http'}://{host}"


def _build_client(endpoint: str):
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
        aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
        # Force path-style addressing — virtual-host style requires a
        # wildcard cert per bucket-host, which we don't set up.
        config=Config(s3={"addressing_style": "path"}),
    )


def _client():
    """Lazy boto3 client. Reads creds from env (MINIO_ACCESS_KEY / _SECRET_KEY).

    We instantiate lazily so that importing `ml.storage` doesn't fail when
    creds aren't configured (e.g. unit tests that don't touch MinIO).
    """
    global _s3_client
    if _s3_client is None:
        _s3_client = _build_client(_endpoint_url(os.environ.get("MINIO_ENDPOINT", S3_ENDPOINT)))
    return _s3_client


def _public_client():
    """Client dédié à la **signature d'URLs destinées à un navigateur**.

    Le VPS parle à MinIO par le réseau Docker interne
    (`MINIO_ENDPOINT=eurio-minio:9000`) : une URL présignée avec ce client
    pointe un hôte que le navigateur ne peut pas résoudre. Le symptôme est
    silencieux — l'API répond 200 avec une URL parfaitement formée, et seule
    l'image ne s'affiche pas.

    `MINIO_PUBLIC_ENDPOINT` (défaut : `MINIO_ENDPOINT`) porte l'hôte joignable
    depuis l'extérieur. On ne se repose PAS sur le fait qu'une présignature
    SigV2 ignore l'en-tête Host : ce serait dépendre d'un repli implicite de
    boto3 qu'une mise à jour peut basculer en SigV4, où le Host est signé.
    """
    global _s3_public_client
    if _s3_public_client is None:
        public_host = os.environ.get("MINIO_PUBLIC_ENDPOINT", "").strip()
        if not public_host:
            return _client()
        _s3_public_client = _build_client(
            _endpoint_url(public_host, ssl_var="MINIO_PUBLIC_USE_SSL")
        )
    return _s3_public_client


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
    # `_public_client` : l'URL part vers un navigateur, elle doit porter un hôte
    # joignable depuis l'extérieur (cf. sa docstring).
    return _public_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": storage_key},
        ExpiresIn=expires_seconds,
    )
