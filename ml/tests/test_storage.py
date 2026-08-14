"""Tests for ml.storage and ml.storage.local_cache.

We avoid hitting a real MinIO. The boto3 client is mocked at module level.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared import storage
from shared.storage import (
    bucket_for_asset,
    bucket_for_source_image,
    public_url,
    signed_url,
)


# ─── bucket_for_* ───────────────────────────────────────────────────────────


def test_bucket_for_asset_numista():
    assert bucket_for_asset("numista") == "numista-canonical"


def test_bucket_for_asset_other_sources():
    assert bucket_for_asset("ebay") == "enrichment-crops"
    assert bucket_for_asset("catawiki") == "enrichment-crops"
    assert bucket_for_asset("mock") == "enrichment-crops"


def test_bucket_for_source_image():
    assert bucket_for_source_image() == "enrichment-raws"


# ─── public_url ─────────────────────────────────────────────────────────────


def test_public_url_strips_leading_slash():
    assert public_url("numista/68395/obverse.jpg") == \
        "https://eurio-images.musubi.dev/numista/68395/obverse.jpg"
    assert public_url("/numista/68395/obverse.jpg") == \
        "https://eurio-images.musubi.dev/numista/68395/obverse.jpg"


# ─── signed_url ─────────────────────────────────────────────────────────────


def test_signed_url_rejects_public_bucket():
    with pytest.raises(ValueError, match="public_url"):
        signed_url("numista-canonical", "x.jpg")


def test_signed_url_calls_boto_for_private_bucket():
    fake = MagicMock()
    fake.generate_presigned_url.return_value = "https://signed.example/x"
    with patch.object(storage, "_s3_client", fake):
        url = signed_url("enrichment-crops", "ebay/run-1/asset-1.png", expires_seconds=60)
    assert url == "https://signed.example/x"
    fake.generate_presigned_url.assert_called_once()
    call = fake.generate_presigned_url.call_args
    assert call.kwargs["Params"] == {
        "Bucket": "enrichment-crops",
        "Key": "ebay/run-1/asset-1.png",
    }
    assert call.kwargs["ExpiresIn"] == 60


# ─── local_cache ────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("EURIO_CACHE_ROOT", str(tmp_path))
    monkeypatch.setenv("EURIO_CACHE_MAX_GB", "0")
    # Make sure the lazy boto client we patch is fresh.
    monkeypatch.setattr(storage, "_s3_client", None)
    yield tmp_path


def _make_fake_client(payloads: dict[tuple[str, str], bytes]):
    """Returns a boto-like client whose download_file writes the given bytes."""
    fake = MagicMock()

    def _download(bucket, key, dest):
        if (bucket, key) not in payloads:
            from botocore.exceptions import ClientError
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            )
        Path(dest).write_bytes(payloads[(bucket, key)])

    fake.download_file.side_effect = _download
    return fake


def test_local_path_downloads_first_then_caches(tmp_cache, monkeypatch):
    from shared.storage import local_cache

    fake = _make_fake_client({("enrichment-crops", "ebay/run-1/a.png"): b"hello"})
    monkeypatch.setattr(storage, "_s3_client", fake)

    p1 = local_cache.local_path("enrichment-crops", "ebay/run-1/a.png")
    assert p1.read_bytes() == b"hello"
    assert fake.download_file.call_count == 1

    # Second call should hit the cache, not re-download.
    p2 = local_cache.local_path("enrichment-crops", "ebay/run-1/a.png")
    assert p2 == p1
    assert fake.download_file.call_count == 1


def test_local_path_raises_on_missing(tmp_cache, monkeypatch):
    from shared.storage import local_cache

    fake = _make_fake_client({})  # no payloads = always raise
    monkeypatch.setattr(storage, "_s3_client", fake)

    with pytest.raises(FileNotFoundError, match="enrichment-crops/missing"):
        local_cache.local_path("enrichment-crops", "missing")


def test_local_path_atomic_no_partial_on_failure(tmp_cache, monkeypatch):
    from shared.storage import local_cache

    def _failing(bucket, key, dest):
        Path(dest).write_bytes(b"partial")
        raise RuntimeError("connection died")

    fake = MagicMock()
    fake.download_file.side_effect = _failing
    monkeypatch.setattr(storage, "_s3_client", fake)

    with pytest.raises(FileNotFoundError):
        local_cache.local_path("enrichment-crops", "x")

    # No final file should exist (only the .tmp was created and then unlinked).
    assert not (tmp_cache / "enrichment-crops" / "x").exists()
    assert not (tmp_cache / "enrichment-crops" / "x.tmp").exists()


def test_evict_when_over_cap(tmp_cache, monkeypatch):
    from shared.storage import local_cache

    monkeypatch.setenv("EURIO_CACHE_MAX_GB", str(1 / 1024 / 1024))   # 1 MB cap

    # Pre-populate cache with 3 fake objects of 500 KB each.
    bucket_dir = tmp_cache / "enrichment-crops"
    bucket_dir.mkdir(parents=True)
    payload = b"x" * (500 * 1024)
    files = []
    for i, name in enumerate(("old.png", "mid.png", "new.png")):
        p = bucket_dir / name
        p.write_bytes(payload)
        # atime ascending: old < mid < new
        os.utime(p, (1000.0 + i, 1000.0 + i))
        files.append(p)

    # Trigger an eviction with a fresh download that adds another 500 KB.
    fake = _make_fake_client({("enrichment-crops", "fresh.png"): payload})
    monkeypatch.setattr(storage, "_s3_client", fake)
    local_cache.local_path("enrichment-crops", "fresh.png")

    # `old.png` (oldest atime) should have been evicted to fit under 1 MB.
    assert not files[0].exists(), "oldest file should be evicted"
    assert (bucket_dir / "fresh.png").exists()


def test_cache_stats_empty(tmp_cache):
    from shared.storage.local_cache import cache_stats
    stats = cache_stats()
    assert stats["n_files"] == 0
    assert stats["size_bytes"] == 0


# ─── Casier artefacts : cloisonné de l'éviction des images ───────────────────


def test_image_eviction_never_touches_artifacts(tmp_cache, monkeypatch):
    """Un modèle ne doit JAMAIS être évincé par le plafond des images.

    Régression visée : `_evict_if_needed()` balayait toute la racine du cache.
    Avec les artefacts sous `<root>/artifacts/`, un cache d'images saturé
    supprimait un .tflite requis par le build — panne silencieuse et différée,
    qui ressemble à un bug plutôt qu'à un cache vide.
    """
    from shared.storage import local_cache

    monkeypatch.setenv("EURIO_CACHE_MAX_GB", str(1 / 1024 / 1024))  # 1 MB
    payload = b"x" * (500 * 1024)

    bucket_dir = tmp_cache / "enrichment-crops"
    bucket_dir.mkdir(parents=True)
    images = []
    for i, name in enumerate(("old.png", "mid.png", "new.png")):
        p = bucket_dir / name
        p.write_bytes(payload)
        os.utime(p, (1000.0 + i, 1000.0 + i))
        images.append(p)

    # L'artefact est le plus ANCIEN de tout le cache : sans cloisonnement il
    # serait la première victime du LRU.
    art_dir = tmp_cache / "artifacts" / "models" / "coin_detector" / "abc123def456"
    art_dir.mkdir(parents=True)
    artifact = art_dir / "coin_detector.tflite"
    artifact.write_bytes(payload)
    os.utime(artifact, (1.0, 1.0))

    fake = _make_fake_client({("enrichment-crops", "fresh.png"): payload})
    monkeypatch.setattr(storage, "_s3_client", fake)
    local_cache.local_path("enrichment-crops", "fresh.png")

    assert artifact.exists(), "un artefact ne doit jamais être évincé par le cap images"
    assert not images[0].exists(), "l'image la plus ancienne devait être évincée"


def test_artifact_path_verifies_sha256(tmp_cache, monkeypatch):
    """Un artefact au sha non conforme n'atterrit jamais sur disque."""
    import hashlib

    from shared.storage import local_cache

    payload = b"weights-v1"
    good_sha = hashlib.sha256(payload).hexdigest()
    key = "models/coin_detector/deadbeef/coin_detector.tflite"

    fake = _make_fake_client({(local_cache.ARTIFACTS_BUCKET, key): payload})
    monkeypatch.setattr(storage, "_s3_client", fake)

    path = local_cache.artifact_path(key, sha256=good_sha)
    assert path.read_bytes() == payload
    assert path.parent.parent.parent.parent.name == "artifacts"

    # Même clé, sha attendu différent → refus, et rien de laissé derrière.
    path.unlink()
    with pytest.raises(ValueError, match="sha256 mismatch"):
        local_cache.artifact_path(key, sha256="0" * 64)
    assert not path.exists()
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_artifact_path_redownloads_corrupted_cache(tmp_cache, monkeypatch):
    """Un fichier en cache dont le sha ne correspond plus est retéléchargé."""
    import hashlib

    from shared.storage import local_cache

    payload = b"weights-v2"
    sha = hashlib.sha256(payload).hexdigest()
    key = "models/eurio_embedder_v1/cafe1234/eurio_embedder_v1.tflite"

    stale = tmp_cache / "artifacts" / key
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"corrompu")

    fake = _make_fake_client({(local_cache.ARTIFACTS_BUCKET, key): payload})
    monkeypatch.setattr(storage, "_s3_client", fake)

    assert local_cache.artifact_path(key, sha256=sha).read_bytes() == payload
