"""Tests pour scripts.llm_coin_aliases (chunk C2a-2).

Couvre les deux invariants de la Definition of Done :
- le garde-fou anti-collision rejette un alias qui matche le vocab d'une
  sœur du groupe (et seulement en limite de mot) ;
- un alias `source='llm'` ingéré produit bien un `hit` du theme-matcher.
"""

from __future__ import annotations

import sqlite3

import pytest

from scripts.llm_coin_aliases import _parse_years, _word_match, collides
from sources.ebay.queries import _theme_match_state


# ── _parse_years ───────────────────────────────────────────────────────────

def test_parse_years_range():
    assert _parse_years("2017-2021") == [2017, 2018, 2019, 2020, 2021]


def test_parse_years_single():
    assert _parse_years("2018") == [2018]


def test_parse_years_list_and_dedup():
    assert _parse_years("2017,2019,2017") == [2017, 2019]


# ── _word_match ────────────────────────────────────────────────────────────

def test_word_match_hits_on_boundary():
    assert _word_match("emi", "belgien 2 euro emi coincard")


def test_word_match_no_substring():
    # un acronyme court ne doit pas matcher en sous-chaîne
    assert not _word_match("emi", "akademie der wissenschaften")


def test_word_match_empty_needle():
    assert not _word_match("", "anything")


# ── collides ───────────────────────────────────────────────────────────────

def test_collides_none_when_no_overlap():
    # 'studentenrevolte' n'apparait dans aucun vocab sœur → pas de collision
    corpus = ["2 euros esro-2b", "iris", "satellite"]
    assert collides("studentenrevolte", corpus) is None


def test_collides_rejects_alias_in_sister_title():
    # un candidat 'satellite' pour la pièce X alors qu'une sœur a déjà
    # 'satellite' dans son titre i18n → rejeté (taperait sur la sœur)
    corpus = ["2 euros satellite esro-2b"]
    assert collides("satellite", corpus) == "2 euros satellite esro-2b"


def test_collides_rejects_alias_equal_to_sister_alias():
    corpus = ["iris"]
    assert collides("iris", corpus) == "iris"


def test_collides_ignores_substring_only_overlap():
    # 'gulden' ne doit pas collisionner avec 'karlsgulden' (sous-chaîne,
    # pas limite de mot) — même sémantique que le matcher
    corpus = ["2 euro karlsgulden"]
    assert collides("gulden", corpus) is None


# ── intégration : un alias LLM produit un hit du matcher ───────────────────

@pytest.fixture
def conn_with_alias():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE coin_names_i18n (
          eurio_id TEXT NOT NULL, lang TEXT NOT NULL, title TEXT NOT NULL,
          PRIMARY KEY (eurio_id, lang)
        );
        CREATE TABLE coin_aliases (
          eurio_id TEXT NOT NULL, lang TEXT NOT NULL, alias TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'mined',
          confidence TEXT NOT NULL DEFAULT 'high',
          PRIMARY KEY (eurio_id, lang, alias)
        );
        INSERT INTO coin_names_i18n (eurio_id, lang, title) VALUES
          ('be-2018-may-1968', 'de', '2 Euro Ereignisse vom Mai 1968');
        INSERT INTO coin_aliases (eurio_id, lang, alias, source) VALUES
          ('be-2018-may-1968', 'de', 'studentenrevolte', 'llm');
        """
    )
    yield conn
    conn.close()


def test_llm_alias_produces_hit(conn_with_alias):
    # le titre vendeur emploie le vocab de marché, absent de l'i18n
    state = _theme_match_state(
        "Belgien 2 Euro 2018 Studentenrevolte BU", "be-2018-may-1968",
        conn=conn_with_alias,
    )
    assert state == "hit"


def test_llm_alias_word_boundary_no_false_hit(conn_with_alias):
    # un titre sans le terme de marché ne doit pas hit sur l'alias
    state = _theme_match_state(
        "Belgien 2 Euro 2018 ESRO-2B BU", "be-2018-may-1968",
        conn=conn_with_alias,
    )
    assert state == "miss"
