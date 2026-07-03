"""Tests pour le garde-fou C7 (migrations one-shot VPS-only, Direction A).

Vérifie ``scripts._vps_only_guard.guard_vps_only`` :
- no-op quand ni ``EURIO_DB_READONLY`` ni ``EURIO_API_URL`` ne sont configurés
  (VPS canonique, ou dev Model A pur) ;
- refuse (``sys.exit`` non-zéro) quand ``EURIO_DB_READONLY`` est vrai (réplique
  read-only C5) ;
- refuse quand ``EURIO_API_URL`` est configuré (machine cliente forward VPS) ;
- laisse passer si ``allow=True`` (``--i-know-this-is-canonical``), quel que
  soit l'environnement.
"""

from __future__ import annotations

import pytest

from scripts._vps_only_guard import guard_vps_only, is_vps_only_blocked


def test_not_blocked_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EURIO_DB_READONLY", raising=False)
    monkeypatch.delenv("EURIO_API_URL", raising=False)
    assert is_vps_only_blocked() is False
    guard_vps_only("test_script", allow=False)  # ne lève pas


def test_blocked_when_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    monkeypatch.delenv("EURIO_API_URL", raising=False)
    assert is_vps_only_blocked() is True
    with pytest.raises(SystemExit) as exc:
        guard_vps_only("test_script", allow=False)
    assert exc.value.code == 1


def test_blocked_when_api_url_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EURIO_DB_READONLY", raising=False)
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.musubi.dev")
    assert is_vps_only_blocked() is True
    with pytest.raises(SystemExit):
        guard_vps_only("test_script", allow=False)


def test_allow_flag_bypasses_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    monkeypatch.setenv("EURIO_API_URL", "https://eurio-api.musubi.dev")
    guard_vps_only("test_script", allow=True)  # ne lève pas malgré le blocage
