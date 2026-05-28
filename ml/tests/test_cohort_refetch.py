"""Tests cohorte refetch — P.7d.

Couvre 3 cas-pivots de la cohorte 19 (cf. ROADMAP §6) :

* **NID 10069 Bremen** — multi-mint Bundesländer (5×3 issues)
* **NID 134283 Bleuet de France** — variant coloured (parent slug + variant row)
* **NID 2162 Treaty of Rome DE** — joint-issue + multi-mint (design_group + 5×3)

Fixtures dans ``ml/tests/fixtures/numista/<nid>/{type,issues,prices_*}.json``
— payloads Numista réels capturés en P.7d (live fetch 2026-05-26). Permettent
de tester la chaîne complète transform→writer sur la DB sans API call.
"""

from __future__ import annotations

import glob
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

FIXTURES = ML_DIR / "tests" / "fixtures" / "numista"
REAL_DB = ML_DIR / "state" / "eurio.db"


def _load_bundle(nid: int) -> tuple[dict, list, dict]:
    base = FIXTURES / str(nid)
    payload = json.loads((base / "type.json").read_text())
    issues_data = json.loads((base / "issues.json").read_text())
    issues = issues_data if isinstance(issues_data, list) else issues_data.get("issues", [])
    prices: dict[int, dict] = {}
    for p in glob.glob(str(base / "prices_*.json")):
        path = Path(p)
        iid = int(path.stem.removeprefix("prices_"))
        prices[iid] = json.loads(path.read_text())
    return payload, issues, prices


def _de_mint_resolver(country: str, mark: str | None) -> str | None:
    de_map = {"A": "de-berlin-a", "D": "de-munich-d", "F": "de-stuttgart-f",
              "G": "de-karlsruhe-g", "J": "de-hamburg-j"}
    if country == "DE":
        return de_map.get(mark)
    if country == "FR":
        return "fr-pessac"
    return None


