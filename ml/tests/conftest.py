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
def _no_ambient_flip(monkeypatch):
    """Neutralise le flip Direction A ambiant pendant les tests.

    Le devShell (``flake.nix``) exporte ``EURIO_DB_READONLY=1`` et pointe
    ``EURIO_DB_PATH`` sur la réplique. Sans ce delenv, tout ``Store(tmp/…)``
    construit sans ``read_only`` explicite s'ouvre en ``mode=ro`` (le défaut se
    résout sur l'env, cf. ``store/connection.py``) et le test échoue en
    ``attempt to write a readonly database`` — alors que le même test passe hors
    devShell. Le résultat d'un test ne doit pas dépendre du shell qui le lance.

    Constaté le 2026-08-16 : 8 tests (dont 2 antérieurs à ce chantier) passaient
    hors direnv et échouaient dedans. Les tests qui veulent exercer le flip
    posent leur propre ``monkeypatch.setenv`` — qui gagne sur cet autouse.
    """
    monkeypatch.delenv("EURIO_DB_READONLY", raising=False)
    monkeypatch.delenv("EURIO_DB_PATH", raising=False)


@pytest.fixture(autouse=True)
def _stub_minio_client(monkeypatch):
    """Replace storage._s3_client with a MagicMock for the test's duration.

    `_client()` short-circuits on a non-None `_s3_client`, so this prevents
    any actual boto3 import or network call. Tests that need a specific
    MinIO behavior reassign `_s3_client` themselves — monkeypatch unwinds
    to the MagicMock on teardown, not None, so the next test stays stubbed.
    """
    from shared import storage
    client = MagicMock()
    # Un MagicMock nu rend un MagicMock pour `generate_presigned_url()`, que les
    # modèles pydantic des routes refusent (`file_url: str`). Le stub doit rendre
    # le TYPE que rend le vrai client, sinon il déplace la panne au lieu de
    # l'éviter. Les tests qui veulent une URL précise réassignent le client.
    client.generate_presigned_url.return_value = "https://minio.test/stub-url"
    monkeypatch.setattr(storage, "_s3_client", client)
