"""Tests for `ml/eval/class_resolver.py`.

Verrouille le contrat du mode `force_eurio_id` introduit phase 1 du
refacto lab/prod (cf. docs/lab-prod-refacto/phase-1-label-space.md) :

- Tous les CoinRef voient `design_group_id = None`
- Tous les ClassDescriptor ont `class_kind == "eurio_id"`
- `class_id == eurio_id` partout (pas de COALESCE résiduel)

Pas de Supabase mocké — on construit un Resolver direct depuis des
CoinRef en mémoire.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.class_resolver import CoinRef, Resolver  # noqa: E402


def _sample_coins() -> list[CoinRef]:
    """Cas représentatif : un coin avec design_group, un sans."""
    return [
        CoinRef(eurio_id="at-2002-2eur-standard", numista_id=64,
                design_group_id="at-2eur-standard-2002"),
        CoinRef(eurio_id="ad-2014-2eur-standard", numista_id=12345,
                design_group_id=None),
    ]


def test_default_mode_uses_design_group_when_present():
    coins = _sample_coins()
    resolver = Resolver(coins)
    at_desc = resolver.for_eurio("at-2002-2eur-standard")
    assert at_desc is not None
    assert at_desc.class_id == "at-2eur-standard-2002"
    assert at_desc.class_kind == "design_group_id"


def test_force_eurio_id_strips_design_group():
    """Reproduit ce que `build_resolver(force_eurio_id=True)` fait avant
    de construire le Resolver : réécrit chaque CoinRef avec
    design_group_id=None."""
    coins = _sample_coins()
    eurio_only = [
        CoinRef(eurio_id=c.eurio_id, numista_id=c.numista_id, design_group_id=None)
        for c in coins
    ]
    resolver = Resolver(eurio_only)

    for descriptor in resolver.classes:
        assert descriptor.class_kind == "eurio_id", (
            f"class {descriptor.class_id} a class_kind={descriptor.class_kind}, "
            "attendu 'eurio_id' en mode force"
        )
        assert descriptor.class_id in {c.eurio_id for c in coins}, (
            f"class_id={descriptor.class_id} n'est pas un eurio_id valide"
        )

    at_desc = resolver.for_eurio("at-2002-2eur-standard")
    assert at_desc is not None
    assert at_desc.class_id == "at-2002-2eur-standard"
    assert at_desc.class_kind == "eurio_id"


def test_force_eurio_id_does_not_collapse_distinct_coins():
    """Deux coins partageant le même design_group doivent rester deux
    classes distinctes en mode force_eurio_id."""
    coins = [
        CoinRef(eurio_id="at-2002-2eur-standard", numista_id=64,
                design_group_id="at-2eur-standard-2002"),
        CoinRef(eurio_id="at-2008-2eur-standard", numista_id=65,
                design_group_id="at-2eur-standard-2002"),
    ]
    eurio_only = [
        CoinRef(eurio_id=c.eurio_id, numista_id=c.numista_id, design_group_id=None)
        for c in coins
    ]
    resolver = Resolver(eurio_only)
    assert len(resolver.classes) == 2
    class_ids = {d.class_id for d in resolver.classes}
    assert class_ids == {"at-2002-2eur-standard", "at-2008-2eur-standard"}