@pytest.fixture
def db_copy(tmp_path: Path) -> sqlite3.Connection:
    """Copy real DB to tmp + seed minimal mints. Yields a connection."""
    if not REAL_DB.exists():
        pytest.skip(f"eurio.db absent: {REAL_DB}")
    target = tmp_path / "eurio.db"
    shutil.copy2(REAL_DB, target)
    Store(target)
    conn = sqlite3.connect(target, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    # Seed DE A/D/F/G/J + FR pessac at minimum (peut déjà être en DB si seed_mints).
    seeds = [
        ("de-berlin-a", "DE", "A", "Berlin", "Mint A"),
        ("de-munich-d", "DE", "D", "Munich", "Mint D"),
        ("de-stuttgart-f", "DE", "F", "Stuttgart", "Mint F"),
        ("de-karlsruhe-g", "DE", "G", "Karlsruhe", "Mint G"),
        ("de-hamburg-j", "DE", "J", "Hamburg", "Mint J"),
        ("fr-pessac", "FR", None, "Pessac", "Monnaie de Paris"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO mints (id, country, mark, city, display_name) "
        "VALUES (?, ?, ?, ?, ?)", seeds,
    )
    yield conn
    conn.close()


# ─── NID 10069 — Bremen (déjà couvert dans test_numista_writer; smoke) ────


def test_cohort_bremen_multi_mint(db_copy: sqlite3.Connection) -> None:
    payload, issues, prices = _load_bundle(10069)
    slug = eurio_id_from_numista_payload(payload)
    assert slug.eurio_id == "de-2010-2eur-state-of-bremen"

    NumistaWriter(db_copy).write_bundle(
        slug=slug, payload=payload, issues=issues,
        prices_by_iid=prices, mint_resolver=_de_mint_resolver,
    )

    # 15 mint_releases = 5 ateliers × 3 issue_types
    assert db_copy.execute(
        "SELECT COUNT(*) FROM coin_mint_releases WHERE parent_type_id = ?",
        (slug.eurio_id,),
    ).fetchone()[0] == 15

    # Pas de variant, pas de design_group
    assert db_copy.execute(
        "SELECT COUNT(*) FROM coin_variants WHERE parent_type_id = ?",
        (slug.eurio_id,),
    ).fetchone()[0] == 0


# ─── NID 134283 — Bleuet de France 2018 Coloured ──────────────────────────


def test_cohort_bleuet_variant(db_copy: sqlite3.Connection) -> None:
    """Bleuet est un variant coloured. Le slug pointe vers le **parent**
    classique (``fr-2018-2eur-bleuet-de-france``), et une row coin_variants
    capture le finish 'coloured'."""
    payload, issues, prices = _load_bundle(134283)
    slug = eurio_id_from_numista_payload(payload)

    # Slug = parent classic
    assert slug.eurio_id == "fr-2018-2eur-100th-anniversary-of-the-end-of-the-first-world-war-bleuet-de-france"
    assert slug.is_variant is True
    assert slug.variant_finish == "coloured"

    NumistaWriter(db_copy).write_bundle(
        slug=slug, payload=payload, issues=issues,
        prices_by_iid=prices, mint_resolver=_de_mint_resolver,
    )

    # 1 variant row, finish=coloured, parent=parent slug
    rows = list(db_copy.execute(
        "SELECT id, parent_type_id, finish FROM coin_variants WHERE parent_type_id = ?",
        (slug.eurio_id,),
    ))
    assert len(rows) == 1
    assert rows[0][1] == slug.eurio_id
    assert rows[0][2] == "coloured"
    assert "variant-numista-134283" in rows[0][0]

    # Finding §1.2 fixtures : Bleuet coloured = 2 issues (BU + Proof seulement,
    # pas de CIRC car commémo collector coloured). On scope aux iids de CE
    # bundle : le parent classique (NID 134685, refetché séparément lors du
    # pilote FR) ajoute sa propre row CIRC sous le même parent_type_id — hors
    # périmètre de ce test variant.
    variant_ids = [f"{slug.eurio_id}/numista-{i['id']}" for i in issues]
    placeholders = ",".join("?" * len(variant_ids))
    assert db_copy.execute(
        f"SELECT COUNT(*) FROM coin_mint_releases WHERE id IN ({placeholders})",
        variant_ids,
    ).fetchone()[0] == 2

    types = sorted([r[0] for r in db_copy.execute(
        f"SELECT issue_type FROM coin_mint_releases WHERE id IN ({placeholders})",
        variant_ids,
    )])
    assert types == ["BU", "PROOF"]


# ─── NID 2162 — Treaty of Rome 2007 DE — joint-issue + multi-mint ─────────


def test_cohort_treaty_of_rome_joint_issue(db_copy: sqlite3.Connection) -> None:
    """Treaty of Rome 2007 : 13 NIDs (1 par pays eurozone à l'époque) partagent
    un design_group commun. Le payload DE doit produire une row design_groups,
    et le coin doit avoir design_group_id rempli."""
    payload, issues, prices = _load_bundle(2162)
    slug = eurio_id_from_numista_payload(payload)

    assert slug.is_joint_issue is True
    assert slug.design_group_id is not None
    assert slug.design_group_id.startswith("eu-")
    expected_dg_id = slug.design_group_id

    NumistaWriter(db_copy).write_bundle(
        slug=slug, payload=payload, issues=issues,
        prices_by_iid=prices, mint_resolver=_de_mint_resolver,
    )

    # design_group créé
    row = db_copy.execute(
        "SELECT id, designation FROM design_groups WHERE id = ?",
        (expected_dg_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == expected_dg_id

    # coin.design_group_id renseigné
    coin_dg = db_copy.execute(
        "SELECT design_group_id FROM coins WHERE eurio_id = ?",
        (slug.eurio_id,),
    ).fetchone()[0]
    assert coin_dg == expected_dg_id

    # Treaty of Rome DE = même grille Bremen-like (5×3 = 15 issues)
    assert db_copy.execute(
        "SELECT COUNT(*) FROM coin_mint_releases WHERE parent_type_id = ?",
        (slug.eurio_id,),
    ).fetchone()[0] == 15


# ─── Cohort multi-write — vérifie idempotence + cohabitation ──────────────


def test_cohort_three_nids_idempotent(db_copy: sqlite3.Connection) -> None:
    """Pipeline complet sur les 3 NIDs en séquence, deux fois. Doit produire
    les mêmes counts (UPSERT idempotent partout)."""
    writer = NumistaWriter(db_copy)

    def _write_all() -> None:
        for nid in (10069, 134283, 2162):
            payload, issues, prices = _load_bundle(nid)
            slug = eurio_id_from_numista_payload(payload)
            writer.write_bundle(
                slug=slug, payload=payload, issues=issues,
                prices_by_iid=prices, mint_resolver=_de_mint_resolver,
            )

    def _counts() -> dict[str, int]:
        return {
            t: db_copy.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ["coin_mint_releases", "coin_variants", "design_groups",
                      "coin_canonical_images", "coin_credits",
                      "coin_observations", "coin_source_refs"]
        }

    _write_all()
    c1 = _counts()
    _write_all()
    c2 = _counts()
    assert c1 == c2, f"non idempotent: c1={c1} c2={c2}"
