"""Tracker de quota d'API — emplacement de la DB et reprise des compteurs (B1).

Le bug d'origine : le compteur s'écrivait dans un `eurio.db` codé en dur pendant
que les lecteurs interrogeaient le Store canonique. La correction déplace le
compteur vers la DB locale inscriptible et fait lire les lecteurs par le même
tracker. Ces tests couvrent la partie qui n'a pas d'endpoint pour la trahir :
la résolution du chemin et la reprise de l'ancien fichier.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import shared.api_quota as api_quota  # noqa: E402
from shared.api_quota import QuotaTracker  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_schema_guard():
    """`ensure_schema` mémorise les chemins déjà provisionnés au niveau process."""
    api_quota._schema_ready.clear()
    yield
    api_quota._schema_ready.clear()


def _make_legacy(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE api_call_log ("
        " source TEXT NOT NULL, key_hash TEXT NOT NULL DEFAULT '',"
        " window TEXT NOT NULL, period TEXT NOT NULL,"
        " calls INTEGER NOT NULL DEFAULT 0, exhausted INTEGER NOT NULL DEFAULT 0,"
        " last_call_at TEXT,"
        " PRIMARY KEY (source, key_hash, window, period))"
    )
    conn.executemany("INSERT INTO api_call_log VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_default_db_is_the_writable_local_state_db(tmp_path, monkeypatch):
    """Jamais le canonique : Mac/PC n'en ont qu'une réplique read-only, y écrire
    un compteur échouerait."""
    target = tmp_path / "eurio.local.db"
    monkeypatch.setenv("EURIO_LOCAL_STATE_DB", str(target))
    assert api_quota.default_db_path() == target
    assert QuotaTracker("ebay", "daily", 5000).db_path == target


def test_record_and_total_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("EURIO_LOCAL_STATE_DB", str(tmp_path / "q.db"))
    tracker = QuotaTracker("ebay", "daily", 5000)
    for _ in range(4):
        tracker.record()
    total = tracker.total()
    assert total.calls == 4
    assert total.remaining == 4996


def test_legacy_counters_are_imported_once(tmp_path, monkeypatch):
    """Le cœur de la reprise : sans elle, le mois Numista en cours repart à zéro
    et le KeyManager surconsomme les 8 clés jusqu'au 429.

    Ce test aurait attrapé la première version du correctif, où l'ATTACH utilisait
    un nom de fichier URI sur une connexion sans `uri=True` : il échouait toujours
    et l'exception était avalée — l'import ne faisait donc jamais rien.
    """
    legacy = tmp_path / "legacy.db"
    _make_legacy(legacy, [
        ("numista", "aaa", "monthly", "2026-08", 1500, 0, "2026-08-01T00:00:00Z"),
        ("numista", "bbb", "monthly", "2026-08", 200, 0, "2026-08-01T00:00:00Z"),
        ("ebay", "", "daily", "2026-08-16", 4733, 0, "2026-08-16T00:00:00Z"),
    ])
    monkeypatch.setattr(api_quota, "_LEGACY_DB", legacy)
    target = tmp_path / "q.db"
    monkeypatch.setenv("EURIO_LOCAL_STATE_DB", str(target))

    api_quota.ensure_schema()

    with sqlite3.connect(target) as conn:
        rows = conn.execute(
            "SELECT source, key_hash, calls FROM api_call_log ORDER BY source, key_hash"
        ).fetchall()
    assert rows == [("ebay", "", 4733), ("numista", "aaa", 1500), ("numista", "bbb", 200)]


def test_legacy_import_never_overwrites_and_is_replayable(tmp_path, monkeypatch):
    """`INSERT OR IGNORE` : une ligne déjà présente gagne, et rejouer est un no-op."""
    # ⚠️ La période DOIT être celle du jour courant, calculée comme le fait
    # `QuotaTracker._period()` (`datetime.now(UTC)`). Ce test a longtemps codé
    # `'2026-08-16'` en dur : `record()` écrivant sous la date du jour, il ne
    # pouvait passer QUE le 2026-08-16, et il est devenu rouge à perpétuité au
    # changement de date — sans que rien ne signale qu'il avait cessé de tester
    # la fusion legacy. Même famille que le reste du catalogue `eurio-verify`.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    legacy = tmp_path / "legacy.db"
    _make_legacy(legacy, [("ebay", "", "daily", today, 4733, 0, "x")])
    monkeypatch.setattr(api_quota, "_LEGACY_DB", legacy)
    target = tmp_path / "q.db"
    monkeypatch.setenv("EURIO_LOCAL_STATE_DB", str(target))

    api_quota.ensure_schema()
    tracker = QuotaTracker("ebay", "daily", 5000, db_path=target)
    tracker.record()                       # 4733 → 4734, valeur locale plus fraîche

    api_quota._schema_ready.clear()
    api_quota.ensure_schema()              # rejoué : ne doit pas ramener 4733

    with sqlite3.connect(target) as conn:
        (calls,) = conn.execute(
            "SELECT calls FROM api_call_log WHERE source='ebay' AND period=?",
            (today,),
        ).fetchone()
    assert calls == 4734


def test_ensure_schema_survives_an_unreadable_legacy_file(tmp_path, monkeypatch):
    """Un legacy corrompu ne doit jamais empêcher le tracker de démarrer — sinon
    une panne de reprise coupe tous les appels eBay et Numista."""
    legacy = tmp_path / "legacy.db"
    legacy.write_bytes(b"ceci n'est pas une base SQLite")
    monkeypatch.setattr(api_quota, "_LEGACY_DB", legacy)
    monkeypatch.setenv("EURIO_LOCAL_STATE_DB", str(tmp_path / "q.db"))

    api_quota.ensure_schema()              # ne doit pas lever
    QuotaTracker("ebay", "daily", 5000).record()
