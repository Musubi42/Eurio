"""Unit tests — preflight « assez d'images par classe ? » (HANDOFF §7.1).

Couvre les tiers du gate (ok / warn / block), l'agrégation du seed sur les
membres d'une classe design_group, et le cas réf morte (classe absente du
catalogue → block, au lieu d'une absence silencieuse du dataset).

Run: `.venv/bin/python -m pytest ml/tests/test_training_preflight.py -q`
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import ClassRef  # noqa: E402
from training.eval.class_resolver import CoinRef, Resolver  # noqa: E402
from training.foundation import preflight as pf  # noqa: E402
from training.foundation.enrichment import MIN_REAL  # noqa: E402
from training.iteration_augmentations import CoinSources  # noqa: E402


def _sources(*, numista=0, ebay=0, ref=0) -> CoinSources:
    # paths n'a pas à être réel ici : seul total/compteurs comptent pour le gate.
    paths = [Path(f"x{i}") for i in range(numista + ebay + ref)]
    return CoinSources(n_numista=numista, n_ebay=ebay, n_ref=ref, paths=paths)


def _resolver(coins: list[CoinRef]) -> Resolver:
    return Resolver(coins)


# ─── _verdict (tiers purs) ───────────────────────────────────────────────


def test_verdict_tiers():
    m = 4
    # seed 0 → block (réf morte / jamais acquise)
    assert pf._verdict(0, 0, m)[0] == "block"
    # 0 < seed < m → block (doublons rééchantillonnés, pas de signal)
    assert pf._verdict(3, 3, m)[0] == "block"
    assert pf._verdict(1, 0, m)[0] == "block"
    # seed ≥ m mais eBay réels < MIN_REAL → warn (s'appuie sur l'augmentation)
    s, _ = pf._verdict(m, m, m)
    assert s == "warn"
    assert pf._verdict(20, MIN_REAL - 1, m)[0] == "warn"
    # seed ≥ m ET eBay réels ≥ MIN_REAL → ok
    assert pf._verdict(20, MIN_REAL, m) == ("ok", None)
    assert pf._verdict(20, MIN_REAL + 5, m) == ("ok", None)


# ─── preflight_classes ───────────────────────────────────────────────────


def test_block_on_starved_and_dead_ref(monkeypatch):
    coins = [
        CoinRef(eurio_id="ok-coin", numista_id=1, design_group_id=None),
        CoinRef(eurio_id="poor-coin", numista_id=2, design_group_id=None),
    ]
    resolver = _resolver(coins)

    seeds = {
        "ok-coin": _sources(numista=1, ebay=15),   # seed 16, ebay 15 → ok
        "poor-coin": _sources(numista=1, ebay=2),  # seed 3 < m=4 → block
    }
    monkeypatch.setattr(
        pf, "real_training_sources",
        lambda eid, nid, store: seeds.get(eid, _sources()),
    )

    classes = [
        ClassRef("ok-coin", "eurio_id"),
        ClassRef("poor-coin", "eurio_id"),
        ClassRef("ghost-coin", "eurio_id"),  # absent du resolver → réf morte
    ]
    report = pf.preflight_classes(classes, store=None, m_per_class=4, resolver=resolver)

    assert not report.ok
    blocked = {c.class_id for c in report.blocked}
    assert blocked == {"poor-coin", "ghost-coin"}
    ghost = next(c for c in report.classes if c.class_id == "ghost-coin")
    assert ghost.seed == 0 and "catalogue" in ghost.reason
    ok = next(c for c in report.classes if c.class_id == "ok-coin")
    assert ok.status == "ok" and ok.seed == 16


def test_design_group_sums_members(monkeypatch):
    # Deux eurio_ids partageant un design_group → une seule classe ; seed sommé.
    coins = [
        CoinRef(eurio_id="be-a", numista_id=10, design_group_id="grp"),
        CoinRef(eurio_id="be-b", numista_id=11, design_group_id="grp"),
    ]
    resolver = _resolver(coins)
    seeds = {
        "be-a": _sources(numista=1, ebay=6),
        "be-b": _sources(numista=1, ebay=7),
    }
    monkeypatch.setattr(
        pf, "real_training_sources",
        lambda eid, nid, store: seeds[eid],
    )

    report = pf.preflight_classes(
        [ClassRef("grp", "design_group_id")], store=None, m_per_class=4, resolver=resolver
    )
    assert len(report.classes) == 1
    c = report.classes[0]
    assert c.seed == 15 and c.n_ebay == 13 and c.n_numista == 2
    assert c.status == "ok"  # 13 eBay ≥ MIN_REAL


def test_warn_does_not_block(monkeypatch):
    coins = [CoinRef(eurio_id="c", numista_id=1, design_group_id=None)]
    resolver = _resolver(coins)
    monkeypatch.setattr(
        pf, "real_training_sources",
        lambda eid, nid, store: _sources(numista=1, ebay=2, ref=3),  # seed 6 ≥ m, ebay 2 < 10
    )
    report = pf.preflight_classes(
        [ClassRef("c", "eurio_id")], store=None, m_per_class=4, resolver=resolver
    )
    assert report.ok  # warn n'arrête pas le run
    assert report.warned and report.warned[0].status == "warn"


def test_empty_staging_not_ok():
    report = pf.preflight_classes([], store=None, m_per_class=4, resolver=None)
    assert report.classes == []
    assert "AUCUNE" in report.summary()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
