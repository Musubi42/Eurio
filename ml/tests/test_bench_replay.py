"""Tests du replay structuré du bench theme-matcher (studio bench, chunk 1).

`replay_bench` lit le gold gelé + le `eurio.db` local. Les deux sont
des artefacts locaux (le gold est committé, la DB non) → test
d'intégration *skippé* si l'un manque, plutôt que de fabriquer un faux
gold (le gold EST la référence — on veut tester dessus).
"""

from __future__ import annotations

import pytest

from scripts.bench_theme_match import DB_PATH, GOLD_PATH, replay_bench
from store import Store

_REASON = "gold gelé ou eurio.db absent (artefacts locaux)"
pytestmark = pytest.mark.skipif(
    not GOLD_PATH.exists() or not DB_PATH.exists(), reason=_REASON
)


@pytest.fixture(scope="module")
def replay() -> dict:
    return replay_bench(Store(DB_PATH)._connection())  # noqa: SLF001


def test_replay_shape(replay):
    assert replay["listings"], "gold vide"
    assert len(replay["listings"]) == replay["metrics"]["total"]


def test_listing_keys(replay):
    expected = {
        "listing_id", "title", "marketplace", "group_year", "price",
        "currency", "bucket", "note", "verdict", "accept", "matcher",
        "outcome", "agreement",
    }
    for ls in replay["listings"]:
        assert set(ls) == expected, ls.get("listing_id")
        assert set(ls["accept"]) == {"ok", "reason"}
        # matcher est None ssi accept_listing a rejeté le listing.
        assert (ls["matcher"] is None) == (not ls["accept"]["ok"])


def test_metrics_internal_consistency(replay):
    m = replay["metrics"]
    # Les pièces valides se répartissent en faux rejet / auto / review.
    assert m["n_valid"] == (
        m["n_false_discard"] + m["n_auto_correct"]
        + m["n_auto_wrong"] + m["n_kept_review"]
    )
    # Le junk se répartit en rejet correct / false-keep.
    assert m["n_junk"] == m["n_correct_discard"] + m["n_false_keep"]


def test_agreement_flag_tracks_outcome(replay):
    for ls in replay["listings"]:
        bad = "WRONG" in ls["outcome"] or "FALSE" in ls["outcome"]
        assert ls["agreement"] is (not bad), ls["listing_id"]
