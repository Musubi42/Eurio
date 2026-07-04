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


# ── Autopull en tâche de fond (thread daemon du serveur ML local) ────────────


def test_autopull_gated_off_by_env(monkeypatch):
    monkeypatch.setenv("EURIO_REPLICA_AUTOPULL", "0")
    assert replica.start_autopull_thread() is None


def test_autopull_gated_without_rsync(monkeypatch):
    monkeypatch.delenv("EURIO_REPLICA_AUTOPULL", raising=False)
    monkeypatch.setattr(replica, "rsync_available", lambda: False)
    assert replica.start_autopull_thread() is None


def test_autopull_pulls_periodically_and_survives_failures(monkeypatch, tmp_path):
    import threading

    monkeypatch.delenv("EURIO_REPLICA_AUTOPULL", raising=False)
    monkeypatch.setattr(replica, "rsync_available", lambda: True)
    calls = []
    done = threading.Event()

    def _pull(dest=None):
        calls.append(dest)
        if len(calls) == 1:
            raise RuntimeError("réseau coupé")  # le thread ne doit pas mourir
        if len(calls) >= 3:
            done.set()
        return tmp_path / "r.db"

    monkeypatch.setattr(replica, "pull_replica_rsync", _pull)
    t = replica.start_autopull_thread(tmp_path / "r.db", interval_s=1)
    assert t is not None
    assert done.wait(timeout=10), "le thread n'a pas continué après l'échec"
    t.stop_event.set()
    t.join(timeout=5)
    assert len(calls) >= 3  # a survécu à l'échec du 1er pull
    assert (tmp_path / ".replica-last-pull").exists()
