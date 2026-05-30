"""Tests du parser BCE multilingue (chantier BCE i18n, 2026-05-29).

Couvre :
- l'identification des champs par label sur la page EN d'ancrage ;
- la fusion des descriptions multi-paragraphes ;
- le mapping positionnel des langues dont le séparateur diffère (lv = point,
  mt = aucun séparateur) ou qui omettent un champ de tête (LU 2023 sans Feature) ;
- le garde-fou d'alignement (`_lang_values_for_coin` retourne None si la
  structure non-EN ne correspond pas au `_field_order` EN).
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from referential.scrape_bce_i18n import _lang_values_for_coin  # noqa: E402
from referential.scrape_bce_images import (  # noqa: E402
    _classify_en_label,
    _strip_leading_strong,
    parse_bce_lang_blocks,
    parse_bce_page,
)
from bs4 import BeautifulSoup  # noqa: E402


def _block(country: str, paras: list[str], img: str = "coin.jpg") -> str:
    """Un bloc BCE : <img> puis <h3>pays</h3> puis des <p>."""
    ps = "".join(paras)
    return f'<img src="/euro/coins/comm/shared/img/{img}" alt=""><h3>{country}</h3>{ps}'


def _strong_p(label: str, value: str) -> str:
    return f"<p><strong>{label}</strong> {value}</p>"


def _plain_p(text: str) -> str:
    return f"<p>{text}</p>"


# ── _strip_leading_strong / _classify_en_label ────────────────────────────


def test_strip_leading_strong_colon():
    soup = BeautifulSoup(_strong_p("Feature:", "90th anniversary"), "lxml")
    assert _strip_leading_strong(soup.find("p")) == "90th anniversary"


def test_strip_leading_strong_preserves_trailing_period():
    soup = BeautifulSoup(_strong_p("Feature:", "A sentence ending here."), "lxml")
    assert _strip_leading_strong(soup.find("p")) == "A sentence ending here."


def test_strip_leading_strong_period_separator():
    # letton : « Apraksts. » (point, pas deux-points)
    soup = BeautifulSoup(_strong_p("Apraksts.", "Uz monētas"), "lxml")
    assert _strip_leading_strong(soup.find("p")) == "Uz monētas"


def test_strip_leading_strong_no_separator():
    # maltais : « Volum tal-ħruġ 2 miljun » (aucun séparateur)
    soup = BeautifulSoup(_strong_p("Volum tal-ħruġ", "2 miljun munita"), "lxml")
    assert _strip_leading_strong(soup.find("p")) == "2 miljun munita"


def test_classify_en_label():
    assert _classify_en_label("Feature:") == "feature"
    assert _classify_en_label("Description:") == "description"
    assert _classify_en_label("Issuing volume:") == "issuing_volume"
    assert _classify_en_label("Issuing date:") == "issuing_date"
    assert _classify_en_label("Unrelated:") is None


# ── parse_bce_page (EN, label-based) ───────────────────────────────────────


def test_parse_en_basic():
    html = _block("Finland", [
        _strong_p("Feature:", "90th anniversary of Finland's independence"),
        _strong_p("Description:", "The coin shows a boat."),
        _strong_p("Issuing volume:", "2 million coins"),
        _strong_p("Issuing date:", "December 2007"),
    ])
    coins = parse_bce_page(html, 2007)
    assert len(coins) == 1
    c = coins[0]
    assert c["country"] == "FI"
    assert c["feature"] == "90th anniversary of Finland's independence"
    assert c["description"] == "The coin shows a boat."
    assert c["issuing_volume"] == "2 million coins"
    assert c["issuing_date"] == "December 2007"
    assert c["_block_index"] == 0
    assert c["_field_order"] == ["feature", "description", "issuing_volume", "issuing_date"]


def test_parse_en_multiparagraph_description():
    html = _block("France", [
        _strong_p("Feature:", "25th anniversary of the pink ribbon"),
        _strong_p("Description:", "Since the 1990s the fight has been a cause."),
        _plain_p("The design represents a woman's bust."),  # continuation, pas de strong
        _strong_p("Issuing volume:", "10 000 000 coins"),
        _strong_p("Issuing date:", "September 2017"),
    ])
    coins = parse_bce_page(html, 2017)
    assert len(coins) == 1
    c = coins[0]
    assert c["description"] == (
        "Since the 1990s the fight has been a cause. "
        "The design represents a woman's bust."
    )
    assert c["issuing_volume"] == "10 000 000 coins"
    assert c["_field_order"] == ["feature", "description", "issuing_volume", "issuing_date"]


def test_parse_en_missing_feature_is_skipped():
    # LU 2023 #2 : second coin sans label Feature → sauté (pas de titre).
    html = (
        _block("Luxembourg", [
            _strong_p("Feature:", "175th anniversary of Parliament"),
            _strong_p("Description:", "Effigy of the Grand Duke."),
            _strong_p("Issuing volume:", "500 000 coins"),
            _strong_p("Issuing date:", "February 2023"),
        ])
        + _block("Luxembourg", [
            _strong_p("Description:", "The design depicts the Grand Duke."),
            _strong_p("Issuing volume:", "500 000 coins"),
            _strong_p("Issuing date:", "February 2023"),
        ], img="coin2.jpg")
    )
    coins = parse_bce_page(html, 2023)
    # Seul le premier coin (avec Feature) est retourné.
    assert len(coins) == 1
    assert coins[0]["feature"].startswith("175th anniversary")
    # Mais le block_index reste stable : le 2e bloc a consommé l'index 1.
    assert coins[0]["_block_index"] == 0


# ── parse_bce_lang_blocks + alignement ─────────────────────────────────────


def test_lang_blocks_positional_and_indexed():
    # 2 blocs ; le 2e a un séparateur point (lv-style) — peu importe, on prend
    # juste les valeurs positionnelles.
    html = (
        _block("Somija", [
            _strong_p("Motīvs:", "Somijas 90 gadadiena"),
            _strong_p("Apraksts.", "Uz monētas attēlota laiva."),
            _strong_p("Emisijas apjoms:", "2 milj"),
            _strong_p("Emisijas datums:", "2007 decembris"),
        ])
        + _block("Vācija", [
            _strong_p("Motīvs:", "Brēmene"),
            _strong_p("Apraksts.", "Pilsētas rātsnams."),
            _strong_p("Emisijas apjoms:", "30 milj"),
            _strong_p("Emisijas datums:", "2010 februāris"),
        ], img="de.jpg")
    )
    blocks = parse_bce_lang_blocks(html)
    assert set(blocks) == {0, 1}
    assert blocks[0][0] == "Somijas 90 gadadiena"
    assert blocks[0][1] == "Uz monētas attēlota laiva."
    assert blocks[1][0] == "Brēmene"


def test_lang_values_for_coin_maps_by_field_order():
    coin = {
        "_block_index": 0,
        "_field_order": ["feature", "description", "issuing_volume", "issuing_date"],
    }
    blocks = {0: ["Le titre", "La description", "2 millions", "décembre 2007"]}
    title, desc = _lang_values_for_coin(coin, blocks)
    assert title == "Le titre"
    assert desc == "La description"


def test_lang_values_for_coin_no_description_field():
    coin = {
        "_block_index": 0,
        "_field_order": ["feature", "issuing_volume", "issuing_date"],
    }
    blocks = {0: ["Titre seul", "2 millions", "décembre"]}
    title, desc = _lang_values_for_coin(coin, blocks)
    assert title == "Titre seul"
    assert desc is None


def test_lang_values_for_coin_trailing_extra_field_maps_prefix():
    # EN omet la date (3 champs) ; la page non-EN l'inclut (4 valeurs). Le
    # préfixe [feature, description] reste aligné → on mappe les deux.
    coin = {
        "_block_index": 0,
        "_field_order": ["feature", "description", "issuing_volume"],
    }
    blocks = {0: ["Le titre", "La description", "2 millions", "déc. 2024"]}
    title, desc = _lang_values_for_coin(coin, blocks)
    assert title == "Le titre"
    assert desc == "La description"


def test_lang_values_for_coin_shorter_drops_description():
    # HR 2013 Boccaccio : EN = [feature, description, volume, date] mais la
    # page non-EN omet la description → vals[1] y est le VOLUME. On écrit le
    # titre seul, jamais le volume comme description.
    coin = {
        "_block_index": 0,
        "_field_order": ["feature", "description", "issuing_volume", "issuing_date"],
    }
    blocks = {0: ["700e anniversaire", "10 000 000 kovanica", "srpanj 2013."]}
    title, desc = _lang_values_for_coin(coin, blocks)
    assert title == "700e anniversaire"
    assert desc is None


def test_lang_values_for_coin_missing_block_returns_none():
    coin = {"_block_index": 5, "_field_order": ["feature"]}
    assert _lang_values_for_coin(coin, {0: ["x"]}) is None


def test_lang_values_for_coin_empty_block_returns_none():
    coin = {"_block_index": 0, "_field_order": ["feature", "description"]}
    assert _lang_values_for_coin(coin, {0: []}) is None
