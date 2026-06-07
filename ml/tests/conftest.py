"""Shared pytest fixtures for the ml test suite.

Provides a default MinIO stub so tests that exercise the scrape pipeline
(orchestrator, download, detect_crop) don't hit the network or block in
upload_through's 17-min exponential backoff when boto3 is unavailable.

Tests that need to inspect MinIO behavior (test_storage_cascade) override
the stub explicitly via their own monkeypatch.setattr(storage, "_s3_client", ...).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _stub_minio_client(monkeypatch):
    """Replace storage._s3_client with a MagicMock for the test's duration.

    `_client()` short-circuits on a non-None `_s3_client`, so this prevents
    any actual boto3 import or network call. Tests that need a specific
    MinIO behavior reassign `_s3_client` themselves — monkeypatch unwinds
    to the MagicMock on teardown, not None, so the next test stays stubbed.
    """
    from shared import storage
    monkeypatch.setattr(storage, "_s3_client", MagicMock())
