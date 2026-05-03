"""Tests pour le bootstrap de la table coins (D-20 / phase 3.A.0).

Vérifie : (1) 2 runs successifs sur DB temp produisent 2628 rows constants
(idempotence par INSERT OR REPLACE), (2) l'update d'une entrée JSON est
reflété au re-run (sans création de doublon), (3) la vue v_ebay_freshness
retourne bien les ~466 commémos 2€ non-EU avec last_enriched_at NULL au
démarrage.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.bootstrap_coins_from_referential import bootstrap
from state.store import Store


def _fixture_referential(tmp_path: Path, entries: list[dict]) -> Path:
    """Écrit un JSON minimal au format eurio_referential."""
    path = tmp_path / "ref.json"
    payload = {
        "schema_version": 1,
        "generated_at": "2026-05-03T00:00:00Z",
        "entry_count": len(entries),
        "entries": entries,
    }
    path.write_text(json.dumps(payload))
    return path


def test_bootstrap_real_referential_idempotent(tmp_path: Path) -> None:
    """Run 2× sur le vrai JSON → 2628 rows, pas de doublons."""
    db = tmp_path / "test.db"
    store = Store(db)
    real_json = Path(__file__).resolve().parents[1] / "datasets" / "eurio_referential.json"

    summary1 = bootstrap(store, json_path=real_json)
    summary2 = bootstrap(store, json_path=real_json)

    assert summary1["n_inserted_or_replaced"] == summary2["n_inserted_or_replaced"]
    n = store._connection().execute("SELECT count(*) FROM coins").fetchone()[0]  # noqa: SLF001
    assert n == summary1["n_entries_total"]
    assert n == 2628


def test_bootstrap_dry_run_writes_nothing(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    store = Store(db)
    real_json = Path(__file__).resolve().parents[1] / "datasets" / "eurio_referential.json"

    summary = bootstrap(store, json_path=real_json, dry_run=True)
    assert summary["dry_run"] is True
    assert summary["n_inserted_or_replaced"] == 0

    n = store._connection().execute("SELECT count(*) FROM coins").fetchone()[0]  # noqa: SLF001
    assert n == 0


def test_bootstrap_replaces_on_update(tmp_path: Path) -> None:
    """Si une entrée change dans le JSON, le re-bootstrap reflète le changement."""
    db = tmp_path / "test.db"
    store = Store(db)

    entry = {
        "eurio_id": "fr-2eur-2002-standard",
        "identity": {
            "country": "FR",
            "country_name": "France",
            "year": 2002,
            "face_value": 2.0,
            "is_commemorative": False,
            "theme": None,
        },
        "cross_refs": {"numista_id": 789},
    }
    json_path = _fixture_referential(tmp_path, [entry])
    bootstrap(store, json_path=json_path)

    row = (
        store._connection()  # noqa: SLF001
        .execute("SELECT theme, numista_id FROM coins WHERE eurio_id = ?", (entry["eurio_id"],))
        .fetchone()
    )
    assert row["numista_id"] == 789

    entry["identity"]["theme"] = "World Cup 2026 commemorative"
    entry["identity"]["is_commemorative"] = True
    entry["cross_refs"]["numista_id"] = 999
    json_path.write_text(
        json.dumps({"schema_version": 1, "entries": [entry]})
    )
    bootstrap(store, json_path=json_path)

    row = (
        store._connection()  # noqa: SLF001
        .execute(
            "SELECT theme, numista_id, is_commemorative FROM coins WHERE eurio_id = ?",
            (entry["eurio_id"],),
        )
        .fetchone()
    )
    assert row["theme"] == "World Cup 2026 commemorative"
    assert row["numista_id"] == 999
    assert row["is_commemorative"] == 1

    n = store._connection().execute("SELECT count(*) FROM coins").fetchone()[0]  # noqa: SLF001
    assert n == 1, "INSERT OR REPLACE devrait conserver une seule row"


def test_v_ebay_freshness_returns_2eur_commemos_non_eu(tmp_path: Path) -> None:
    """La vue v_ebay_freshness filtre sur (face_value=2, is_commemorative=1, country!='eu')."""
    db = tmp_path / "test.db"
    store = Store(db)

    entries = [
        {
            "eurio_id": "fr-2eur-2015-paix",
            "identity": {
                "country": "FR", "year": 2015, "face_value": 2.0,
                "is_commemorative": True, "theme": "70 ans paix",
            },
            "cross_refs": {},
        },
        {
            "eurio_id": "de-1eur-2010-standard",
            "identity": {
                "country": "DE", "year": 2010, "face_value": 1.0,
                "is_commemorative": False, "theme": None,
            },
            "cross_refs": {},
        },
        {
            "eurio_id": "eu-2eur-2009-emu",
            "identity": {
                "country": "eu", "year": 2009, "face_value": 2.0,
                "is_commemorative": True, "theme": "EMU",
            },
            "cross_refs": {},
        },
    ]
    bootstrap(store, json_path=_fixture_referential(tmp_path, entries))

    rows = (
        store._connection()  # noqa: SLF001
        .execute("SELECT eurio_id, last_enriched_at, n_images FROM v_ebay_freshness")
        .fetchall()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["eurio_id"] == "fr-2eur-2015-paix"
    assert row["last_enriched_at"] is None
    assert row["n_images"] == 0
