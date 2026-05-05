"""Tests du step pipeline text_signal_extract (chunk 5 auto-validation).

Pas de Store ici — on utilise une raw connection, le step bascule sur
``_flush_rows_direct`` (chemin tests / backfill standalone).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sources._base.steps.text_signal import (
    EXTRACTOR_VERSION,
    run_text_signal_extract,
)


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "state" / "schema.sql"


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    # Colonnes ajoutées via Store._ensure_column en prod, pas dans
    # schema.sql — répliquées ici pour les tests qui utilisent une raw
    # conn. Doit rester en sync avec store.py::_bootstrap.
    for stmt in (
        "ALTER TABLE source_images ADD COLUMN route_decision TEXT",
        "ALTER TABLE source_images ADD COLUMN route_reason TEXT",
        "ALTER TABLE listing_text_signals ADD COLUMN vs_target_verdict TEXT",
        "ALTER TABLE listing_text_signals "
        "ADD COLUMN contradictions_json TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE listing_text_signals "
        "ADD COLUMN convergences_json TEXT NOT NULL DEFAULT '[]'",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # already exists (schema drift)
    return conn


def _insert_run_and_image(
    conn: sqlite3.Connection,
    *,
    source_image_id: str,
    title: str | None,
    target_eurio_id: str = "ad-2014-2eur-20-years-in-the-council-of-europe",
) -> tuple[str, str]:
    """Insert a minimal source_run + source_image, return (run_id, source_ref)."""
    run_id = "run-test-1"
    source_ref = f"ebay_{source_image_id}_img0"
    conn.execute(
        """
        INSERT INTO source_runs (id, source, kind, status, started_at)
        VALUES (?, ?, 'run', 'success', datetime('now'))
        ON CONFLICT(id) DO NOTHING
        """,
        (run_id, "ebay"),
    )
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, target_eurio_id, listing_title, run_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source_image_id, "ebay", source_ref, target_eurio_id, title, run_id),
    )
    conn.commit()
    return run_id, source_ref


def _insert_coin(
    conn: sqlite3.Connection,
    *,
    eurio_id: str,
    country: str,
    year: int,
    face_value: float = 2.0,
    theme: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative, theme)
        VALUES (?, ?, ?, ?, 1, ?)
        ON CONFLICT(eurio_id) DO NOTHING
        """,
        (eurio_id, country, year, face_value, theme),
    )
    conn.commit()


def test_extract_persists_one_row_per_source_image(conn):
    _, ref = _insert_run_and_image(
        conn,
        source_image_id="sid1",
        title="2 euros Andorre 2016 TV Radio",
    )
    res = run_text_signal_extract(
        conn=conn,
        run=None,
        source_image_ids={ref: "sid1"},
    )
    assert res.n_extracted == 1
    assert res.n_errors == 0

    row = conn.execute(
        "SELECT * FROM listing_text_signals WHERE source_image_id = ?",
        ("sid1",),
    ).fetchone()
    assert row is not None
    assert json.loads(row["countries_json"]) == ["AD"]
    assert json.loads(row["years_json"]) == [2016]
    assert json.loads(row["denominations_json"]) == [2.0]
    assert row["coverage"] == "rich"
    assert row["extractor_version"] == EXTRACTOR_VERSION


def test_idempotent_skips_existing(conn):
    _, ref = _insert_run_and_image(
        conn, source_image_id="sid1",
        title="2 euros Andorre 2016 TV Radio",
    )
    # First pass
    run_text_signal_extract(
        conn=conn, run=None, source_image_ids={ref: "sid1"},
    )
    # Second pass — should skip
    res = run_text_signal_extract(
        conn=conn, run=None, source_image_ids={ref: "sid1"},
    )
    assert res.n_extracted == 0
    assert res.n_skipped_existing == 1


