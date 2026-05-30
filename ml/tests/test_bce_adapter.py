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


def test_match_group_single_item_unchanged():
    """Groupe à 1 bloc → comportement identique à _match_entry."""
    idx = _index([_RefCoin(
        eurio_id="de-2010-2eur-state-of-bremen",
        country="DE", year=2010, theme_slug="state-of-bremen",
    )])
    assert _adapter().match_group(idx, [("DE", 2010, "federal-state-of-bremen")]) == [
        "de-2010-2eur-state-of-bremen"
    ]


def test_match_group_one_to_one_no_double_claim():
    """Deux blocs au-dessus du plancher sur le SEUL candidat : un seul l'obtient
    (le plus fort), l'autre reste non-matché — jamais de double-claim."""
    idx = _index([_RefCoin(
        eurio_id="xx-1-2eur-common-words-here", country="XX", year=1,
        theme_slug="common-words-here",
    )])
    res = _adapter().match_group(idx, [
        ("XX", 1, "common-words-here"),   # score 1.0
        ("XX", 1, "common-words-there"),  # ~0.67, au-dessus du plancher aussi
    ])
    assert res[0] == "xx-1-2eur-common-words-here"
    assert res[1] is None  # candidat déjà réclamé → pas de double-claim
    assert res.count("xx-1-2eur-common-words-here") == 1


def test_match_group_optimal_beats_greedy():
    """L'assignation optimale (score total max) bat le greedy : le bloc qui
    score un poil plus haut sur un candidat partagé ne le monopolise pas si un
    autre appariement global est meilleur."""
    idx = _index([
        _RefCoin(eurio_id="xx-1-2eur-alpha", country="XX", year=1, theme_slug="alpha-theme"),
        _RefCoin(eurio_id="xx-1-2eur-beta", country="XX", year=1, theme_slug="beta-theme"),
    ])
    # bloc A: parfait sur alpha ; bloc B: moyen sur alpha, parfait sur beta.
    res = _adapter().match_group(idx, [
        ("XX", 1, "alpha-theme"),
        ("XX", 1, "beta-theme"),
    ])
    assert res == ["xx-1-2eur-alpha", "xx-1-2eur-beta"]


def test_match_group_override_frees_shared_candidate():
    """Un override sur la pièce divergente la rattache à son vrai eurio_id, ce
    qui libère le candidat partagé pour la pièce correcte."""
    idx = _index([
        _RefCoin(eurio_id="es-2014-2eur-park-guell-and-the-works-of-antoni-gaudi",
                 country="ES", year=2014,
                 theme_slug="park-guell-and-the-works-of-antoni-gaudi"),
        _RefCoin(eurio_id="es-2014-2eur-king-accession-to-spanish-throne",
                 country="ES", year=2014,
                 theme_slug="king-accession-to-spanish-throne"),
    ])
    res = _adapter().match_group(idx, [
        ("ES", 2014, "change-of-the-head-of-state"),  # a un override → king
        ("ES", 2014, "unescos-world-cultural-and-natural-heritage-sites-park-guell"),
    ])
    assert res[0] == "es-2014-2eur-king-accession-to-spanish-throne"
    assert res[1] == "es-2014-2eur-park-guell-and-the-works-of-antoni-gaudi"


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
