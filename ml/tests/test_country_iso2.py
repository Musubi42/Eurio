"""Tests pour `country_to_iso2()` dans ml/referential/eurio_referential.py.

Lock l'état du dictionnaire `COUNTRY_NAME_TO_ISO2` : toute eurozone + 4 États
tiers + le pseudo-pays `eu` pour joint-issues.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from referential.eurio_referential import country_to_iso2  # noqa: E402


@pytest.mark.parametrize("name,expected", [
    # Eurozone canon EN (echantillon, le dict en a 21)
    ("Germany", "DE"),
    ("France", "FR"),
    ("Italy", "IT"),
    ("Bulgaria", "BG"),  # eurozone 2026-01-01
    # Numista long-form (688 catalog rows observed 2026-05-25)
    ("Germany, Federal Republic of", "DE"),
    # Joint-issue pseudo-country — lowercase aligned with coins.country='eu'
    ("European Union", "eu"),
    # Third-state monetary agreements
    ("Andorra", "AD"),
    ("Monaco", "MC"),
    ("San Marino", "SM"),
    ("Vatican City", "VA"),
    ("Vatican", "VA"),  # short variant also accepted
])
def test_country_to_iso2_known(name, expected):
    assert country_to_iso2(name) == expected


def test_european_union_returns_lowercase_eu():
    """Strict assert : aligned with coins.country='eu' convention (lowercase).
    A regression to 'EU' uppercase would break joint-issue queries."""
    assert country_to_iso2("European Union") == "eu"


@pytest.mark.parametrize("name", [
    "",
    "   ",
    None,
])
def test_country_to_iso2_empty_or_none(name):
    """Empty / None / whitespace-only → None, never crash."""
    assert country_to_iso2(name) is None


def test_country_to_iso2_whitespace_stripped():
    """Leading / trailing whitespace tolerated."""
    assert country_to_iso2("  France  ") == "FR"


def test_country_to_iso2_internal_whitespace_normalized():
    """Multiple internal spaces collapsed to single space."""
    assert country_to_iso2("San   Marino") == "SM"


@pytest.mark.parametrize("name", [
    "Atlantis",
    "Wakanda",
    "United States",  # not eurozone
    "United Kingdom",  # left eurozone (never was, but defensive)
    "Yugoslavia",
])
def test_country_to_iso2_unknown_returns_none(name):
    assert country_to_iso2(name) is None


def test_country_to_iso2_case_sensitive():
    """Function does NOT lowercase input — Numista returns canonical case."""
    # "germany" lowercase is NOT in the dict; tested to lock this behavior.
    # If a use case appears, prefer adding the canonical case to the dict
    # rather than making the function case-insensitive (which would mask
    # data quality issues upstream).
    assert country_to_iso2("germany") is None
    assert country_to_iso2("GERMANY") is None