def test_force_recomputes(conn):
    _, ref = _insert_run_and_image(
        conn, source_image_id="sid1",
        title="2 euros Andorre 2016 TV Radio",
    )
    run_text_signal_extract(conn=conn, run=None, source_image_ids={ref: "sid1"})
    res = run_text_signal_extract(
        conn=conn, run=None, source_image_ids={ref: "sid1"}, force=True,
    )
    assert res.n_extracted == 1
    assert res.n_skipped_existing == 0


def test_empty_title_persisted_as_empty_coverage(conn):
    _, ref = _insert_run_and_image(
        conn, source_image_id="sid1", title="",
    )
    res = run_text_signal_extract(
        conn=conn, run=None, source_image_ids={ref: "sid1"},
    )
    assert res.n_extracted == 1
    assert res.n_skipped_empty_title == 1

    row = conn.execute(
        "SELECT coverage, countries_json FROM listing_text_signals WHERE source_image_id = ?",
        ("sid1",),
    ).fetchone()
    assert row["coverage"] == "empty"
    assert json.loads(row["countries_json"]) == []


def test_null_title_handled(conn):
    _, ref = _insert_run_and_image(
        conn, source_image_id="sid1", title=None,
    )
    res = run_text_signal_extract(
        conn=conn, run=None, source_image_ids={ref: "sid1"},
    )
    assert res.n_extracted == 1
    assert res.n_errors == 0


def test_batch_multiple_images(conn):
    _, ref1 = _insert_run_and_image(
        conn, source_image_id="sid1",
        title="2 euros France 2014 Première Guerre",
    )
    conn.execute(
        """
        INSERT INTO source_images (id, source, source_ref, listing_title, run_id)
        VALUES ('sid2', 'ebay', 'ebay_sid2_img0',
                'Lot 2 coins Andorra & France 2 Euro 2023', 'run-test-1')
        """
    )
    conn.execute(
        """
        INSERT INTO source_images (id, source, source_ref, listing_title, run_id)
        VALUES ('sid3', 'ebay', 'ebay_sid3_img0',
                'Belgique 2 Euro 2008 Fauté Désaxé', 'run-test-1')
        """
    )
    conn.commit()

    res = run_text_signal_extract(
        conn=conn, run=None,
        source_image_ids={
            ref1: "sid1",
            "ebay_sid2_img0": "sid2",
            "ebay_sid3_img0": "sid3",
        },
    )
    assert res.n_extracted == 3

    rows = conn.execute(
        "SELECT source_image_id, is_lot, rejected_markers_json FROM listing_text_signals "
        "ORDER BY source_image_id"
    ).fetchall()
    by_id = {r["source_image_id"]: r for r in rows}
    assert by_id["sid1"]["is_lot"] == 0
    assert by_id["sid2"]["is_lot"] == 1
    assert "error_struck" in json.loads(by_id["sid3"]["rejected_markers_json"])


def test_missing_source_image_logged_as_error(conn):
    res = run_text_signal_extract(
        conn=conn, run=None,
        source_image_ids={"missing_ref": "no-such-sid"},
    )
    assert res.n_extracted == 0
    assert res.n_errors == 1


def test_empty_input_returns_zero_result(conn):
    res = run_text_signal_extract(conn=conn, run=None, source_image_ids={})
    assert res.n_extracted == 0
    assert res.n_skipped_existing == 0
    assert res.n_errors == 0


# ── Chunk 6 — verdict vs target persisted ────────────────────────────────────


def test_verdict_convergent_persisted_when_target_matches(conn):
    eurio_id = "ad-2014-2eur-20-years-in-the-council-of-europe"
    _insert_coin(conn, eurio_id=eurio_id, country="AD", year=2014)
    _, ref = _insert_run_and_image(
        conn,
        source_image_id="sid1",
        title="2 euros Andorre 2014 commemorative",
        target_eurio_id=eurio_id,
    )
    run_text_signal_extract(conn=conn, run=None, source_image_ids={ref: "sid1"})

    row = conn.execute(
        "SELECT vs_target_verdict, contradictions_json, convergences_json "
        "  FROM listing_text_signals WHERE source_image_id = ?",
        ("sid1",),
    ).fetchone()
    assert row["vs_target_verdict"] == "convergent"
    assert json.loads(row["contradictions_json"]) == []
    assert set(json.loads(row["convergences_json"])) == {
        "country", "year", "denomination",
    }


