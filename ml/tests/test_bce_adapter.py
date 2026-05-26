"""Tests pour BceAdapter._match_entry — focus sur le fuzzy + overrides
manuels (P10, 2026-05-26)."""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from sources.bce.adapter import (  # noqa: E402
    MANUAL_BCE_OVERRIDES,
    BceAdapter,
    _RefCoin,
)


def _adapter() -> BceAdapter:
    return BceAdapter()


def _index(coins: list[_RefCoin]) -> dict[tuple[str, int], list[_RefCoin]]:
    idx: dict[tuple[str, int], list[_RefCoin]] = {}
    for c in coins:
        idx.setdefault((c.country, c.year), []).append(c)
    return idx


def test_match_single_candidate_fuzzy_succeeds():
    """1 seul candidat (country, year) avec slug proche → match."""
    idx = _index([_RefCoin(
        eurio_id="de-2010-2eur-state-of-bremen",
        country="DE", year=2010,
        theme_slug="state-of-bremen",
    )])
    assert (_adapter()._match_entry(idx, "DE", 2010, "federal-state-of-bremen")
            == "de-2010-2eur-state-of-bremen")


def test_match_no_candidate_returns_none():
    """(country, year) absent du référentiel → None."""
    assert _adapter()._match_entry({}, "AT", 2099, "foo") is None


def test_match_too_dissimilar_returns_none():
    """Score < score_floor → pas de match (filet de sécurité fuzzy)."""
    idx = _index([_RefCoin(
        eurio_id="xx-2099-2eur-some-coin",
        country="XX", year=2099,
        theme_slug="some-coin",
    )])
    # Slug BCE arbitraire, aucun token en commun, hors override → fuzzy
    # retourne None (le filet score_floor).
    assert _adapter()._match_entry(
        idx, "XX", 2099, "completely-unrelated-theme-name",
    ) is None


def test_manual_override_kniefall():
    """L'override force le match kniefall → german-polish-reconciliation
    quand l'eurio_id existe dans le référentiel."""
    idx = _index([_RefCoin(
        eurio_id="de-2020-2eur-german-polish-reconciliation",
        country="DE", year=2020,
        theme_slug="german-polish-reconciliation",
    )])
    assert _adapter()._match_entry(
        idx, "DE", 2020,
        "the-50th-anniversary-of-willy-brandts-kniefall-von-warschau",
    ) == "de-2020-2eur-german-polish-reconciliation"


def test_manual_override_plautus():
    """plauto (IT canonique BCE) → plautus (slug Numista cohorte)."""
    idx = _index([_RefCoin(
        eurio_id="it-2016-2eur-2200th-anniversary-of-the-death-of-plautus",
        country="IT", year=2016,
        theme_slug="2200th-anniversary-of-the-death-of-plautus",
    )])
    assert _adapter()._match_entry(
        idx, "IT", 2016,
        "2200th-anniversary-of-the-death-of-tito-maccio-plauto",
    ) == "it-2016-2eur-2200th-anniversary-of-the-death-of-plautus"


def test_manual_override_skipped_if_eurio_missing():
    """Si l'eurio_id cible de l'override n'est plus dans le référentiel
    courant (rename, suppression), on bypass l'override pour éviter une
    FK error downstream — retombe sur le fuzzy classique."""
    # Référentiel courant n'a PAS l'eurio_id targeté par l'override
    # de-2020-...-german-polish-reconciliation, juste un autre slug.
    idx = _index([_RefCoin(
        eurio_id="de-2020-2eur-some-other-renamed-slug",
        country="DE", year=2020,
        theme_slug="some-other-renamed-slug",
    )])
    # L'override aurait pointé sur "...-german-polish-reconciliation"
    # absent du référentiel → bypass. Le fuzzy entre "kniefall" et
    # "some-other-renamed-slug" donne 0, donc retourne None.
    assert _adapter()._match_entry(
        idx, "DE", 2020,
        "the-50th-anniversary-of-willy-brandts-kniefall-von-warschau",
    ) is None


def test_manual_overrides_keys_are_canonical():
    """Sanity : les keys de MANUAL_BCE_OVERRIDES ont le format attendu
    (country UPPERCASE, year int, slug minuscule)."""
    for (country, year, slug), eurio_id in MANUAL_BCE_OVERRIDES.items():
        assert country.isupper(), country
        assert isinstance(year, int)
        assert slug == slug.lower(), slug
        assert eurio_id.startswith(f"{country.lower()}-{year}-"), (
            f"override {country}-{year}-{slug} → {eurio_id} : "
            f"l'eurio_id ne commence pas par le bon prefix country-year"
        )
