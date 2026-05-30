"""Tests de l'adapter + pipeline LMDLP (sans réseau).

Couvre : extraction (pays/année/thème/qualité/prix), filtrage single-commemo,
groupage one-to-one + matching, et le promote (collapse qualité au prix min →
coin_market_quotes + coin_source_refs).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from sources._base.adapter import DiscoveredItem, SourceQuery  # noqa: E402
from sources._base.run_logger import start_run  # noqa: E402
from sources._base.slug_match import RefCoin  # noqa: E402
from sources.lmdlp.adapter import (  # noqa: E402
    LmdlpAdapter,
    extract_country_iso2,
    extract_price_eur,
    extract_quality,
    extract_theme_slug,
    extract_year,
    is_single_commemo,
    to_product,
)
from sources.lmdlp.pipeline import _promote  # noqa: E402
from state import Store  # noqa: E402


def _product(name, sku, *, country_cat="France", year_cat="2026",
             quality="UNC", price="1999", purchasable=True, in_stock=True,
             type_term="Pièce 2 euros commémorative", extra_cats=None):
    cats = [{"name": year_cat}, {"name": "Pièces / pays"}, {"name": country_cat}]
    if extra_cats:
        cats += [{"name": c} for c in extra_cats]
    return {
        "name": name, "sku": sku,
        "permalink": f"https://lamonnaiedelapiece.com/fr/product/{sku}/",
        "is_purchasable": purchasable, "is_in_stock": in_stock,
        "prices": {"price": price, "currency_minor_unit": 2},
        "categories": cats,
        "attributes": [
            {"name": "Qualité", "terms": [{"name": quality}]},
            {"name": "Type", "terms": [{"name": type_term}]},
        ],
    }


# ── extraction ──────────────────────────────────────────────────────────────


def test_extract_basic_fields():
    p = _product("2 euros France 2026 &#8211; Marine nationale UNC", "fr2026mnunc")
    assert extract_country_iso2(p) == "FR"
    assert extract_year(p) == 2026
    assert extract_theme_slug(p) == "marine-nationale"
    assert extract_quality(p) == "UNC"
    assert extract_price_eur(p) == 19.99


def test_year_fallback_from_sku():
    p = _product("2 euros Estonie &#8211; Sipsik UNC", "est2026siunc", year_cat="x")
    assert extract_year(p) == 2026


def test_theme_slug_stable_across_qualities():
    base = "2 euros France 2026 &#8211; Marine nationale"
    slugs = {
        extract_theme_slug(_product(f"{base} UNC", "a")),
        extract_theme_slug(_product(f"{base} BU FDC Coincard", "b")),
        extract_theme_slug(_product(f"{base} BE Proof colori", "c")),
    }
    assert slugs == {"marine-nationale"}


@pytest.mark.parametrize("name,expected", [
    # marque d'atelier allemande : lettre seule en tête → retirée
    ("2 euros Allemagne 2006 – D Schleswig-Holstein UNC", "schleswig-holstein"),
    ("2 euros Allemagne 2007 – F Traité de Rome UNC", "traite-de-rome"),
    # combo 5 ateliers, préfixe et suffixe
    ("2 euros Allemagne 2019 – ADFGJ Mur de Berlin UNC", "mur-de-berlin"),
    ("2 euros Allemagne 2022 – Erasmus ADFGJ UNC", "erasmus"),
])
def test_german_mint_mark_stripped(name, expected):
    assert extract_theme_slug(_product(name, "s", country_cat="Allemagne")) == expected


def test_mint_mark_not_stripped_for_non_german():
    # « A » initial sur une pièce non-allemande n'est pas une marque d'atelier.
    slug = extract_theme_slug(_product("2 euros France 2020 – A Truc UNC", "s"))
    assert slug == "a-truc"


def test_german_mints_collapse_to_one_key():
    raws = [
        _product("2 euros Allemagne 2006 – D Schleswig-Holstein UNC", "d", country_cat="Allemagne", year_cat="2006"),
        _product("2 euros Allemagne 2006 – F Schleswig-Holstein UNC", "f", country_cat="Allemagne", year_cat="2006"),
        _product("2 euros Allemagne 2006 – G Schleswig-Holstein BU FDC", "g", country_cat="Allemagne", year_cat="2006"),
    ]
    keys = {(p.country, p.year, p.theme_slug) for p in (to_product(r) for r in raws)}
    assert keys == {("DE", 2006, "schleswig-holstein")}


def test_price_minor_unit():
    assert extract_price_eur(_product("x", "s", price="345")) == 3.45
    assert extract_price_eur({"prices": {}}) is None


# ── filtrage single-commemo ──────────────────────────────────────────────────


@pytest.mark.parametrize("name,extra,ok", [
    ("2 euros France 2026 – Marine nationale UNC", {}, True),
    ("2 x 2 euros France 2026 – rouleau", {}, False),                  # multipack
    ("2 euros France 2026 – A + B", {}, False),                        # bundle
    ("Coffret 2 euros France 2026", {}, False),                        # blacklist
    ("2 euros France 2026 – Marine nationale UNC", {"type_term": "Monnaie normale"}, False),
    ("2 euros France 2026 – Marine nationale UNC", {"purchasable": False}, False),
])
def test_is_single_commemo(name, extra, ok):
    assert is_single_commemo(_product(name, "s", **extra))[0] is ok


# ── discover (fetch + ref_index mockés) ──────────────────────────────────────


def _fake_ref_index():
    return {
        ("FR", 2026): [RefCoin("fr-2026-2eur-marine-nationale", "FR", 2026, "marine-nationale")],
        ("HR", 2026): [RefCoin("hr-2026-2eur-radio-croate", "HR", 2026, "radio-croate")],
    }


def test_discover_groups_and_matches(monkeypatch):
    raws = [
        _product("2 euros France 2026 – Marine nationale UNC", "fr_unc", quality="UNC", price="395"),
        _product("2 euros France 2026 – Marine nationale BU FDC Coincard", "fr_bu", quality="BU FDC", price="2499"),
        _product("2 euros Croatie 2026 – Radio croate UNC", "hr_unc", country_cat="Croatie", quality="UNC", price="1999"),
        _product("2 euros Andorre 2026 – Inconnue UNC", "ad_x", country_cat="Andorre"),  # pas de candidat
    ]
    adapter = LmdlpAdapter(conn=object())
    monkeypatch.setattr(adapter, "fetch_all_2eur", lambda: raws)
    monkeypatch.setattr(adapter, "_load_referential", _fake_ref_index)

    items = list(adapter.discover(SourceQuery(source_id="lmdlp")))
    # 2 produits FR (matchés) + 1 HR ; Andorre droppé (aucun candidat).
    assert len(items) == 3
    fr = [i for i in items if i.target_eurio_id == "fr-2026-2eur-marine-nationale"]
    assert {i.condition_raw for i in fr} == {"UNC", "BU FDC"}
    assert all(i.listing_currency == "EUR" for i in items)


def test_discover_country_filter(monkeypatch):
    raws = [
        _product("2 euros France 2026 – Marine nationale UNC", "fr_unc"),
        _product("2 euros Croatie 2026 – Radio croate UNC", "hr_unc", country_cat="Croatie"),
    ]
    adapter = LmdlpAdapter(conn=object())
    monkeypatch.setattr(adapter, "fetch_all_2eur", lambda: raws)
    monkeypatch.setattr(adapter, "_load_referential", _fake_ref_index)
    items = list(adapter.discover(SourceQuery(source_id="lmdlp", country="HR")))
    assert [i.target_eurio_id for i in items] == ["hr-2026-2eur-radio-croate"]


# ── promote (Store temp) ─────────────────────────────────────────────────────


def _item(eurio_id, quality, price, sku, in_stock=True):
    return DiscoveredItem(
        source_ref=f"lmdlp/{sku}",
        source_url=f"https://lamonnaiedelapiece.com/fr/product/{sku}/",
        target_eurio_id=eurio_id, condition_raw=quality,
        listing_price=price, listing_currency="EUR",
        raw_payload={"sku": sku, "in_stock": in_stock},
    )


def _seed_registry(conn):
    """coin_source_refs.source a une FK vers source_registry(id) ; en prod le
    registry est seedé (seed_source_registry). On y met 'lmdlp' ici."""
    conn.execute(
        "INSERT OR IGNORE INTO source_registry (id, display_name, kind) "
        "VALUES ('lmdlp', 'La Monnaie de la Pièce', 'community')"
    )


def test_promote_writes_quotes_and_ref(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_registry(conn)
    with start_run(conn, source="lmdlp", kind="run", force=True) as run:
        items = [
            _item("fr-2026-2eur-marine", "UNC", 3.95, "a"),
            _item("fr-2026-2eur-marine", "BU FDC", 24.99, "b"),
            # doublon de qualité « BU FDC » → collapse au prix min (12.50)
            _item("fr-2026-2eur-marine", "BU FDC", 12.50, "c"),
        ]
        res = _promote(conn, run, items)

    assert res.n_coins == 1
    assert res.n_quotes == 2  # UNC + BU FDC (collapsé)
    rows = conn.execute(
        "SELECT condition_raw, condition_normalized, p50, sample_size "
        "FROM coin_market_quotes WHERE eurio_id='fr-2026-2eur-marine' "
        "ORDER BY condition_raw"
    ).fetchall()
    by_q = {r["condition_raw"]: r for r in rows}
    assert by_q["UNC"]["p50"] == 3.95
    assert by_q["UNC"]["condition_normalized"] == "unknown"
    assert by_q["BU FDC"]["p50"] == 12.50          # min des deux BU FDC
    assert by_q["BU FDC"]["sample_size"] == 2
    ref = conn.execute(
        "SELECT source, source_url FROM coin_source_refs "
        "WHERE target_id='fr-2026-2eur-marine' AND target_kind='coin'"
    ).fetchone()
    assert ref["source"] == "lmdlp"
    assert ref["source_url"].startswith("https://lamonnaiedelapiece.com")


def test_load_fr_aux_slugs_and_match(tmp_path):
    """_load_referential peuple aux_slugs depuis les signaux FR, et discover
    matche un libellé FR abrégé via le titre i18n FR."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    conn.execute(
        "INSERT OR IGNORE INTO coins (eurio_id, country, year, face_value, is_commemorative) "
        "VALUES ('be-2009-2eur-economic-monetary-union', 'BE', 2009, 2.0, 1)"
    )
    conn.execute(
        "INSERT INTO coin_names_i18n (eurio_id, lang, title, source, method) "
        "VALUES ('be-2009-2eur-economic-monetary-union', 'fr', "
        "'2 euros Union économique et monétaire', 'numista_api', 'scrape')"
    )
    adapter = LmdlpAdapter(conn=conn)
    aux = adapter._load_fr_aux_slugs()
    assert "union-economique-et-monetaire" in aux["be-2009-2eur-economic-monetary-union"]

    # discover : un produit FR « Union économique et monétaire » matche.
    raws = [_product("2 euros Belgique 2009 – Union économique et monétaire UNC",
                     "be_uem", country_cat="Belgique", year_cat="2009")]
    import pytest as _pt
    monkeypatch = _pt.MonkeyPatch()
    monkeypatch.setattr(adapter, "fetch_all_2eur", lambda: raws)
    items = list(adapter.discover(SourceQuery(source_id="lmdlp")))
    monkeypatch.undo()
    assert [i.target_eurio_id for i in items] == ["be-2009-2eur-economic-monetary-union"]


def test_promote_skips_priceless(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    with start_run(conn, source="lmdlp", kind="run", force=True) as run:
        res = _promote(conn, run, [_item("x-2026-2eur-y", "UNC", None, "a")])
    assert res.n_quotes == 0 and res.n_coins == 0
