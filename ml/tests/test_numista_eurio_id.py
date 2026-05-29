"""Tests pour ml/referential/numista_eurio_id.py (≥ 50 cas).

Chaque fixture est un payload Numista minimal mais réaliste. Les commentaires
citent le nid source quand le cas est inspiré d'un vrai coin observé en base.

Convention payload minimal :
    {
        "id": <int>,
        "title": "2 Euros - ...",
        "issuer": {"code": "FR", "name": "France"},
        "min_year": 2020,
        "value": {"numeric_value": 2, "currency": {"name": "Euro"}},
        "commemorated_topic": <str|None>,  # presence = commemo
    }
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from referential.numista_eurio_id import (  # noqa: E402
    MANUAL_NID_SLUG_OVERRIDES,
    detect_joint_issue,
    detect_variant,
    eurio_id_from_numista_payload,
    is_commemorative_payload,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def make_payload(
    nid: int,
    title: str,
    country_code: str,
    country_name: str,
    year: int,
    *,
    is_commemo: bool = False,
    numeric: int = 2,
    currency: str = "Euro",
    commemorated_topic: str | None = None,
) -> dict:
    """Build a synthetic Numista payload for tests.

    Pour marquer une commemo SANS topic verbeux (mode legacy testant la
    règle title-parens), on utilise object_type.name au lieu d'un
    `commemorated_topic="x"` placeholder qui polluerait le nouveau
    slug verbeux. `commemorated_topic` peut être fourni explicitement
    pour tester la nouvelle règle.
    """
    payload: dict = {
        "id": nid,
        "title": title,
        "issuer": {"code": country_code, "name": country_name},
        "min_year": year,
        "value": {"numeric_value": numeric, "currency": {"name": currency}},
        "commemorated_topic": commemorated_topic,
    }
    if is_commemo and not commemorated_topic:
        payload["object_type"] = {"name": "Circulating commemorative coins"}
    return payload


# ─── Standards (10) ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("nid,title,iso,name,year,expected_eurio,expected_slug", [
    # nid=1, BE Albert II 1st map
    (1, "2 Euros - Albert II (1st map, 1st type, 1st portrait)",
     "BE", "Belgium", 2002,
     "be-2002-2eur-standard-albert-ii-1st-map-1st-type-1st-portrait",
     "albert-ii-1st-map-1st-type-1st-portrait"),
    # BE Albert II 2nd map
    (2, "2 Euros - Albert II (2nd map)", "BE", "Belgium", 2008,
     "be-2008-2eur-standard-albert-ii-2nd-map",
     "albert-ii-2nd-map"),
    # BE Philippe
    (3, "2 Euros - Philippe", "BE", "Belgium", 2014,
     "be-2014-2eur-standard-philippe",
     "philippe"),
    # FR Marianne 1st map
    (4, "2 Euros (1st map, 1st type)", "FR", "France", 2002,
     "fr-2002-2eur-standard-1st-map-1st-type",
     "1st-map-1st-type"),
    # DE 1st map
    (5, "2 Euros (1st map)", "DE", "Germany", 2002,
     "de-2002-2eur-standard-1st-map",
     "1st-map"),
    # IT
    (6, "2 Euros (1st map)", "IT", "Italy", 2002,
     "it-2002-2eur-standard-1st-map",
     "1st-map"),
    # LU Henri 1st type
    (7, "2 Euros - Henri I (1st type, 1st portrait)", "LU", "Luxembourg", 2002,
     "lu-2002-2eur-standard-henri-i-1st-type-1st-portrait",
     "henri-i-1st-type-1st-portrait"),
    # VA Francis (year disambiguates 2014 vs 2017)
    (8, "2 Euros - Francis", "VA", "Vatican City", 2014,
     "va-2014-2eur-standard-francis",
     "francis"),
    # VA Sede Vacante
    (9, "2 Euros - Sede Vacante", "VA", "Vatican City", 2013,
     "va-2013-2eur-standard-sede-vacante",
     "sede-vacante"),
    # MT minimal
    (10, "2 Euros", "MT", "Malta", 2008,
     "mt-2008-2eur-standard-1st-type",
     "1st-type"),
])
def test_standards(nid, title, iso, name, year, expected_eurio, expected_slug):
    p = make_payload(nid, title, iso, name, year, is_commemo=False)
    r = eurio_id_from_numista_payload(p)
    assert r is not None, f"{title} returned None unexpectedly"
    assert r.eurio_id == expected_eurio
    assert r.is_commemorative is False
    assert r.is_variant is False
    assert r.is_joint_issue is False


# ─── Joint-issues (15) ───────────────────────────────────────────────────────


@pytest.mark.parametrize("nid,title,iso,name,year,expected_eurio,expected_theme", [
    # Rome 2007 — 6 founding members
    (101, "2 Euros - Albert II (Treaty of Rome)", "BE", "Belgium", 2007,
     "be-2007-2eur-treaty-of-rome", "rome"),
    (102, "2 Euros (Treaty of Rome)", "DE", "Germany", 2007,
     "de-2007-2eur-treaty-of-rome", "rome"),
    (103, "2 Euros (Treaty of Rome)", "FR", "France", 2007,
     "fr-2007-2eur-treaty-of-rome", "rome"),
    (104, "2 Euros (Treaty of Rome)", "IT", "Italy", 2007,
     "it-2007-2eur-treaty-of-rome", "rome"),
    # EMU 2009
    (105, "2 Euros (10th anniversary of the Economic and Monetary Union)",
     "FR", "France", 2009,
     "fr-2009-2eur-10th-anniversary-of-the-economic-and-monetary-union",
     "emu"),
    (106, "2 Euros (Economic and Monetary Union)", "DE", "Germany", 2009,
     "de-2009-2eur-economic-and-monetary-union", "emu"),
    (107, "2 Euros (Economic and Monetary Union)", "ES", "Spain", 2009,
     "es-2009-2eur-economic-and-monetary-union", "emu"),
    # Euro Cash 2012
    (108, "2 Euros (10 Years of Euro Cash)", "FR", "France", 2012,
     "fr-2012-2eur-10-years-of-euro-cash", "euro-cash"),
    (109, "2 Euros (10 Years of Euro Cash)", "DE", "Germany", 2012,
     "de-2012-2eur-10-years-of-euro-cash", "euro-cash"),
    (110, "2 Euros (10 Years of Euro Cash)", "IT", "Italy", 2012,
     "it-2012-2eur-10-years-of-euro-cash", "euro-cash"),
    # EU Flag 2015
    (111, "2 Euros (30 Years of European Union Flag)", "FR", "France", 2015,
     "fr-2015-2eur-30-years-of-european-union-flag", "eu-flag"),
    (112, "2 Euros (30 Years of European Union Flag)", "DE", "Germany", 2015,
     "de-2015-2eur-30-years-of-european-union-flag", "eu-flag"),
    # Erasmus 2022
    (113, "2 Euros (35 Years of the Erasmus Programme)", "FR", "France", 2022,
     "fr-2022-2eur-35-years-of-the-erasmus-programme", "erasmus"),
    (114, "2 Euros - Albert II (Erasmus)", "BE", "Belgium", 2022,
     "be-2022-2eur-erasmus", "erasmus"),
    (115, "2 Euros (Erasmus Programme)", "IT", "Italy", 2022,
     "it-2022-2eur-erasmus-programme", "erasmus"),
])
def test_joint_issues(nid, title, iso, name, year, expected_eurio, expected_theme):
    p = make_payload(nid, title, iso, name, year, is_commemo=True)
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert r.eurio_id == expected_eurio
    assert r.is_joint_issue is True
    assert r.joint_theme == expected_theme
    assert r.design_group_id == f"eu-{expected_theme}-{year}"
    assert r.is_commemorative is True


def test_joint_issue_year_guard():
    """Treaty of Rome theme reused in 2017 must NOT be detected as 2007 joint."""
    p = make_payload(999, "2 Euros (Treaty of Rome — 60th anniversary)",
                     "VA", "Vatican City", 2017, is_commemo=True)
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert r.is_joint_issue is False
    assert r.joint_theme is None
    # Slug still derived from parens (commemo path)
    assert r.eurio_id.startswith("va-2017-2eur-")


# ─── Commemos non-joint (10) ─────────────────────────────────────────────────


@pytest.mark.parametrize("nid,title,iso,name,year,expected_eurio", [
    # BE national commemos
    (201, "2 Euros - Albert II (Centenary of the Universal Declaration of Human Rights)",
     "BE", "Belgium", 2008,
     "be-2008-2eur-centenary-of-the-universal-declaration-of-human-rights"),
    # FR
    (202, "2 Euros (D-Day, 70th Anniversary)", "FR", "France", 2014,
     "fr-2014-2eur-d-day-70th-anniversary"),
    (203, "2 Euros (Auguste Rodin)", "FR", "France", 2017,
     "fr-2017-2eur-auguste-rodin"),
    # IT
    (204, "2 Euros (200th Anniversary of the Birth of Louis Braille)",
     "IT", "Italy", 2009,
     "it-2009-2eur-200th-anniversary-of-the-birth-of-louis-braille"),
    # ES
    (205, "2 Euros (Alhambra)", "ES", "Spain", 2011,
     "es-2011-2eur-alhambra"),
    # DE Bundesländer
    (206, "2 Euros (Schleswig-Holstein)", "DE", "Germany", 2006,
     "de-2006-2eur-schleswig-holstein"),
    # NL
    (207, "2 Euros - Willem-Alexander (Kingdom of the Netherlands)",
     "NL", "Netherlands", 2013,
     "nl-2013-2eur-kingdom-of-the-netherlands"),
    # PT
    (208, "2 Euros (50th anniversary of the April Revolution)",
     "PT", "Portugal", 2024,
     "pt-2024-2eur-50th-anniversary-of-the-april-revolution"),
    # LU Henri portrait
    (209, "2 Euros - Henri I (Grand-Duke Henri and Grand-Duchess Maria Teresa)",
     "LU", "Luxembourg", 2006,
     "lu-2006-2eur-grand-duke-henri-and-grand-duchess-maria-teresa"),
    # MT unique theme
    (210, "2 Euros (Il-Kelb tal-Fenek)", "MT", "Malta", 2017,
     "mt-2017-2eur-il-kelb-tal-fenek"),
])
def test_commemos_non_joint(nid, title, iso, name, year, expected_eurio):
    p = make_payload(nid, title, iso, name, year, is_commemo=True)
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert r.eurio_id == expected_eurio
    assert r.is_commemorative is True
    assert r.is_joint_issue is False
    assert r.is_variant is False


# ─── Variants (5) ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("nid,title,iso,name,year,expected_finish,expected_parent_slug", [
    (301, "2 Euros (Erasmus, coloured)", "FR", "France", 2022,
     "coloured", "erasmus"),
    (302, "2 Euros - Albert II (Treaty of Rome) [hologram]",
     "BE", "Belgium", 2007,
     "hologram", "treaty-of-rome"),
    (303, "2 Euros (D-Day, gilded)", "FR", "France", 2014,
     "gilded", "d-day"),
    (304, "2 Euros - Philippe (pattern)", "BE", "Belgium", 2014,
     "pattern", "philippe"),
    (305, "2 Euros (Alhambra, mule)", "ES", "Spain", 2011,
     "mule", "alhambra"),
])
def test_variants(nid, title, iso, name, year, expected_finish, expected_parent_slug):
    p = make_payload(nid, title, iso, name, year,
                     is_commemo=(expected_parent_slug != "philippe"))
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert r.is_variant is True
    assert r.variant_finish == expected_finish
    assert r.variant_kind == expected_finish
    # Chantier variantes : la variante a SON propre eurio_id (= base-{kind}),
    # et pointe vers la canonique via canonical_eurio_id (= le base_slug nu).
    if expected_parent_slug == "philippe":
        base = f"{iso.lower()}-{year}-2eur-standard-{expected_parent_slug}"
    else:
        base = f"{iso.lower()}-{year}-2eur-{expected_parent_slug}"
    assert r.canonical_eurio_id == base
    assert r.eurio_id == f"{base}-{expected_finish}"
    assert r.variant_label is not None


# ─── Variantes first-class — groupes de collision réels (cache) ──────────────
#
# Régression du bug découvert au rollout zone euro : 2+ types Numista
# (même pays+année+thème) collisionnaient sur l'eurio_id parent. Désormais
# chaque variante a son propre eurio_id `base-{kind}` + canonical_eurio_id.

_CACHE_DIR = ML_DIR / "state" / "numista_cache"


def _cached_payload(nid: int) -> dict | None:
    import json
    p = _CACHE_DIR / str(nid) / "type.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


@pytest.mark.parametrize("nid,expected_eurio,expected_kind,expected_canon", [
    # DE 2008 Hamburg : canonique (circulation) vs Mule (erreur de frappe)
    (2994, "de-2008-2eur-federal-state-of-hamburg", "classic", None),
    (327881, "de-2008-2eur-federal-state-of-hamburg-mule", "mule",
     "de-2008-2eur-federal-state-of-hamburg"),
    # DE 2015 Hessen : canonique vs Pattern (essai)
    (69263, "de-2015-2eur-state-of-hessen", "classic", None),
    (284594, "de-2015-2eur-state-of-hessen-pattern", "pattern",
     "de-2015-2eur-state-of-hessen"),
    # LU 2020 Prince Charles : classic vs hologram
    (243911, "lu-2020-2eur-birth-of-prince-charles-jean-phillipe-joseph-marie-guillaume-10-5-2020",
     "classic", None),
    (243914, "lu-2020-2eur-birth-of-prince-charles-jean-phillipe-joseph-marie-guillaume-10-5-2020-hologram",
     "hologram",
     "lu-2020-2eur-birth-of-prince-charles-jean-phillipe-joseph-marie-guillaume-10-5-2020"),
    # LU 2025 accession Henri : classic vs coloured vs hologram (groupe ×3)
    (467622, "lu-2025-2eur-25th-anniversary-of-the-accession-of-grand-duke-henri-to-the-throne",
     "classic", None),
    (467619, "lu-2025-2eur-25th-anniversary-of-the-accession-of-grand-duke-henri-to-the-throne-coloured",
     "coloured",
     "lu-2025-2eur-25th-anniversary-of-the-accession-of-grand-duke-henri-to-the-throne"),
    (477676, "lu-2025-2eur-25th-anniversary-of-the-accession-of-grand-duke-henri-to-the-throne-hologram",
     "hologram",
     "lu-2025-2eur-25th-anniversary-of-the-accession-of-grand-duke-henri-to-the-throne"),
])
def test_real_collision_groups(nid, expected_eurio, expected_kind, expected_canon):
    payload = _cached_payload(nid)
    if payload is None:
        pytest.skip(f"cache absent pour nid {nid}")
    r = eurio_id_from_numista_payload(payload)
    assert r is not None
    assert r.eurio_id == expected_eurio
    assert r.variant_kind == expected_kind
    assert r.canonical_eurio_id == expected_canon
    if expected_kind == "classic":
        assert r.is_variant is False
        assert r.variant_label is None
    else:
        assert r.is_variant is True
        assert r.variant_label is not None


def test_canonical_has_no_variant_fields():
    """Non-régression : un commémo normal garde son slug exact, variant_kind=classic."""
    p = make_payload(10069, '2 Euros (Bundesländer - "Bremen")', "DE", "Germany",
                     2010, is_commemo=True)
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert r.variant_kind == "classic"
    assert r.canonical_eurio_id is None
    assert r.variant_label is None


# ─── Determinism (5) ─────────────────────────────────────────────────────────


def test_deterministic_same_payload_same_result():
    """Calling twice with same payload must produce identical result."""
    p = make_payload(401, "2 Euros (Auguste Rodin)", "FR", "France", 2017,
                     is_commemo=True)
    r1 = eurio_id_from_numista_payload(p)
    r2 = eurio_id_from_numista_payload(p)
    assert r1 == r2


def test_deterministic_unicode_in_name():
    """Non-ASCII chars in catalog_name must be transliterated identically."""
    p = make_payload(402, "2 Euros (Île de la Réunion)", "FR", "France", 2020,
                     is_commemo=True)
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert r.eurio_id == "fr-2020-2eur-ile-de-la-reunion"


def test_deterministic_quotes_stripped():
    p = make_payload(403, "2 Euros (D'Artagnan)", "FR", "France", 2020,
                     is_commemo=True)
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert "dartagnan" in r.eurio_id


def test_deterministic_ampersand_normalized():
    p = make_payload(404, "2 Euros (Treaty & Friendship)", "FR", "France", 2020,
                     is_commemo=True)
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert r.eurio_id == "fr-2020-2eur-treaty-friendship"


def test_deterministic_long_name_truncated_on_word_boundary():
    long = "2 Euros (a-very-long-theme-name-that-exceeds-sixty-characters-limit-and-keeps-going)"
    p = make_payload(405, long, "FR", "France", 2020, is_commemo=True)
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    # Slug section is bounded by max_len=60 (cf slugify)
    slug_part = r.eurio_id.removeprefix("fr-2020-2eur-")
    assert len(slug_part) <= 60


# ─── Out-of-scope & defensive (8) ────────────────────────────────────────────


def test_out_of_scope_non_2eur_returns_none():
    p = make_payload(501, "1 Euro", "FR", "France", 2020, numeric=1)
    assert eurio_id_from_numista_payload(p) is None


def test_out_of_scope_cents_returns_none():
    p = make_payload(502, "50 Cents", "FR", "France", 2020, numeric=1, currency="Euro Cent")
    # Even if numeric_value != 2, we return None
    assert eurio_id_from_numista_payload(p) is None


def test_out_of_scope_non_euro_currency_returns_none():
    p = {
        "id": 503,
        "title": "2 Dollars",
        "issuer": {"code": "US", "name": "United States"},
        "min_year": 2020,
        "value": {"numeric_value": 2, "currency": {"name": "Dollar"}},
    }
    assert eurio_id_from_numista_payload(p) is None


def test_missing_country_returns_none():
    p = {
        "id": 504,
        "title": "2 Euros",
        "issuer": {},
        "min_year": 2020,
        "value": {"numeric_value": 2, "currency": {"name": "Euro"}},
    }
    assert eurio_id_from_numista_payload(p) is None


def test_missing_year_returns_none():
    p = {
        "id": 505,
        "title": "2 Euros",
        "issuer": {"code": "FR"},
        "value": {"numeric_value": 2, "currency": {"name": "Euro"}},
    }
    assert eurio_id_from_numista_payload(p) is None


def test_empty_payload_returns_none():
    assert eurio_id_from_numista_payload({}) is None
    assert eurio_id_from_numista_payload(None) is None  # type: ignore[arg-type]


def test_issuer_name_fallback_when_code_missing():
    """If issuer.code is missing, fall back to name map."""
    p = {
        "id": 506,
        "title": "2 Euros (Test)",
        "issuer": {"name": "France"},
        "min_year": 2020,
        "value": {"numeric_value": 2, "currency": {"name": "Euro"}},
        "commemorated_topic": "x",
    }
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert r.country == "FR"


def test_issuer_unknown_name_returns_none():
    """Unknown country name (no code, no map match) → None."""
    p = {
        "id": 507,
        "title": "2 Euros (Test)",
        "issuer": {"name": "Atlantis"},
        "min_year": 2020,
        "value": {"numeric_value": 2, "currency": {"name": "Euro"}},
    }
    assert eurio_id_from_numista_payload(p) is None


# ─── Manual overrides (2) ────────────────────────────────────────────────────


def test_manual_override_is_honored(monkeypatch):
    """A nid present in MANUAL_NID_SLUG_OVERRIDES bypasses computation."""
    from referential import numista_eurio_id as mod
    monkeypatch.setitem(mod.MANUAL_NID_SLUG_OVERRIDES, "601", "custom-slug")
    p = make_payload(601, "2 Euros (Whatever)", "VA", "Vatican City", 2017,
                     is_commemo=True)
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert r.eurio_id == "va-2017-2eur-custom-slug"
    assert r.used_override is True


def test_manual_overrides_empty_by_default():
    """At greenfield refetch start, no overrides should be hardcoded."""
    assert MANUAL_NID_SLUG_OVERRIDES == {}


# ─── Helper function direct tests ────────────────────────────────────────────


@pytest.mark.parametrize("title,expected_finish", [
    ("2 Euros (Erasmus, coloured)", "coloured"),
    ("2 Euros (Erasmus, colored)", "coloured"),       # American spelling normalized
    ("2 Euros - Treaty (hologram)", "hologram"),
    ("2 Euros (gilded)", "gilded"),
    ("2 Euros (pattern)", "pattern"),
    ("2 Euros (mule)", "mule"),
    ("2 Euros (misstrike)", "mis-strike"),
    ("2 Euros (Treaty of Rome)", None),               # not a variant
    ("", None),
])
def test_detect_variant(title, expected_finish):
    is_var, finish = detect_variant(title)
    if expected_finish is None:
        assert is_var is False
        assert finish is None
    else:
        assert is_var is True
        assert finish == expected_finish


@pytest.mark.parametrize("title,year,expected_theme", [
    ("2 Euros (Treaty of Rome)", 2007, "rome"),
    ("2 Euros (Treaty of Rome)", 2017, None),        # wrong year
    ("2 Euros (Economic and Monetary Union)", 2009, "emu"),
    ("2 Euros (10 Years of Euro Cash)", 2012, "euro-cash"),
    ("2 Euros (European Union Flag)", 2015, "eu-flag"),
    ("2 Euros (Erasmus)", 2022, "erasmus"),
    ("2 Euros (Erasmus)", 2023, None),
    ("2 Euros (random theme)", 2020, None),
])
def test_detect_joint_issue(title, year, expected_theme):
    result = detect_joint_issue(title, year)
    if expected_theme is None:
        assert result is None
    else:
        assert result is not None
        assert result[0] == expected_theme


@pytest.mark.parametrize("payload,expected", [
    ({"title": "2 Euros (Theme)", "commemorated_topic": "x"}, True),
    ({"title": "2 Euros - Albert II", "commemorated_topic": None}, False),
    ({"title": "2 Euros (Commemorative)", "commemorated_topic": None}, True),
    ({"title": "2 Euros", "commemorated_topic": None}, False),
])
def test_is_commemorative_payload(payload, expected):
    assert is_commemorative_payload(payload) is expected


# ─── ROADMAP §5 regression cases — cohorte 19 ────────────────────────────────
#
# These cases use the REAL Numista titles as of 2026-05-25 (read from
# referential_catalog). They lock the algorithm's CURRENT behavior — if Numista
# renames a title, the test catches it and the operator decides whether to
# accept the new slug (cohort doc + eurio_id_migrations) or pin the old one
# (MANUAL_NID_SLUG_OVERRIDES).
#
# The cohort 19 is NID-keyed (cf. cohort_validation_19.txt), not eurio_id-keyed,
# precisely because slugs are downstream of Numista's title decisions.


@pytest.mark.parametrize("nid,title,iso,name,year,expected_eurio,notes", [
    # LV-2018 Zemgale vs Baltic States — historically the V1 risk was to
    # collapse 2 same-(country,year,denom) commemos into one slug.
    (132943, "2 Euros (100th Anniversary of the Baltic States)",
     "LV", "Latvia", 2018,
     "lv-2018-2eur-100th-anniversary-of-the-baltic-states",
     "Baltic States joint commemo (LV side)"),
    (147218, "2 Euros (Zemgale)",
     "LV", "Latvia", 2018,
     "lv-2018-2eur-zemgale",
     "Zemgale — distinct slug from Baltic States despite same (LV,2018,2eur)"),

    # BE-2017 — two different commemos same year, must produce different slugs
    (203001, "2 Euros (200 Years of the University of Ghent)",
     "BE", "Belgium", 2017,
     "be-2017-2eur-200-years-of-the-university-of-ghent",
     "BE-2017 Ghent — fictitious NID, title pattern from Numista convention"),
    (203002, "2 Euros (200 Years of the University of Liège)",
     "BE", "Belgium", 2017,
     "be-2017-2eur-200-years-of-the-university-of-liege",
     "BE-2017 Liège — fictitious NID, accent stripped"),

    # FR-2010 — Numista renamed this coin over time
    # ("Appel du 18 juin" → "Appeal of 18 June" → "Speech of June 18th 1940")
    # NID 11526 is stable. Test the CURRENT slug.
    (11526, "2 Euros (Speech of June 18th 1940)",
     "FR", "France", 2010,
     "fr-2010-2eur-speech-of-june-18th-1940",
     "FR-2010 General de Gaulle commemo — NID 11526, current Numista title"),

    # DE-2009 NID 5054 — KNOWN V1 BUG : Numista title is 'Economic and Monetary
    # Union' which triggers joint-issue detection. Expected current eurio_id in
    # DB is `de-2009-2eur-ludwigskirche-in-saarbrucken-saarland` (legacy slug
    # from historical Numista title). The pure function on the CURRENT Numista
    # title produces the EMU joint-issue slug — the V1 bug regresses.
    #
    # FIX TRACKING : populate MANUAL_NID_SLUG_OVERRIDES[5054] during P.7
    # (refetch hardening), or accept the rename via eurio_id_migrations.
    # This test ASSERTS the current (buggy) behavior so we know if/when it
    # changes. Update the expected value when the fix lands.
    (5054, "2 Euros (Economic and Monetary Union)",
     "DE", "Germany", 2009,
     "de-2009-2eur-economic-and-monetary-union",
     "V1 EMU regression — Saarland Bundesland mis-classified as joint-issue"),

    # DE-2010 NID 10069 — Bremen Bundesländer (cohort fil-rouge)
    (10069, "2 Euros (Bundesländer - \"Bremen\")",
     "DE", "Germany", 2010,
     "de-2010-2eur-bundeslander-bremen",
     "Bremen Bundesländer — cohort 19 fil-rouge, current Numista title"),

    # DE-2007 Treaty of Rome (joint-issue)
    # Joint-issue detection should fire; already covered in test_joint_issues
    # but re-verified here as cohort 19 case.
    (101, "2 Euros (Treaty of Rome)",
     "DE", "Germany", 2007,
     "de-2007-2eur-treaty-of-rome",
     "Treaty of Rome 2007 — joint-issue, cohort 19 addition"),
])
def test_cohort19_regression(nid, title, iso, name, year, expected_eurio, notes):
    """Lock current behavior on cohort 19 NIDs. See module docstring."""
    p = make_payload(nid, title, iso, name, year, is_commemo=True)
    r = eurio_id_from_numista_payload(p)
    assert r is not None, f"function returned None for {notes}"
    assert r.eurio_id == expected_eurio, (
        f"slug drift for nid {nid} ({notes}):\n"
        f"  expected: {expected_eurio}\n"
        f"  actual:   {r.eurio_id}"
    )


def test_cohort19_bleuet_variant():
    """FR-2018 Bleuet (NID 134283) — Numista title carries '; Coloured' suffix.
    Chantier variantes : la variante a son propre eurio_id `…-coloured` et
    pointe vers la canonique `fr-2018-2eur-bleuet-de-france`."""
    p = make_payload(
        134283, "2 Euros (Bleuet de France; Coloured)",
        "FR", "France", 2018, is_commemo=True,
    )
    r = eurio_id_from_numista_payload(p)
    assert r is not None
    assert r.canonical_eurio_id == "fr-2018-2eur-bleuet-de-france"
    assert r.eurio_id == "fr-2018-2eur-bleuet-de-france-coloured"
    assert r.is_variant is True
    assert r.variant_finish == "coloured"
    assert r.variant_kind == "coloured"
