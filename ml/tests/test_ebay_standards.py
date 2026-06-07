"""Chemin STANDARD eBay : attribution, plages d'ères, cohort-scoping, discover.

Verrouille le câblage du Chunk B (élargissement du scrape aux pièces
``is_commemorative=0``). L'exclusion commémo par theme-match positif (i18n)
est validée sur données réelles par ``scripts.standards_attribution_diag`` ;
ici on couvre la logique pure + le routage, sans fixtures i18n lourdes.
"""
from __future__ import annotations

import json

import pytest

from sources._base.adapter import DiscoveryGroup, SourceQuery
from sources.cohort_scope import EbayGroup, cohort_ebay_groups
from sources.ebay.standards import (
    attribute_standard_listing,
    eras_for_year,
    load_standard_eras,
)
from store import Store
from tests.test_ebay_adapter import _detail, _make_adapter, _summary

_DENOM = 2.0

# Ères ES (carte/portrait/type) : (eurio_id, année de début).
_ES_ERAS = [
    ("es-1999-2eur-standard-juan-carlos-i-1st-type-1st-map", 1999),
    ("es-2007-2eur-standard-juan-carlos-i-1st-type-2nd-map", 2007),
    ("es-2010-2eur-standard-juan-carlos-i-2nd-type-2nd-map", 2010),
    ("es-2015-2eur-standard-felipe-vi", 2015),
]


def _seed(conn, eurio_id, country, year, *, is_comm, canonical=None, theme=None):
    conn.execute(
        """
        INSERT OR REPLACE INTO coins (
          eurio_id, country, country_name, year, face_value,
          is_commemorative, theme, canonical_eurio_id, raw_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}')
        """,
        (eurio_id, country, country, year, _DENOM, int(is_comm), theme, canonical),
    )


def _seed_es_standards(conn):
    for eid, year in _ES_ERAS:
        _seed(conn, eid, "ES", year, is_comm=False)


def _seed_cohort(conn, name, eurio_ids):
    conn.execute(
        "INSERT OR REPLACE INTO experiment_cohorts (id, name, eurio_ids_json) "
        "VALUES (?, ?, ?)",
        (name, name, json.dumps(eurio_ids)),
    )


# ── Plages d'ères ────────────────────────────────────────────────────────────