def test_verdict_contradict_persisted_on_country_mismatch(conn):
    eurio_id = "fr-2014-2eur-100-years-since-the-start-of-world-war-i"
    _insert_coin(conn, eurio_id=eurio_id, country="FR", year=2014)
    _, ref = _insert_run_and_image(
        conn,
        source_image_id="sid1",
        title="Belgique 2 euros 2014 commémorative",
        target_eurio_id=eurio_id,
    )
    run_text_signal_extract(conn=conn, run=None, source_image_ids={ref: "sid1"})

    row = conn.execute(
        "SELECT vs_target_verdict, contradictions_json "
        "  FROM listing_text_signals WHERE source_image_id = ?",
        ("sid1",),
    ).fetchone()
    assert row["vs_target_verdict"] == "contradict"
    assert "country" in json.loads(row["contradictions_json"])


def test_verdict_null_when_target_missing_from_coins(conn):
    """Target_eurio_id présent sur source_images mais pas dans coins —
    pas de verdict, on persiste juste les signaux. Pas une erreur."""
    _, ref = _insert_run_and_image(
        conn,
        source_image_id="sid1",
        title="2 euros Andorre 2014",
        target_eurio_id="ad-2014-unknown-coin",
    )
    res = run_text_signal_extract(
        conn=conn, run=None, source_image_ids={ref: "sid1"},
    )
    assert res.n_errors == 0

    row = conn.execute(
        "SELECT vs_target_verdict FROM listing_text_signals "
        "WHERE source_image_id = ?",
        ("sid1",),
    ).fetchone()
    assert row["vs_target_verdict"] is None


def test_verdict_null_when_no_target_eurio_id(conn):
    """Pas de target sur source_images → pas de verdict, pas d'erreur."""
    run_id = "run-test-1"
    conn.execute(
        "INSERT INTO source_runs (id, source, kind, status, started_at) "
        "VALUES (?, 'ebay', 'run', 'success', datetime('now'))",
        (run_id,),
    )
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
        "listing_title, run_id) VALUES (?, ?, ?, NULL, ?, ?)",
        ("sid1", "ebay", "ebay_sid1_img0", "2 euros Andorre 2014", run_id),
    )
    conn.commit()

    res = run_text_signal_extract(
        conn=conn, run=None, source_image_ids={"ebay_sid1_img0": "sid1"},
    )
    assert res.n_errors == 0

    row = conn.execute(
        "SELECT vs_target_verdict FROM listing_text_signals "
        "WHERE source_image_id = ?",
        ("sid1",),
    ).fetchone()
    assert row["vs_target_verdict"] is None


def test_verdict_partial_when_country_absent(conn):
    """Titre sans pays détecté mais année + denom convergent → partial."""
    eurio_id = "fr-2014-2eur-test"
    _insert_coin(conn, eurio_id=eurio_id, country="FR", year=2014)
    _, ref = _insert_run_and_image(
        conn,
        source_image_id="sid1",
        title="2 euros 2014 commémorative belle qualité",
        target_eurio_id=eurio_id,
    )
    run_text_signal_extract(conn=conn, run=None, source_image_ids={ref: "sid1"})

    row = conn.execute(
        "SELECT vs_target_verdict FROM listing_text_signals "
        "WHERE source_image_id = ?",
        ("sid1",),
    ).fetchone()
    assert row["vs_target_verdict"] == "partial"


