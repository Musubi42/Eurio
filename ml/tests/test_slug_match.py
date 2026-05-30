"""Tests du matcher de slugs partagé (``sources._base.slug_match``).

Couvre la logique générique indépendamment de toute source : fuzzy floor/gap,
overrides, assignation one-to-one et optimale. Les tests BCE-spécifiques
(``test_bce_adapter``) vérifient en plus le câblage des overrides BCE.
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from sources._base.slug_match import (  # noqa: E402
    RefCoin,
    SlugGroupMatcher,
    max_assignment,
    slug_score,
)


def _index(coins: list[RefCoin]) -> dict[tuple[str, int], list[RefCoin]]:
    idx: dict[tuple[str, int], list[RefCoin]] = {}
    for c in coins:
        idx.setdefault((c.country, c.year), []).append(c)
    return idx


# ── slug_score ──────────────────────────────────────────────────────────────


def test_slug_score_empty_is_zero():
    assert slug_score("", "donatello") == 0.0
    assert slug_score("donatello", "") == 0.0


def test_slug_score_verbose_vs_compact_high():
    # Titre verbeux source vs slug compact référentiel → couverture max.
    s = slug_score("550th-anniversary-of-the-death-of-donatello", "donatello")
    assert s == 1.0


def test_slug_score_unrelated_low():
    assert slug_score("alpha-theme", "totally-different") < 0.25


# ── max_assignment ───────────────────────────────────────────────────────────


def test_max_assignment_injective_picks_global_optimum():
    # bloc0 préfère A (0.9) mais bloc1 ne peut QUE A (0.8) → l'optimal global
    # donne A à bloc1 et B à bloc0 (0.5+0.8=1.3 > 0.9+0=0.9).
    scoremaps = [{"A": 0.9, "B": 0.5}, {"A": 0.8}]
    assert max_assignment(scoremaps) == ["B", "A"]


def test_max_assignment_empty_scoremap_is_none():
    assert max_assignment([{}, {"A": 0.7}]) == [None, "A"]


# ── SlugGroupMatcher : match_entry (sans unicité) ────────────────────────────


def test_match_entry_single_candidate_fuzzy_succeeds():
    idx = _index([RefCoin("de-2010-2eur-bremen", "DE", 2010, "federal-state-of-bremen")])
    assert SlugGroupMatcher().match_entry(idx, "DE", 2010, "bremen") == "de-2010-2eur-bremen"


def test_match_entry_no_candidate_returns_none():
    assert SlugGroupMatcher().match_entry({}, "AT", 2099, "foo") is None


def test_match_entry_too_dissimilar_returns_none():
    idx = _index([RefCoin("fr-2020-2eur-x", "FR", 2020, "completely-other-subject")])
    assert SlugGroupMatcher().match_entry(idx, "FR", 2020, "zzz") is None


def test_match_entry_override_shortcircuits_fuzzy():
    overrides = {("DE", 2020, "kniefall"): "de-2020-2eur-reconciliation"}
    idx = _index([RefCoin("de-2020-2eur-reconciliation", "DE", 2020, "polish-reconciliation")])
    m = SlugGroupMatcher(overrides=overrides)
    assert m.match_entry(idx, "DE", 2020, "kniefall") == "de-2020-2eur-reconciliation"


def test_match_entry_override_skipped_if_eurio_missing():
    # L'override pointe un eurio_id absent des candidats → on retombe sur le fuzzy
    # (qui échoue ici) plutôt que de renvoyer un id fantôme (garde-fou FK).
    overrides = {("DE", 2020, "kniefall"): "de-2020-2eur-ABSENT"}
    idx = _index([RefCoin("de-2020-2eur-other", "DE", 2020, "unrelated-subject")])
    assert SlugGroupMatcher(overrides=overrides).match_entry(idx, "DE", 2020, "kniefall") is None


# ── SlugGroupMatcher : match_group (one-to-one) ──────────────────────────────


def test_match_group_single_item_matches_match_entry():
    idx = _index([RefCoin("de-2010-2eur-bremen", "DE", 2010, "federal-state-of-bremen")])
    assert SlugGroupMatcher().match_group(idx, [("DE", 2010, "bremen")]) == ["de-2010-2eur-bremen"]


def test_match_group_no_double_claim():
    idx = _index([
        RefCoin("xx-1-2eur-alpha", "XX", 1, "alpha-theme"),
        RefCoin("xx-1-2eur-beta", "XX", 1, "beta-theme"),
    ])
    res = SlugGroupMatcher().match_group(idx, [("XX", 1, "alpha-theme"), ("XX", 1, "beta-theme")])
    assert res == ["xx-1-2eur-alpha", "xx-1-2eur-beta"]
    assert len(set(res)) == 2  # aucun id réclamé deux fois


def test_match_group_optimal_beats_greedy():
    # Les deux blocs scorent le plus haut sur "alpha", mais l'assignation
    # optimale globale leur attribue chacun le bon eurio_id.
    idx = _index([
        RefCoin("xx-1-2eur-alpha", "XX", 1, "alpha-theme"),
        RefCoin("xx-1-2eur-beta", "XX", 1, "beta-theme"),
    ])
    res = SlugGroupMatcher().match_group(idx, [("XX", 1, "beta-theme"), ("XX", 1, "alpha-theme")])
    assert res == ["xx-1-2eur-beta", "xx-1-2eur-alpha"]


def test_match_group_override_frees_shared_candidate():
    # bloc0 (override) prend son id ; bloc1 récupère le candidat libéré.
    overrides = {("ES", 2014, "head-of-state"): "es-2014-2eur-king"}
    idx = _index([
        RefCoin("es-2014-2eur-park-guell", "ES", 2014, "park-guell-and-the-works-of-gaudi"),
        RefCoin("es-2014-2eur-king", "ES", 2014, "king-accession-to-spanish-throne"),
    ])
    res = SlugGroupMatcher(overrides=overrides).match_group(idx, [
        ("ES", 2014, "head-of-state"),
        ("ES", 2014, "park-guell"),
    ])
    assert res == ["es-2014-2eur-king", "es-2014-2eur-park-guell"]
