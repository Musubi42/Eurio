"""Tests du lease cross-machine eurio.db (refacto ML chunk 6a).

Faux client S3 en mémoire modélisant la sémantique ``IfNoneMatch='*'`` (création
atomique) et les erreurs ``NoSuchKey`` — ça couvre la logique de verrou sans
toucher MinIO ni le réseau.
"""

from __future__ import annotations

import io
import json
import socket

import pytest
from botocore.exceptions import ClientError

from store import lease


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    # ── put / get / delete ────────────────────────────────────────────────
    def put_object(self, *, Bucket, Key, Body, IfNoneMatch=None):  # noqa: N803
        if IfNoneMatch == "*" and Key in self.objects:
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed"},
                 "ResponseMetadata": {"HTTPStatusCode": 412}},
                "PutObject",
            )
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode()
        return {}

    def get_object(self, *, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey"}}, "GetObject"
            )
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)
        return {}

    # ── file helpers ──────────────────────────────────────────────────────
    def upload_file(self, filename, Bucket, Key):  # noqa: N803
        with open(filename, "rb") as fh:
            self.objects[Key] = fh.read()

    def download_file(self, Bucket, Key, filename):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        with open(filename, "wb") as fh:
            fh.write(self.objects[Key])


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirige DB + marqueur vers tmp et injecte un FakeS3 partagé."""
    db = tmp_path / "state" / "eurio.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"local-db-v1")
    marker = tmp_path / "state" / ".eurio.db.lease"
    monkeypatch.setattr(lease, "_DB_PATH", db)
    monkeypatch.setattr(lease, "_MARKER", marker)
    fake = FakeS3()
    monkeypatch.setattr(lease, "_s3", lambda: fake)
    # checkpoint WAL est un no-op utile ici (fichier non-sqlite) → on le neutralise
    monkeypatch.setattr(lease, "_wal_checkpoint", lambda p: None)
    return fake, db, marker


def test_acquire_on_empty_bucket_posts_lock_and_marker(env):
    fake, db, marker = env
    assert lease.acquire() == 0
    assert lease.LOCK_KEY in fake.objects
    assert marker.exists()
    held = json.loads(fake.objects[lease.LOCK_KEY])
    assert held["holder_host"] == socket.gethostname()


def test_second_acquire_is_refused_when_other_holds(env, monkeypatch):
    fake, db, marker = env
    # un autre host tient déjà le verrou, pas de marqueur local
    fake.objects[lease.LOCK_KEY] = json.dumps(
        {"holder_host": "other-machine", "pid": 999, "acquired_at": "x"}
    ).encode()
    assert lease.acquire() == 2  # refusé
    assert not marker.exists()


def test_acquire_pulls_remote_when_diverging(env):
    import hashlib
    fake, db, marker = env
    fake.objects[lease.DB_KEY] = b"remote-db-v2"
    fake.objects[lease.SHA_KEY] = hashlib.sha256(b"remote-db-v2").hexdigest().encode()
    assert lease.acquire() == 0
    assert db.read_bytes() == b"remote-db-v2"  # pull effectué


def test_acquire_skips_pull_when_sha_matches(env):
    import hashlib
    fake, db, marker = env
    fake.objects[lease.DB_KEY] = b"different-bytes"  # ne doit PAS être pull
    fake.objects[lease.SHA_KEY] = hashlib.sha256(db.read_bytes()).hexdigest().encode()
    assert lease.acquire() == 0
    assert db.read_bytes() == b"local-db-v1"  # inchangé, pas de pull


def test_acquire_integrity_failure_keeps_lock_and_local(env):
    fake, db, marker = env
    fake.objects[lease.DB_KEY] = b"remote-db-v2"
    fake.objects[lease.SHA_KEY] = b"deadbeef" * 8  # sha faux
    assert lease.acquire() == 3
    assert db.read_bytes() == b"local-db-v1"  # local intact


def test_release_requires_holding(env):
    fake, db, marker = env
    # personne ne tient → release refusé
    assert lease.release() == 2


def test_acquire_then_release_roundtrip(env):
    import hashlib
    fake, db, marker = env
    assert lease.acquire() == 0
    db.write_bytes(b"local-db-edited")  # on bosse
    assert lease.release() == 0
    assert lease.LOCK_KEY not in fake.objects  # verrou retiré
    assert not marker.exists()
    assert fake.objects[lease.DB_KEY] == b"local-db-edited"  # push
    assert fake.objects[lease.SHA_KEY].decode() == hashlib.sha256(
        b"local-db-edited").hexdigest()


def test_steal_requires_force(env):
    fake, db, marker = env
    fake.objects[lease.LOCK_KEY] = json.dumps(
        {"holder_host": "crashed", "pid": 1, "acquired_at": "x"}
    ).encode()
    assert lease.steal(force=False) == 2
    assert lease.LOCK_KEY in fake.objects  # toujours là
    assert lease.steal(force=True) == 0
    assert lease.LOCK_KEY not in fake.objects  # volé


def test_idempotent_acquire_when_already_holding(env):
    fake, db, marker = env
    assert lease.acquire() == 0
    # ré-acquérir ne re-pull pas / ne casse pas
    assert lease.acquire() == 0


def test_startup_warns_when_other_holds(env):
    fake, db, marker = env
    fake.objects[lease.LOCK_KEY] = json.dumps(
        {"holder_host": "other-machine", "pid": 9, "acquired_at": "t0"}
    ).encode()
    msgs = lease.startup_warnings()
    assert any("verrou tenu par other-machine" in m for m in msgs)


def test_startup_warns_on_divergence_without_lease(env):
    import hashlib
    fake, db, marker = env
    fake.objects[lease.SHA_KEY] = hashlib.sha256(b"remote-different").hexdigest().encode()
    msgs = lease.startup_warnings()
    assert any("diverge du distant" in m for m in msgs)


def test_startup_silent_when_we_hold_and_synced(env):
    fake, db, marker = env
    assert lease.acquire() == 0  # on tient le lease, pas de DB distante
    assert lease.startup_warnings() == []


def test_startup_silent_when_minio_unreachable(env, monkeypatch):
    def boom():
        raise RuntimeError("no MINIO_ACCESS_KEY")
    monkeypatch.setattr(lease, "_s3", boom)
    assert lease.startup_warnings() == []