def test_contradict_writes_discarded_and_route_decision(conn):
    """Filtre dur (chunk 6.c) — verdict contradict → discarded_listings
    + route_decision='rejected_text' sur source_images."""
    eurio_id = "fr-2014-2eur-test"
    _insert_coin(conn, eurio_id=eurio_id, country="FR", year=2014)
    _, ref = _insert_run_and_image(
        conn,
        source_image_id="sid1",
        title="Belgique 2 euros 2014 commémorative",
        target_eurio_id=eurio_id,
    )
    res = run_text_signal_extract(
        conn=conn, run=None, source_image_ids={ref: "sid1"},
    )
    assert res.n_rejected_contradict == 1

    # discarded_listings row écrit
    drow = conn.execute(
        "SELECT reason, target_eurio_id, raw_payload FROM discarded_listings "
        "WHERE source_ref = ?",
        (ref,),
    ).fetchone()
    assert drow is not None
    assert drow["reason"] == "text_contradict_country"
    assert drow["target_eurio_id"] == eurio_id
    payload = json.loads(drow["raw_payload"])
    assert "country" in payload["contradictions"]

    # route_decision posé sur source_images
    sirow = conn.execute(
        "SELECT route_decision, route_reason FROM source_images WHERE id = ?",
        ("sid1",),
    ).fetchone()
    assert sirow["route_decision"] == "rejected_text"
    assert sirow["route_reason"] == "country"


def test_no_rejection_on_convergent(conn):
    eurio_id = "fr-2014-2eur-test"
    _insert_coin(conn, eurio_id=eurio_id, country="FR", year=2014)
    _, ref = _insert_run_and_image(
        conn,
        source_image_id="sid1",
        title="France 2 euros 2014 hommage",
        target_eurio_id=eurio_id,
    )
    res = run_text_signal_extract(
        conn=conn, run=None, source_image_ids={ref: "sid1"},
    )
    assert res.n_rejected_contradict == 0
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM discarded_listings WHERE source_ref = ?",
        (ref,),
    ).fetchone()["n"]
    assert n == 0
    sirow = conn.execute(
        "SELECT route_decision FROM source_images WHERE id = ?",
        ("sid1",),
    ).fetchone()
    assert sirow["route_decision"] is None


def test_force_recompute_does_not_duplicate_discarded(conn):
    """Idempotence : recompute via force ne duplique pas les rejets
    text_contradict_*. Le step nettoie d'abord puis ré-écrit."""
    eurio_id = "fr-2014-2eur-test"
    _insert_coin(conn, eurio_id=eurio_id, country="FR", year=2014)
    _, ref = _insert_run_and_image(
        conn,
        source_image_id="sid1",
        title="Belgique 2 euros 2014",
        target_eurio_id=eurio_id,
    )
    run_text_signal_extract(conn=conn, run=None, source_image_ids={ref: "sid1"})
    run_text_signal_extract(
        conn=conn, run=None, source_image_ids={ref: "sid1"}, force=True,
    )

    n = conn.execute(
        "SELECT COUNT(*) AS n FROM discarded_listings "
        "WHERE source_ref = ? AND reason LIKE 'text_contradict_%'",
        (ref,),
    ).fetchone()["n"]
    assert n == 1


def test_force_recomputes_verdict_after_coin_added(conn):
    """Première extraction sans coin (verdict=NULL), puis on ajoute le
    coin et on recompute via force=True — le verdict apparaît."""
    eurio_id = "fr-2014-2eur-test"
    _, ref = _insert_run_and_image(
        conn,
        source_image_id="sid1",
        title="France 2 euros 2014",
        target_eurio_id=eurio_id,
    )
    run_text_signal_extract(conn=conn, run=None, source_image_ids={ref: "sid1"})
    row = conn.execute(
        "SELECT vs_target_verdict FROM listing_text_signals "
        "WHERE source_image_id = ?",
        ("sid1",),
    ).fetchone()
    assert row["vs_target_verdict"] is None

    _insert_coin(conn, eurio_id=eurio_id, country="FR", year=2014)
    run_text_signal_extract(
        conn=conn, run=None, source_image_ids={ref: "sid1"}, force=True,
    )
    row = conn.execute(
        "SELECT vs_target_verdict FROM listing_text_signals "
        "WHERE source_image_id = ?",
        ("sid1",),
    ).fetchone()
    assert row["vs_target_verdict"] == "convergent"
