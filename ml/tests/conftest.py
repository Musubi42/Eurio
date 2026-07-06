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
def _isolate_local_state_db(monkeypatch, tmp_path):
    """Isole le store d'état local (``eurio.local.db``, bookkeeping cohort_jobs/
    scans) sur un tmp unique PAR TEST. Sans ça, ``local_state_store()`` taperait
    le vrai ``ml/state/eurio.local.db`` → tests non-hermétiques + pollution. Le
    cache par-chemin de ``local_state_store`` rend automatiquement un store frais
    par path unique."""
    monkeypatch.setenv(
        "EURIO_LOCAL_STATE_DB", str(tmp_path / "eurio.local.db"),
    )


@pytest.fixture(autouse=True)
def _no_ambient_canonical(monkeypatch):
    """Neutralise le canonique distant ambiant pendant les tests.

    L'env dev (direnv/SOPS) exporte ``EURIO_API_URL`` vers le VRAI VPS — sans ce
    delenv, les pushes best-effort (F09 : ancrages lab_routes /
    ``iteration_runner._sync_canonical``) partiraient réellement au canonique
    depuis la suite de tests. Les tests qui exercent le gating posent leur propre
    ``monkeypatch.setenv`` (qui gagne sur ce fixture autouse).
    """
    monkeypatch.delenv("EURIO_API_URL", raising=False)
    monkeypatch.delenv("EURIO_API_TOKEN", raising=False)
    monkeypatch.delenv("EURIO_ITERATION_PUSH", raising=False)


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
