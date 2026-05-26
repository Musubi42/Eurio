"""Tests transforms purs Numista payload → row dicts (P.7c.2).

Stratégie : utiliser le cache Bremen (NID 10069) déjà fetché en P.7b comme
fixture vivante. La cohorte 19 NIDs ajoutera d'autres fixtures en P.7d.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from referential.numista_eurio_id import eurio_id_from_numista_payload  # noqa: E402
from referential.numista_transforms import (  # noqa: E402
    GRADE_RAW_TO_EURIO,
    NUMISTA_SOURCE,
    _detect_issue_type,
    coin_canonical_image_rows,
    coin_credit_rows,
    coin_cross_ref_rows,
    coin_market_quote_rows,
    coin_observation_rows,
    coin_row,
    coin_source_ref_row,
    coin_variant_row,
    design_group_row,
    mint_release_price_rows,
    mint_release_rows,
)


BREMEN_CACHE = ML_DIR / "state" / "numista_cache" / "10069"


def _bremen_type() -> dict:
    if not BREMEN_CACHE.exists():
        pytest.skip(f"Bremen cache absent (run P.7b live fetch first): {BREMEN_CACHE}")
    return json.loads((BREMEN_CACHE / "type.json").read_text())


def _bremen_issues() -> list[dict]:
    data = json.loads((BREMEN_CACHE / "issues.json").read_text())
    return data if isinstance(data, list) else data.get("issues", [])


def _bremen_prices_by_iid() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for p in BREMEN_CACHE.glob("prices_*.json"):
        iid = int(p.stem.removeprefix("prices_"))
        out[iid] = json.loads(p.read_text())
    return out


def _fake_mint_resolver(country: str, mark: str | None) -> str | None:
    # 5 ateliers DE canoniques (cf. seed_mints.py).
    de_map = {"A": "de-berlin-a", "D": "de-munich-d", "F": "de-stuttgart-f",
              "G": "de-karlsruhe-g", "J": "de-hamburg-j"}
    if country == "DE":
        return de_map.get(mark)
    return None


# ─── _detect_issue_type ────────────────────────────────────────────────────


@pytest.mark.parametrize(("comment", "expected"), [
    (None, "CIRC"),
    ("", "CIRC"),
    ("-", "CIRC"),
    ("BU set", "BU"),
    ("Proof", "PROOF"),
    ("PROOF", "PROOF"),
    ("Brilliant Uncirculated", "BU"),
    ("Coincard", "COIN_CARD"),
    ("Coin card", "COIN_CARD"),
    ("BE", "BE"),
    ("Belle Epreuve", "OTHER"),  # contient pas "be" comme token isolé (a "be" dans "belle" mais via word boundary)
    ("Weber edition", "OTHER"),  # "weber" ne déclenche pas "be"
    ("Special edition", "OTHER"),
])
def test_detect_issue_type(comment: str | None, expected: str) -> None:
    assert _detect_issue_type(comment) == expected


def test_grade_mapping_complete() -> None:
    """Les 7 grades Numista (g/vg/f/vf/xf/au/unc) doivent tous être dans
    GRADE_RAW_TO_EURIO. ``g`` est mappé à None (ignoré)."""
    assert set(GRADE_RAW_TO_EURIO.keys()) == {"g", "vg", "f", "vf", "xf", "au", "unc"}
    assert GRADE_RAW_TO_EURIO["g"] is None
    assert GRADE_RAW_TO_EURIO["unc"] == "UNC"
    assert GRADE_RAW_TO_EURIO["au"] == "TTB"
    assert GRADE_RAW_TO_EURIO["xf"] == "TTB"
    assert GRADE_RAW_TO_EURIO["vf"] == "TB"


# ─── coin_row + source_ref ─────────────────────────────────────────────────


def test_coin_row_bremen() -> None:
    payload = _bremen_type()
    slug = eurio_id_from_numista_payload(payload)
    assert slug is not None
    row = coin_row(slug, payload)

    assert row["eurio_id"] == "de-2010-2eur-state-of-bremen"
    assert row["country"] == "DE"
    assert row["country_name"] == "Germany, Federal Republic of"
    assert row["year"] == 2010
    assert row["face_value"] == 2.0
    assert row["is_commemorative"] == 1
    assert row["numista_id"] == 10069
    assert row["theme"] == 'Bundesländer - "Bremen"'
    assert row["ref_source"] == NUMISTA_SOURCE
    assert row["ref_native_id"] == "10069"
    assert "composition" not in row  # capturé en observation, pas en coins


def test_coin_source_ref_row_bremen() -> None:
    payload = _bremen_type()
    slug = eurio_id_from_numista_payload(payload)
    row = coin_source_ref_row(slug, payload)
    assert row["target_kind"] == "coin"
    assert row["target_id"] == "de-2010-2eur-state-of-bremen"
    assert row["source"] == NUMISTA_SOURCE
    assert row["source_native_id"] == "10069"
    assert "10069" in row["source_url"]


# ─── coin_cross_refs ───────────────────────────────────────────────────────


def test_coin_cross_ref_rows_bremen() -> None:
    payload = _bremen_type()
    slug = eurio_id_from_numista_payload(payload)
    rows = coin_cross_ref_rows(slug, payload)
    by_type = {r["ref_type"]: r["ref_value"] for r in rows}
    # Bremen : KM#285, Jaeger 549, Schön 278 (cf. findings §3)
    assert by_type.get("krause_mishler") == "285"
    assert by_type.get("jaeger") == "549"
    assert by_type.get("schon") == "278"
    # PK est (eurio_id, ref_type) → pas de duplicat ref_type
    assert len(rows) == len(set(r["ref_type"] for r in rows))


# ─── mint_release_rows ─────────────────────────────────────────────────────


def test_mint_release_rows_bremen_15_issues() -> None:
    payload = _bremen_type()
    issues = _bremen_issues()
    slug = eurio_id_from_numista_payload(payload)
    rows = mint_release_rows(slug, issues, _fake_mint_resolver)

    # Bremen : 5 ateliers × 3 issue_types = 15 rows
    assert len(rows) == 15

    # Tous parent_type_id = eurio_id
    assert {r["parent_type_id"] for r in rows} == {"de-2010-2eur-state-of-bremen"}

    # Tous mint_year = 2010
    assert {r["mint_year"] for r in rows} == {2010}

    # Distribution issue_type : 5 CIRC, 5 BU, 5 PROOF
    from collections import Counter
    counts = Counter(r["issue_type"] for r in rows)
    assert counts["CIRC"] == 5
    assert counts["BU"] == 5
    assert counts["PROOF"] == 5

    # mint_id résolu pour les 5 lettres
    assert {r["mint_id"] for r in rows} == {
        "de-berlin-a", "de-munich-d", "de-stuttgart-f",
        "de-karlsruhe-g", "de-hamburg-j",
    }

    # PKs uniques + format attendu
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == 15
    for r in rows:
        assert r["id"].startswith("de-2010-2eur-state-of-bremen/numista-")


def test_mint_release_rows_circ_atelier_a_mintage_6m() -> None:
    """Cas-fil-rouge findings §1.2 : Bremen 2010 A circulation = 6M."""
    payload = _bremen_type()
    issues = _bremen_issues()
    slug = eurio_id_from_numista_payload(payload)
    rows = mint_release_rows(slug, issues, _fake_mint_resolver)
    a_circ = [r for r in rows
              if r["mint_id"] == "de-berlin-a" and r["issue_type"] == "CIRC"]
    assert len(a_circ) == 1
    assert a_circ[0]["_mintage"] == 6_000_000


# ─── mint_release_price_rows ───────────────────────────────────────────────


def test_mint_release_price_rows_bremen_iid_53447() -> None:
    """Issue 53447 = Bremen 2010 A circulation. 7 grades dans le payload
    (g/vg/f/vf/xf/au/unc) → 6 rows en sortie (g ignoré)."""
    prices = _bremen_prices_by_iid()[53447]
    rows = mint_release_price_rows("test-id", prices, fetched_at="2026-05-26T00:00:00Z")
    assert len(rows) == 6
    by_grade = {r["grade_raw"]: r for r in rows}
    assert "g" not in by_grade
    assert by_grade["unc"]["grade_eurio"] == "UNC"
    assert by_grade["unc"]["price"] == 3.11
    assert by_grade["au"]["grade_eurio"] == "TTB"
    assert by_grade["xf"]["grade_eurio"] == "TTB"
    assert by_grade["vf"]["grade_eurio"] == "TB"
    assert all(r["source"] == NUMISTA_SOURCE for r in rows)
    assert all(r["currency"] == "EUR" for r in rows)


# ─── coin_market_quote_rows (agrégation Type-level) ────────────────────────


def test_coin_market_quote_rows_bremen_aggregation() -> None:
    """Findings §2.2 + §2.3 : agrégation MAX par grade Eurio.

    Finding live Bremen : BU et Proof n'exposent que ``unc`` (1 prix/issue).
    Seul CIRC expose les 7 grades. Distribution réelle :
      - UNC : 15 prix (5 CIRC unc + 5 BU unc + 5 Proof unc)
      - TTB : 10 prix (5 CIRC au + 5 CIRC xf)
      - TB  : 15 prix (5 CIRC vf + 5 CIRC f + 5 CIRC vg)
    """
    prices = _bremen_prices_by_iid()
    rows = coin_market_quote_rows(
        "de-2010-2eur-state-of-bremen",
        prices,
        period_start="2026-05-26",
    )
    by_cond = {r["condition_normalized"]: r for r in rows}
    assert set(by_cond.keys()) == {"UNC", "TTB", "TB"}

    assert by_cond["UNC"]["sample_size"] == 15
    assert by_cond["TTB"]["sample_size"] == 10
    assert by_cond["TB"]["sample_size"] == 15

    # UNC >= TTB >= TB (max-aggregation cohérente avec la hiérarchie de grade)
    assert by_cond["UNC"]["p50"] >= by_cond["TTB"]["p50"]
    assert by_cond["TTB"]["p50"] >= by_cond["TB"]["p50"]

    # p10 == p50 == p90 (Numista expose 1 valeur, pas distribution)
    for r in rows:
        assert r["p10"] == r["p50"] == r["p90"]
        assert r["source"] == NUMISTA_SOURCE
        assert r["currency"] == "EUR"
        assert r["period_start"] == "2026-05-26"


# ─── images, credits, observations, variants, design_groups ───────────────


def test_coin_canonical_image_rows_bremen() -> None:
    payload = _bremen_type()
    slug = eurio_id_from_numista_payload(payload)
    rows = coin_canonical_image_rows(slug, payload)
    assert len(rows) == 2  # obverse + reverse
    roles = {r["role"] for r in rows}
    assert roles == {"obverse", "reverse"}
    for r in rows:
        assert r["source"] == NUMISTA_SOURCE
        assert r["url"].startswith("https://en.numista.com/")


def test_coin_credit_rows_bremen() -> None:
    """Bremen : obverse engraver = Bodo Broschat, reverse = Luc Luycx."""
    payload = _bremen_type()
    slug = eurio_id_from_numista_payload(payload)
    rows = coin_credit_rows(slug, payload)
    by_face = {r["source_ref"]: r["name"] for r in rows}
    assert by_face["obverse"] == "Bodo Broschat"
    assert by_face["reverse"] == "Luc Luycx"
    assert all(r["role"] == "engraver" for r in rows)


def test_coin_observation_rows_bremen() -> None:
    payload = _bremen_type()
    slug = eurio_id_from_numista_payload(payload)
    rows = coin_observation_rows(slug, payload)
    by_type = {r["observation_type"]: r for r in rows}
    # Doit avoir au moins : theme (commemorated_topic), series, composition
    assert "theme" in by_type
    assert json.loads(by_type["theme"]["payload_json"]) == "State of Bremen"
    assert "series" in by_type
    assert json.loads(by_type["series"]["payload_json"]) == "German states"
    assert "composition" in by_type
    assert "Bimetallic" in json.loads(by_type["composition"]["payload_json"])
    assert all(r["source"] == NUMISTA_SOURCE for r in rows)


def test_design_group_row_no_joint_issue() -> None:
    """Bremen n'est pas joint-issue (Bundesländer = série DE seule)."""
    payload = _bremen_type()
    slug = eurio_id_from_numista_payload(payload)
    assert design_group_row(slug) is None


def test_coin_variant_row_no_variant() -> None:
    """Bremen n'est pas un variant (classique CIRC)."""
    payload = _bremen_type()
    slug = eurio_id_from_numista_payload(payload)
    assert coin_variant_row(slug, payload) is None
