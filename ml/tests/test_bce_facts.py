"""Tests des normaliseurs de facts BCE (tirage + date d'émission).

Couvre les formats réels observés sur les pages EN + le bruit extractif
(pied de page « Copyright … », coquille « I ssuing date »).
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest  # noqa: E402

from referential.bce_facts import parse_issuing_date, parse_issuing_volume  # noqa: E402


@pytest.mark.parametrize("raw, expected", [
    ("2 million coins", 2_000_000),
    ("1 million coins", 1_000_000),
    ("1.6 million coins", 1_600_000),
    ("1.25 million coins", 1_250_000),
    ("100,000 coins", 100_000),
    ("2 000 000 coins", 2_000_000),       # espaces comme séparateur de milliers
    ("70 500 coins", 70_500),
    ("max 750 000 coins", 750_000),       # préfixe « max » ignoré
    ("181 000 coins I ssuing date: October 2024", 181_000),  # coquille → coupée
    ("30\xa0million\xa0coins", 30_000_000),  # nbsp
])
def test_parse_volume(raw, expected):
    assert parse_issuing_volume(raw)["value"] == expected


def test_parse_volume_keeps_raw_and_none():
    out = parse_issuing_volume("unparseable blob")
    assert out["value"] is None
    assert out["raw_text"] == "unparseable blob"
    assert parse_issuing_volume(None) == {"value": None, "raw_text": None}


@pytest.mark.parametrize("raw, y, m, d", [
    ("September 2017", 2017, 9, None),
    ("December 2007", 2007, 12, None),
    ("21 October 2019", 2019, 10, 21),
    ("1 June 2023", 2023, 6, 1),
    ("Fourth quarter 2022", 2022, None, None),   # trimestre → année seule
    ("Second half of 2025", 2025, None, None),
    ("January 2009 Copyright 2026, European Central Bank", 2009, 1, None),  # footer coupé
    ("May/June 2018", 2018, 6, None),            # prend le 1er « Mois AAAA »
])
def test_parse_date(raw, y, m, d):
    out = parse_issuing_date(raw)
    assert (out["year"], out["month"], out["day"]) == (y, m, d)


def test_parse_date_strips_footer_in_raw():
    out = parse_issuing_date("January 2014 Copyright 2026, European Central Bank")
    assert "Copyright" not in (out["raw_text"] or "")
    assert out["year"] == 2014


def test_parse_date_none():
    assert parse_issuing_date(None)["year"] is None