def test_load_standard_eras_computes_ranges(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_es_standards(conn)
    eras = load_standard_eras(conn, _DENOM, "ES")
    ranges = {e.eurio_id: (e.year_from, e.year_to) for e in eras}
    assert ranges["es-1999-2eur-standard-juan-carlos-i-1st-type-1st-map"] == (1999, 2006)
    assert ranges["es-2007-2eur-standard-juan-carlos-i-1st-type-2nd-map"] == (2007, 2009)
    assert ranges["es-2010-2eur-standard-juan-carlos-i-2nd-type-2nd-map"] == (2010, 2014)
    assert ranges["es-2015-2eur-standard-felipe-vi"] == (2015, 9999)


def test_eras_for_year_membership(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_es_standards(conn)
    eras = load_standard_eras(conn, _DENOM, "ES")
    assert [e.eurio_id for e in eras_for_year(eras, 2016)] == ["es-2015-2eur-standard-felipe-vi"]
    assert [e.eurio_id for e in eras_for_year(eras, 2003)][0].startswith("es-1999")
    assert eras_for_year(eras, 1990) == []  # avant la 1re ère


def test_same_year_collision_returns_two_eras(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed(conn, "mt-2008-2eur-standard-2nd-map", "MT", 2008, is_comm=False)
    _seed(conn, "mt-2026-2eur-standard-valletta", "MT", 2026, is_comm=False)
    _seed(conn, "mt-2026-2eur-standard-il-kelb-tal-fenek", "MT", 2026, is_comm=False)
    eras = load_standard_eras(conn, _DENOM, "MT")
    hits = eras_for_year(eras, 2026)
    assert len(hits) == 2  # collision → ambiguous en aval


# ── Attribution ──────────────────────────────────────────────────────────────


def test_attribute_single_by_year_range(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_es_standards(conn)
    m = attribute_standard_listing(
        "Spanien 2 Euro Kursmünze 2016, zirkuliert", _DENOM, "ES", conn=conn
    )
    assert m.verdict == "single"
    assert m.target_eurio_id == "es-2015-2eur-standard-felipe-vi"
    # Doctrine : les ères du pays sont portées en candidates même pour 'single'.
    assert len(m.candidates) == 4


def test_attribute_commemo_keyword_excluded(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_es_standards(conn)
    m = attribute_standard_listing(
        "2 Euro Gedenkmünze 2016 alle Nationen", _DENOM, "ES", conn=conn
    )
    assert m.verdict == "commemo"
    assert m.reason == "commemo_keyword"


def test_attribute_double_negative_kept(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_es_standards(conn)
    # Mot-clé standard co-présent → l'exclusion commémo est levée.
    m = attribute_standard_listing(
        "Spanien 2 Euro Kursmünze KEINE Gedenkmünze 2016", _DENOM, "ES", conn=conn
    )
    assert m.verdict == "single"
    assert m.target_eurio_id == "es-2015-2eur-standard-felipe-vi"


def test_attribute_yearless_is_ambiguous(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_es_standards(conn)
    m = attribute_standard_listing(
        "Spanien 2 Euro Kursmünze Jahr nach Wahl", _DENOM, "ES", conn=conn
    )
    assert m.verdict == "ambiguous"
    assert m.target_eurio_id is None
    assert len(m.candidates) == 4


def test_attribute_denomination_contradiction(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_es_standards(conn)
    m = attribute_standard_listing("Spanien 1 Euro 2016 Kursmünze", _DENOM, "ES", conn=conn)
    assert m.verdict == "no_match"
    assert m.reason == "group_contradict_denomination"


# ── Groupes avers (design_group collapse) ─────────────────────────────────────

# BE 2€ standard groupés par avers (cf. chantier design-groups-standards).
_BE_GROUPED = [
    ("be-1999-2eur-standard-albert-ii-1st-map-1st-type-1st-portrait", 1999, "be-2euro-albert-ii-t1"),
    ("be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait", 2007, "be-2euro-albert-ii-t1"),
    ("be-2008-2eur-standard-albert-ii-2nd-map-2nd-type-2nd-portrait", 2008, "be-2euro-albert-ii-t2"),
    ("be-2009-2eur-standard-albert-ii-2nd-map-2nd-type-1st-portrait", 2009, "be-2euro-albert-ii-t2"),
    ("be-2014-2eur-standard-philippe", 2014, "be-2euro-philippe-t1"),
]


def _seed_be_grouped(conn):
    for gid in {g for _, _, g in _BE_GROUPED}:
        conn.execute(
            "INSERT OR REPLACE INTO design_groups (id, designation) VALUES (?, ?)", (gid, gid)
        )
    for eid, year, gid in _BE_GROUPED:
        _seed(conn, eid, "BE", year, is_comm=False)
        conn.execute(
            "UPDATE coins SET design_group_id=? WHERE eurio_id=?", (gid, eid)
        )


def test_load_standard_eras_collapses_groups(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_be_grouped(conn)
    eras = load_standard_eras(conn, _DENOM, "BE")
    by_group = {e.group_id: e for e in eras}
    # 5 Types → 3 ères (groupes avers).
    assert set(by_group) == {"be-2euro-albert-ii-t1", "be-2euro-albert-ii-t2", "be-2euro-philippe-t1"}
    t1 = by_group["be-2euro-albert-ii-t1"]
    # be-1999 + be-2007 fusionnés : la plage couvre 1999→2007.
    assert (t1.year_from, t1.year_to) == (1999, 2007)
    assert set(t1.eurio_ids) == {
        "be-1999-2eur-standard-albert-ii-1st-map-1st-type-1st-portrait",
        "be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait",
    }
    assert by_group["be-2euro-philippe-t1"].year_to == 9999  # dernier groupe ouvert


def test_attribute_grouped_resolves_year_prior(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_be_grouped(conn)
    # Un listing 2007 : be-2007 ne starve plus — il tombe dans le groupe t1.
    m07 = attribute_standard_listing(
        "Belgien 2 Euro Kursmünze 2007 zirkuliert", _DENOM, "BE", conn=conn
    )
    assert m07.verdict == "single"
    # prior résolu au millésime DANS le groupe → be-2007 (pas be-1999).
    assert m07.target_eurio_id == "be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait"
    # candidates = les 5 Types du pays (review humaine).
    assert len(m07.candidates) == 5

    # Un listing 2003 : même groupe t1, prior = be-1999.
    m03 = attribute_standard_listing(
        "Belgien 2 Euro Kursmünze 2003 zirkuliert", _DENOM, "BE", conn=conn
    )
    assert m03.verdict == "single"
    assert m03.target_eurio_id == "be-1999-2eur-standard-albert-ii-1st-map-1st-type-1st-portrait"


def test_grouped_commemo_excluded_before_widened_range(tmp_path):
    """Étape 4 (theme-match commémo) AVANT étape 5 (plage) : la fenêtre t1
    élargie à [1999,2007] ne doit pas absorber la commémo Traité de Rome 2007."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_be_grouped(conn)
    # Commémo BE 2007 (Traité de Rome) + titre i18n discriminant (theme-match).
    _seed(conn, "be-2007-2eur-commemo-rome", "BE", 2007, is_comm=True)
    conn.execute(
        "INSERT OR IGNORE INTO source_registry (id, display_name, kind) VALUES "
        "('eurio_derived', 'Eurio derived', 'derived')"
    )
    conn.execute(
        "INSERT INTO coin_names_i18n (eurio_id, lang, title, source) VALUES (?, ?, ?, ?)",
        ("be-2007-2eur-commemo-rome", "de", "Vertrag von Rom", "eurio_derived"),
    )
    m = attribute_standard_listing(
        "Belgien 2 Euro 2007 Vertrag von Rom", _DENOM, "BE", conn=conn
    )
    assert m.verdict == "commemo"
    assert m.reason.startswith("commemo_in_standard_run:")


def test_attribute_multiyear_same_group_resolves(tmp_path):
    """Lot multi-années dont toutes les années tombent dans UN groupe → attribué
    (récupère l'offre type « Kursmünzen 2000-2008 » Juan Carlos)."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_be_grouped(conn)
    m = attribute_standard_listing(
        "Belgien 2 Euro Kursmünze 2003 2005 König Albert II", _DENOM, "BE", conn=conn
    )
    assert m.verdict == "single"
    assert m.target_eurio_id == "be-1999-2eur-standard-albert-ii-1st-map-1st-type-1st-portrait"
    assert m.reason.startswith("year_group_resolved")


def test_attribute_multiyear_spans_groups_is_ambiguous(tmp_path):
    """Lot multi-années qui chevauche plusieurs groupes → ambigu (review)."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_be_grouped(conn)
    m = attribute_standard_listing(
        "Belgien 2 Euro Lot 2005 2009 Kursmünze", _DENOM, "BE", conn=conn
    )
    assert m.verdict == "ambiguous"
    assert m.reason.startswith("year_spans_groups")


def test_attribute_multiyear_foreign_lot_not_resolved(tmp_path):
    """Lot multi-années sans confirmation du pays cible → ambigu (anti-leak
    inter-pays : « Serie de Finlandia 2017-2018 » ne doit pas devenir ES/BE)."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_be_grouped(conn)
    m = attribute_standard_listing("Serie 2003 2005 Lot Münzen", _DENOM, "BE", conn=conn)
    assert m.verdict == "ambiguous"
    assert m.reason == "year_multi_country_unconfirmed"


def test_attribute_multiyear_commemo_still_excluded(tmp_path):
    """Un lot multi-années dont une année hit un thème commémo → commemo."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_be_grouped(conn)
    _seed(conn, "be-2007-2eur-commemo-rome", "BE", 2007, is_comm=True)
    conn.execute(
        "INSERT OR IGNORE INTO source_registry (id, display_name, kind) VALUES "
        "('eurio_derived', 'Eurio derived', 'derived')"
    )
    conn.execute(
        "INSERT INTO coin_names_i18n (eurio_id, lang, title, source) VALUES (?, ?, ?, ?)",
        ("be-2007-2eur-commemo-rome", "de", "Vertrag von Rom", "eurio_derived"),
    )
    m = attribute_standard_listing(
        "Belgien 2 Euro 2003 2007 Vertrag von Rom", _DENOM, "BE", conn=conn
    )
    assert m.verdict == "commemo"


def test_standard_view_counts_design_groups(tmp_path):
    """v_ebay_standard_groups.n_eras = nombre de groupes avers (pas de Types)."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_be_grouped(conn)        # 5 Types BE → 3 groupes
    _seed_es_standards(conn)      # 4 Types ES non groupés → 4 (legacy)
    rows = {
        r["country"]: r["n_eras"]
        for r in conn.execute(
            "SELECT country, n_eras FROM v_ebay_standard_groups WHERE country IN ('BE','ES')"
        )
    }
    assert rows["BE"] == 3
    assert rows["ES"] == 4


# ── Cohort-scoping ───────────────────────────────────────────────────────────


def test_cohort_routes_standard_commemo_variant(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_es_standards(conn)  # es-* standards → v_ebay_standard_groups
    _seed(conn, "es-2016-2eur-segovia", "ES", 2016, is_comm=True, theme="segovia")
    _seed(conn, "es-2018-2eur-coloured", "ES", 2018, is_comm=False,
          canonical="es-2015-2eur-standard-felipe-vi")  # variante → non_scrapable
    _seed(conn, "eu-2009-2eur-emu", "eu", 2009, is_comm=True, theme="emu")  # eu → non_scrapable
    _seed_cohort(conn, "mix-test", [
        "es-1999-2eur-standard-juan-carlos-i-1st-type-1st-map",
        "es-2016-2eur-segovia",
        "es-2018-2eur-coloured",
        "eu-2009-2eur-emu",
    ])

    groups, non_scrapable = cohort_ebay_groups(store, "mix-test")

    std = [g for g in groups if g.kind == "standard"]
    comm = [g for g in groups if g.kind == "commemorative"]
    assert std == [EbayGroup(_DENOM, "ES", None, 4, "standard")]  # 4 ères ES
    assert comm == [EbayGroup(_DENOM, "ES", 2016, 1, "commemorative")]
    assert set(non_scrapable) == {"es-2018-2eur-coloured", "eu-2009-2eur-emu"}


# ── Discover (smoke, fake client) ────────────────────────────────────────────


def test_discover_standard_group_resolves_and_yields(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_es_standards(conn)
    s = _summary("ITEM_STD", "2 Euro Spanien 2016 Kursmünze bankfrisch", price=5.0)
    detail = _detail("ITEM_STD", additional=["https://i.ebayimg.com/HD-1.jpg"])
    adapter, _ = _make_adapter(store, search=[{"itemSummaries": [s]}], items={"ITEM_STD": detail})

    items = list(adapter.discover(SourceQuery(
        source_id="ebay",
        discovery_group=DiscoveryGroup(_DENOM, "ES", year=None, kind="standard"),
    )))

    assert items, "le listing standard doit être gardé et yieldé"
    assert all(it.target_eurio_id == "es-2015-2eur-standard-felipe-vi" for it in items)


def test_discover_standard_excludes_commemo_keyword(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_es_standards(conn)
    s = _summary("ITEM_COMM", "2 Euro Gedenkmünze Spanien 2016 alle Nationen", price=5.0)
    detail = _detail("ITEM_COMM", additional=[])
    adapter, _ = _make_adapter(store, search=[{"itemSummaries": [s]}], items={"ITEM_COMM": detail})

    items = list(adapter.discover(SourceQuery(
        source_id="ebay",
        discovery_group=DiscoveryGroup(_DENOM, "ES", year=None, kind="standard"),
    )))

    assert items == [], "un titre auto-déclaré Gedenkmünze est exclu du run standard"
