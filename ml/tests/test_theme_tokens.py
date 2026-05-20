"""Tests for ml.sources.ebay.theme_tokens."""

from __future__ import annotations

import sqlite3

import pytest

from sources.ebay.theme_tokens import (
    COUNTRY_TOKENS_BY_LANG,
    STOP_WORDS_BY_LANG,
    extract_tokens,
    load_i18n_title,
    normalize,
)


# ── normalize ─────────────────────────────────────────────────────────────


def test_normalize_lowercases():
    assert normalize("ABC") == "abc"


def test_normalize_drops_accents():
    assert normalize("Gypaète barbu") == "gypaete barbu"
    assert normalize("Année") == "annee"
    assert normalize("Français") == "francais"
    assert normalize("España") == "espana"
    assert normalize("Österreich") == "osterreich"
    assert normalize("Müller") == "muller"


def test_normalize_preserves_punctuation_and_spaces():
    assert normalize("2 Euros - 1ère carte") == "2 euros - 1ere carte"


def test_normalize_empty():
    assert normalize("") == ""


# ── extract_tokens ────────────────────────────────────────────────────────


def test_extract_tokens_fr_kniefall():
    """Titre Numista FR avec thème historique fort."""
    tokens = extract_tokens("2 Euros - Génuflexion de Varsovie", "fr")
    # "génuflexion" et "varsovie" attendus, "de" stop, "2" et "euros" stop/drop
    assert "genuflexion" in tokens
    assert "varsovie" in tokens
    assert "euros" not in tokens
    assert "de" not in tokens


def test_extract_tokens_en_bearded_vulture():
    tokens = extract_tokens("2 Euros Bearded vulture", "en")
    assert "bearded" in tokens
    assert "vulture" in tokens
    assert "euros" not in tokens


def test_extract_tokens_de_kniefall():
    tokens = extract_tokens("2 Euro Kniefall von Warschau", "de")
    assert "kniefall" in tokens
    assert "warschau" in tokens
    assert "von" not in tokens
    assert "euro" not in tokens


def test_extract_tokens_drops_country_andorra_fr():
    """COUNTRY_TOKENS_BY_LANG['fr'] doit virer 'andorre' du titre."""
    tokens = extract_tokens("2 euros Andorre - Hymne national", "fr")
    assert "andorre" not in tokens
    assert "hymne" in tokens or "national" in tokens


def test_extract_tokens_drops_country_germany_de():
    """Title peut mentionner 'Deutschland' explicitement."""
    tokens = extract_tokens("2 Euro Deutschland Wiedervereinigung", "de")
    assert "deutschland" not in tokens
    assert "wiedervereinigung" in tokens


def test_extract_tokens_drops_min_len():
    """Tokens < 4 chars doivent être virés (war/map/etc.)."""
    tokens = extract_tokens("2 Euros 1st map", "en")
    # 'map' = 3 chars → drop. '1st' = ordinal → drop. '2' → drop.
    assert tokens == []


def test_extract_tokens_drops_pure_digits_and_ordinals():
    tokens = extract_tokens("100th anniversary year 1992 birth", "en")
    # "100th" = ordinal → drop. "1992" = digits → drop. "anniversary",
    # "year", "birth" = stop. → vide.
    assert "1992" not in tokens
    assert "100th" not in tokens
    assert "anniversary" not in tokens


def test_extract_tokens_cap_max_words():
    title = "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta"
    tokens = extract_tokens(title, "en", max_words=3)
    assert len(tokens) == 3
    assert tokens == ["alpha", "beta", "gamma"]


def test_extract_tokens_preserves_order():
    tokens = extract_tokens("Genuflexion Varsovie Allemagne", "fr")
    # "allemagne" est dans countries → drop. "genuflexion" puis "varsovie".
    assert tokens == ["genuflexion", "varsovie"]


def test_extract_tokens_empty_title():
    assert extract_tokens("", "fr") == []


def test_extract_tokens_unknown_lang_no_stop():
    """Lang inconnue : pas de stop-words appliqués, mais min_len/digits ok."""
    tokens = extract_tokens("hello world test", "xx")
    assert "hello" in tokens
    assert "world" in tokens
    assert "test" in tokens


def test_extract_tokens_min_len_zero_keeps_short():
    tokens = extract_tokens("Hymne d'Andorre", "fr", min_len=2)
    # "de" est stop (dropé même à min_len=2), "andorre" est country.
    # → seul "hymne" attendu.
    assert tokens == ["hymne"]


# ── STOP_WORDS_BY_LANG / COUNTRY_TOKENS_BY_LANG sanity ────────────────────


def test_stop_words_cover_six_langs():
    assert set(STOP_WORDS_BY_LANG.keys()) == {"en", "fr", "de", "it", "es", "nl"}


def test_country_tokens_cover_six_langs():
    assert set(COUNTRY_TOKENS_BY_LANG.keys()) == {"en", "fr", "de", "it", "es", "nl"}


def test_stop_words_no_accents():
    """Tous les stop-words doivent être en forme normalisée (sans accents)."""
    for lang, words in STOP_WORDS_BY_LANG.items():
        for w in words:
            assert normalize(w) == w, f"stop word {w!r} in {lang} not normalized"


def test_country_tokens_no_accents():
    for lang, tokens in COUNTRY_TOKENS_BY_LANG.items():
        for t in tokens:
            assert normalize(t) == t, f"country token {t!r} in {lang} not normalized"


# ── load_i18n_title ───────────────────────────────────────────────────────


@pytest.fixture
def conn_with_i18n():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE coin_names_i18n (
          eurio_id   TEXT NOT NULL,
          lang       TEXT NOT NULL,
          title      TEXT NOT NULL,
          source     TEXT NOT NULL DEFAULT 'numista',
          confidence TEXT NOT NULL DEFAULT 'canon',
          model      TEXT,
          fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (eurio_id, lang)
        );
        INSERT INTO coin_names_i18n (eurio_id, lang, title) VALUES
          ('fr-1999-2eur-standard', 'fr', '2 euros 1re carte'),
          ('fr-1999-2eur-standard', 'en', '2 Euros 1st map'),
          ('ad-2025-2eur-bearded-vulture', 'fr', '2 euros Gypaète barbu'),
          ('ad-2025-2eur-bearded-vulture', 'en', '2 Euros Bearded vulture');
        """
    )
    yield conn
    conn.close()


def test_load_i18n_title_hit(conn_with_i18n):
    assert load_i18n_title(conn_with_i18n, "fr-1999-2eur-standard", "fr") == "2 euros 1re carte"


def test_load_i18n_title_miss(conn_with_i18n):
    assert load_i18n_title(conn_with_i18n, "fr-1999-2eur-standard", "de") is None


def test_load_i18n_title_unknown_eurio(conn_with_i18n):
    assert load_i18n_title(conn_with_i18n, "xx-9999-9eur-nope", "fr") is None


def test_load_i18n_title_works_with_plain_tuple_factory():
    """Si la conn n'a pas Row factory, on retombe sur l'index entier."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE coin_names_i18n (
          eurio_id TEXT, lang TEXT, title TEXT,
          PRIMARY KEY (eurio_id, lang)
        );
        INSERT INTO coin_names_i18n VALUES ('e1', 'fr', 'hello');
        """
    )
    assert load_i18n_title(conn, "e1", "fr") == "hello"
    conn.close()
