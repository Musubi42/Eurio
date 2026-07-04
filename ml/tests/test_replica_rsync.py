"""Transport rsync de la réplique (Direction A — pull incrémental sqlite3_rsync).

Unitaires purs : dispatch auto (rsync préféré, fallback API), wrapper ssh,
propagation d'échec. Le transfert réel est couvert par la vérif live
(runbook replica-auto-sync.md), pas ici.
"""
from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from client import replica  # noqa: E402


def test_rsync_available_requires_binary_and_key(monkeypatch, tmp_path):
    key = tmp_path / "eurio_replica"
    monkeypatch.setattr(replica, "_RSYNC_KEY", key)
    monkeypatch.setattr(replica.shutil, "which", lambda name: "/nix/bin/sqlite3_rsync")
    assert replica.rsync_available() is False  # clé absente
    key.write_text("k")
    assert replica.rsync_available() is True
    monkeypatch.setattr(replica.shutil, "which", lambda name: None)
    assert replica.rsync_available() is False  # binaire absent


def test_auto_falls_back_to_api_when_rsync_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(replica, "rsync_available", lambda: False)
    called = {}
    monkeypatch.setattr(
        replica, "pull_replica",
        lambda dest=None, **kw: called.setdefault("api", dest) or Path("/x"),
    )
    path, mode = replica.pull_replica_auto(tmp_path / "r.db")
    assert mode == "api" and "api" in called


def test_auto_falls_back_to_api_on_rsync_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(replica, "rsync_available", lambda: True)

    def _boom(dest=None):
        raise RuntimeError("réseau coupé")

    monkeypatch.setattr(replica, "pull_replica_rsync", _boom)
    monkeypatch.setattr(replica, "pull_replica", lambda dest=None, **kw: Path("/x"))
    path, mode = replica.pull_replica_auto(tmp_path / "r.db")
    assert mode == "api"


def test_auto_prefers_rsync(monkeypatch, tmp_path):
    monkeypatch.setattr(replica, "rsync_available", lambda: True)
    monkeypatch.setattr(replica, "pull_replica_rsync", lambda dest=None: Path("/r"))
    path, mode = replica.pull_replica_auto(tmp_path / "r.db")
    assert (path, mode) == (Path("/r"), "rsync")


def test_ssh_wrapper_is_executable_and_pins_key(monkeypatch, tmp_path):
    monkeypatch.setattr(replica, "_RSYNC_KEY", Path("/home/u/.ssh/eurio_replica"))
    wrapper = replica._write_ssh_wrapper(tmp_path)
    assert wrapper.stat().st_mode & stat.S_IXUSR
    body = wrapper.read_text()
    assert "/home/u/.ssh/eurio_replica" in body
    assert "BatchMode=yes" in body and "ClearAllForwardings=yes" in body


def test_pull_replica_rsync_raises_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        replica.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 1, stdout="", stderr="boom"),
    )
    with pytest.raises(RuntimeError, match="boom"):
        replica.pull_replica_rsync(tmp_path / "r.db")
