"""Tests writer + intégration P.7c.3.

Stratégie : copie eurio.db dans tmp_path, applique writer sur cache Bremen
(zero API call, le cache /numista_cache/10069/ doit exister via P.7b smoke),
vérifie counts attendus. Pas de modification de la DB réelle.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from referential.numista_eurio_id import eurio_id_from_numista_payload  # noqa: E402
from referential.numista_writer import NumistaWriter  # noqa: E402
from state.store import Store  # noqa: E402


REAL_DB = ML_DIR / "state" / "eurio.db"
BREMEN_CACHE = ML_DIR / "state" / "numista_cache" / "10069"


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    if not REAL_DB.exists():
        pytest.skip(f"eurio.db absent: {REAL_DB}")
    if not BREMEN_CACHE.exists():
        pytest.skip(f"Bremen cache absent (run P.7b smoke): {BREMEN_CACHE}")
    target = tmp_path / "eurio.db"
    shutil.copy2(REAL_DB, target)
    return target


def _load_bremen_bundle() -> tuple[dict, list, dict]:
    payload = json.loads((BREMEN_CACHE / "type.json").read_text())
    issues_data = json.loads((BREMEN_CACHE / "issues.json").read_text())
    issues = issues_data if isinstance(issues_data, list) else issues_data.get("issues", [])
    prices: dict[int, dict] = {}
    for p in BREMEN_CACHE.glob("prices_*.json"):
        iid = int(p.stem.removeprefix("prices_"))
        prices[iid] = json.loads(p.read_text())
    return payload, issues, prices


def _de_mint_resolver(country: str, mark: str | None) -> str | None:
    return {
        ("DE", "A"): "de-berlin-a",
        ("DE", "D"): "de-munich-d",
        ("DE", "F"): "de-stuttgart-f",
        ("DE", "G"): "de-karlsruhe-g",
        ("DE", "J"): "de-hamburg-j",
    }.get((country, mark))


def _count(conn: sqlite3.Connection, table: str, eurio_id: str) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE eurio_id = ?", (eurio_id,)
    ).fetchone()[0]


def test_write_bundle_bremen_counts(db_copy: Path) -> None:
    """Smoke : ingestion complète du bundle Bremen sur DB copie, vérif counts."""
    Store(db_copy)  # bootstrap if needed
    conn = sqlite3.connect(db_copy, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")

    # Seed mints DE A/D/F/G/J (le test peut tourner sans seed externe)
    for slug, mark in [("de-berlin-a", "A"), ("de-munich-d", "D"),
                       ("de-stuttgart-f", "F"), ("de-karlsruhe-g", "G"),
                       ("de-hamburg-j", "J")]:
        conn.execute(
            "INSERT OR IGNORE INTO mints (id, country, mark, city, display_name) "
            "VALUES (?, 'DE', ?, ?, ?)",
            (slug, mark, slug.split("-")[1].capitalize(), f"Mint {mark}"),
        )

    payload, issues, prices = _load_bremen_bundle()
    slug = eurio_id_from_numista_payload(payload)
    assert slug is not None
    eurio_id = slug.eurio_id  # 'de-2010-2eur-bundeslander-bremen'

    writer = NumistaWriter(conn)
    writer.write_bundle(
        slug=slug, payload=payload, issues=issues,
        prices_by_iid=prices, mint_resolver=_de_mint_resolver,
    )

    # Counts
    assert _count(conn, "coins", eurio_id) == 1
    # source_refs : la PK clé est target_id, pas eurio_id
    assert conn.execute(
        "SELECT COUNT(*) FROM coin_source_refs WHERE target_id = ?", (eurio_id,)
    ).fetchone()[0] == 1
    assert _count(conn, "coin_cross_refs", eurio_id) == 3      # KM, J, Schön
    assert conn.execute(
        "SELECT COUNT(*) FROM coin_mint_releases WHERE parent_type_id = ?",
        (eurio_id,),
    ).fetchone()[0] == 15

    # 5 CIRC × 6 grades (g ignored) + 5 BU × 1 + 5 Proof × 1 = 40
    n_prices = conn.execute(
        """SELECT COUNT(*) FROM mint_release_prices p
           JOIN coin_mint_releases r ON r.id = p.mint_release_id
           WHERE r.parent_type_id = ?""",
        (eurio_id,),
    ).fetchone()[0]
    assert n_prices == 40

    # 3 conditions Type-level
    assert _count(conn, "coin_market_quotes", eurio_id) == 3

    # images obverse + reverse
    assert _count(conn, "coin_canonical_images", eurio_id) == 2

    # credits : Broschat (obverse) + Luycx (reverse)
    assert _count(conn, "coin_credits", eurio_id) == 2

    # observations : theme + series + composition + edge + shape + orientation
    # + weight_g + thickness_mm  (diameter null car None dans payload)
    n_obs = _count(conn, "coin_observations", eurio_id)
    assert n_obs >= 5  # au moins 5 observations capturées


def test_write_bundle_idempotent(db_copy: Path) -> None:
    """Deuxième run sur la même DB ne doit pas multiplier les rows (UPSERT)."""
    Store(db_copy)
    conn = sqlite3.connect(db_copy, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    for slug, mark in [("de-berlin-a", "A"), ("de-munich-d", "D"),
                       ("de-stuttgart-f", "F"), ("de-karlsruhe-g", "G"),
                       ("de-hamburg-j", "J")]:
        conn.execute(
            "INSERT OR IGNORE INTO mints (id, country, mark, city, display_name) "
            "VALUES (?, 'DE', ?, ?, ?)",
            (slug, mark, slug, slug),
        )
    payload, issues, prices = _load_bremen_bundle()
    slug = eurio_id_from_numista_payload(payload)
    eurio_id = slug.eurio_id

    writer1 = NumistaWriter(conn)
    writer1.write_bundle(
        slug=slug, payload=payload, issues=issues,
        prices_by_iid=prices, mint_resolver=_de_mint_resolver,
    )
    n_releases_1 = conn.execute(
        "SELECT COUNT(*) FROM coin_mint_releases WHERE parent_type_id = ?",
        (eurio_id,),
    ).fetchone()[0]
    n_obs_1 = _count(conn, "coin_observations", eurio_id)
    n_quotes_1 = _count(conn, "coin_market_quotes", eurio_id)

    # 2e write
    writer2 = NumistaWriter(conn)
    writer2.write_bundle(
        slug=slug, payload=payload, issues=issues,
        prices_by_iid=prices, mint_resolver=_de_mint_resolver,
    )
    n_releases_2 = conn.execute(
        "SELECT COUNT(*) FROM coin_mint_releases WHERE parent_type_id = ?",
        (eurio_id,),
    ).fetchone()[0]
    n_obs_2 = _count(conn, "coin_observations", eurio_id)
    n_quotes_2 = _count(conn, "coin_market_quotes", eurio_id)

    assert n_releases_1 == n_releases_2 == 15
    assert n_obs_1 == n_obs_2
    # market_quotes : ON CONFLICT (source, eurio_id, period_start, condition_raw)
    # Le period_start est aujourd'hui → identique entre les 2 runs → pas de
    # dup
    assert n_quotes_1 == n_quotes_2 == 3


def test_market_quote_aggregation_bremen(db_copy: Path) -> None:
    Store(db_copy)
    conn = sqlite3.connect(db_copy, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    for slug, mark in [("de-berlin-a", "A"), ("de-munich-d", "D"),
                       ("de-stuttgart-f", "F"), ("de-karlsruhe-g", "G"),
                       ("de-hamburg-j", "J")]:
        conn.execute(
            "INSERT OR IGNORE INTO mints (id, country, mark, city, display_name) "
            "VALUES (?, 'DE', ?, ?, ?)",
            (slug, mark, slug, slug),
        )
    payload, issues, prices = _load_bremen_bundle()
    slug = eurio_id_from_numista_payload(payload)
    NumistaWriter(conn).write_bundle(
        slug=slug, payload=payload, issues=issues,
        prices_by_iid=prices, mint_resolver=_de_mint_resolver,
    )
    rows = list(conn.execute(
        """SELECT condition_normalized, p50, sample_size
           FROM coin_market_quotes WHERE eurio_id = ?
           ORDER BY condition_normalized""",
        (slug.eurio_id,),
    ))
    by_cond = {r[0]: (r[1], r[2]) for r in rows}
    # Cf. findings §2.4 : UNC=15, TTB=10, TB=15
    assert by_cond["UNC"][1] == 15
    assert by_cond["TTB"][1] == 10
    assert by_cond["TB"][1] == 15
    assert by_cond["UNC"][0] >= by_cond["TTB"][0] >= by_cond["TB"][0]
