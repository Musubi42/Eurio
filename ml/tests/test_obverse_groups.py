"""Tests des fonctions pures de dérivation des design_groups par avers."""

from __future__ import annotations

from pathlib import Path

import pytest

from bootstrap.obverse_groups import (
    ObverseKey,
    StandardCoin,
    apply_plan,
    derive_groups,
    parse_obverse_key,
    plan_bootstrap,
)
from state.store import Store

# --- Fixtures : les 5 standards BE 2€ réels (cf. eurio.db 2026-06-07) ---

BE_1999 = StandardCoin(
    "be-1999-2eur-standard-albert-ii-1st-map-1st-type-1st-portrait",
    "BE", 2.0, 1999, "2 Euros - Albert II (1st map, 1st type, 1st portrait)",
)
BE_2007 = StandardCoin(
    "be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait",
    "BE", 2.0, 2007, "2 Euros - Albert II (2nd map, 1st type, 1st portrait)",
)
BE_2008 = StandardCoin(
    "be-2008-2eur-standard-albert-ii-2nd-map-2nd-type-2nd-portrait",
    "BE", 2.0, 2008, "2 Euros - Albert II (2nd map, 2nd type, 2nd portrait)",
)
BE_2009 = StandardCoin(
    "be-2009-2eur-standard-albert-ii-2nd-map-2nd-type-1st-portrait",
    "BE", 2.0, 2009, "2 Euros - Albert II (2nd map, 2nd type, 1st portrait)",
)
BE_2014 = StandardCoin(
    "be-2014-2eur-standard-philippe",
    "BE", 2.0, 2014, "2 Euros - Philippe",
)
ALL_BE = [BE_1999, BE_2007, BE_2008, BE_2009, BE_2014]


# --- parse_obverse_key ---

def test_parse_albert_ii_first_type() -> None:
    assert parse_obverse_key(BE_1999.design_description) == ObverseKey("Albert II", 1)
    # be-2007 a un avers IDENTIQUE à be-1999 (seule la carte/revers change) :
    # même clé malgré « 2nd map ».
    assert parse_obverse_key(BE_2007.design_description) == ObverseKey("Albert II", 1)


def test_parse_albert_ii_second_type() -> None:
    assert parse_obverse_key(BE_2008.design_description) == ObverseKey("Albert II", 2)
    assert parse_obverse_key(BE_2009.design_description) == ObverseKey("Albert II", 2)


def test_parse_monarch_without_type_defaults_to_one() -> None:
    assert parse_obverse_key(BE_2014.design_description) == ObverseKey("Philippe", 1)


def test_parse_ignores_portrait_and_map() -> None:
    # Le portrait diffère (2nd vs 1st) mais ne change pas la clé.
    assert parse_obverse_key(BE_2008.design_description).type_ordinal == 2
    assert parse_obverse_key(BE_2009.design_description).type_ordinal == 2


def test_parse_other_denomination_prefix() -> None:
    assert parse_obverse_key("50 Cents - Juan Carlos I (1st type)") == ObverseKey(
        "Juan Carlos I", 1
    )
    assert parse_obverse_key("1 Euro - Felipe VI") == ObverseKey("Felipe VI", 1)


def test_parse_fallback_to_eurio_id() -> None:
    # design_description absent → fallback sur l'eurio_id.
    assert parse_obverse_key(None, BE_2014.eurio_id) == ObverseKey("Philippe", 1)
    key = parse_obverse_key(None, BE_2008.eurio_id)
    assert key is not None and key.type_ordinal == 2


def test_parse_unparsable_returns_none() -> None:
    assert parse_obverse_key(None, None) is None
    assert parse_obverse_key("", "") is None
    assert parse_obverse_key("2 Euros - ") is None  # monarque vide


# --- derive_groups ---

def test_derive_be_three_groups() -> None:
    result = derive_groups(ALL_BE)
    by_id = {g.group_id: g for g in result.groups}
    assert set(by_id) == {
        "be-2euro-albert-ii-t1",
        "be-2euro-albert-ii-t2",
        "be-2euro-philippe-t1",
    }
    assert not result.unparsable


def test_derive_be_t1_merges_1999_and_2007() -> None:
    result = derive_groups(ALL_BE)
    t1 = next(g for g in result.groups if g.group_id == "be-2euro-albert-ii-t1")
    assert t1.members == (BE_1999.eurio_id, BE_2007.eurio_id)
    assert (t1.year_min, t1.year_max) == (1999, 2007)


def test_derive_be_t2_merges_2008_and_2009() -> None:
    result = derive_groups(ALL_BE)
    t2 = next(g for g in result.groups if g.group_id == "be-2euro-albert-ii-t2")
    assert t2.members == (BE_2008.eurio_id, BE_2009.eurio_id)
    assert (t2.year_min, t2.year_max) == (2008, 2009)


def test_derive_philippe_is_singleton_group() -> None:
    result = derive_groups(ALL_BE)
    phil = next(g for g in result.groups if g.group_id == "be-2euro-philippe-t1")
    assert phil.members == (BE_2014.eurio_id,)
    assert phil.is_singleton
    assert [g.group_id for g in result.singletons] == ["be-2euro-philippe-t1"]


def test_derive_designation_fr_and_en() -> None:
    result = derive_groups([BE_1999, BE_2007])
    t1 = result.groups[0]
    assert t1.designation == "BE 2€ Albert II (1er type)"
    assert t1.designation_i18n["en"] == "BE 2€ Albert II (1st type)"


def test_derive_groups_sorted_by_year() -> None:
    result = derive_groups(ALL_BE)
    assert [g.group_id for g in result.groups] == [
        "be-2euro-albert-ii-t1",
        "be-2euro-albert-ii-t2",
        "be-2euro-philippe-t1",
    ]


def test_derive_unparsable_flagged_not_grouped() -> None:
    bad = StandardCoin("be-9999-2eur-mystere", "BE", 2.0, 9999, None)
    result = derive_groups([BE_2014, bad])
    assert result.unparsable == ["be-9999-2eur-mystere"]
    assert all(bad.eurio_id not in g.members for g in result.groups)


# --- bootstrap (plan + apply) ---

def _seed_coins(store: Store, coins: list[StandardCoin]) -> None:
    conn = store._connection()
    for c in coins:
        conn.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative, "
            "design_description, design_group_id) VALUES (?, ?, ?, ?, 0, ?, ?)",
            (c.eurio_id, c.country, c.year, c.face_value, c.design_description, c.design_group_id),
        )


def _seed_group(store: Store, group_id: str) -> None:
    store._connection().execute(
        "INSERT INTO design_groups (id, designation) VALUES (?, ?)",
        (group_id, group_id),
    )


def _dg(store: Store, eurio_id: str) -> str | None:
    return store._connection().execute(
        "SELECT design_group_id FROM coins WHERE eurio_id = ?", (eurio_id,)
    ).fetchone()[0]


def _make_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def test_apply_attaches_be_groups(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    _seed_coins(store, ALL_BE)
    plan = plan_bootstrap(store._connection(), "BE")
    summary = apply_plan(store._connection(), plan)

    assert summary["coins_attached"] == 5
    assert summary["groups_inserted"] == 3
    assert _dg(store, BE_1999.eurio_id) == "be-2euro-albert-ii-t1"
    assert _dg(store, BE_2007.eurio_id) == "be-2euro-albert-ii-t1"
    assert _dg(store, BE_2008.eurio_id) == "be-2euro-albert-ii-t2"
    assert _dg(store, BE_2014.eurio_id) == "be-2euro-philippe-t1"
    # le groupe Philippe singleton est bien matérialisé en table
    row = store._connection().execute(
        "SELECT designation FROM design_groups WHERE id = 'be-2euro-philippe-t1'"
    ).fetchone()
    assert row is not None


def test_apply_is_idempotent(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    _seed_coins(store, ALL_BE)
    apply_plan(store._connection(), plan_bootstrap(store._connection(), "BE"))
    # 2e run : plan voit tout en already_ok, rien à attacher, pas de doublon de groupe
    plan2 = plan_bootstrap(store._connection(), "BE")
    assert plan2.n_to_attach == 0
    summary2 = apply_plan(store._connection(), plan2)
    assert summary2["coins_attached"] == 0
    assert summary2["already_ok"] == 5
    n_groups = store._connection().execute(
        "SELECT COUNT(*) FROM design_groups WHERE id LIKE 'be-2euro-%'"
    ).fetchone()[0]
    assert n_groups == 3


def test_conflict_aborts_without_writing(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    # be-1999 appartient DÉJÀ à un autre groupe (ex. joint-issue / axe A)
    seeded = list(ALL_BE)
    seeded[0] = StandardCoin(
        BE_1999.eurio_id, "BE", 2.0, 1999, BE_1999.design_description,
        design_group_id="some-other-group",
    )
    _seed_group(store, "some-other-group")
    _seed_coins(store, seeded)
    plan = plan_bootstrap(store._connection(), "BE")
    assert plan.has_conflicts
    assert plan.conflicts[0][0] == BE_1999.eurio_id

    with pytest.raises(RuntimeError, match="écrasement"):
        apply_plan(store._connection(), plan)
    # rien écrit : be-2007 reste NULL, aucun groupe avers inséré
    assert _dg(store, BE_2007.eurio_id) is None
    n_groups = store._connection().execute(
        "SELECT COUNT(*) FROM design_groups WHERE id LIKE 'be-2euro-%'"
    ).fetchone()[0]
    assert n_groups == 0
    # be-1999 conserve son groupe d'origine (non écrasé)
    assert _dg(store, BE_1999.eurio_id) == "some-other-group"


def test_plan_skips_already_attached_coin(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    # be-2014 déjà attaché à SA cible → already_ok, pas un conflit
    seeded = list(ALL_BE)
    seeded[4] = StandardCoin(
        BE_2014.eurio_id, "BE", 2.0, 2014, BE_2014.design_description,
        design_group_id="be-2euro-philippe-t1",
    )
    _seed_group(store, "be-2euro-philippe-t1")
    _seed_coins(store, seeded)
    plan = plan_bootstrap(store._connection(), "BE")
    assert not plan.has_conflicts
    assert BE_2014.eurio_id in plan.already_ok.get("be-2euro-philippe-t1", [])


# --- rapport volume (agrégation par classe) ---

def _seed_si(store: Store, sid: str, target_eurio_id: str) -> None:
    store._connection().execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id) "
        "VALUES (?, 'ebay', ?, ?)",
        (sid, sid, target_eurio_id),
    )


def _seed_ia(store: Store, iid: str, sid: str, crop_index: int, *, eurio_id, eligible: int) -> None:
    store._connection().execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, storage_path, "
        "eurio_id, training_eligible) VALUES (?, ?, ?, 'x', ?, ?)",
        (iid, sid, crop_index, eurio_id, eligible),
    )


def test_report_volume_pools_group_members(tmp_path: Path) -> None:
    from scripts.report_obverse_group_volume import collect

    store = _make_store(tmp_path)
    _seed_coins(store, ALL_BE)
    apply_plan(store._connection(), plan_bootstrap(store._connection(), "BE"))

    # 2 crops attribués (prior be-1999) dont 1 résolu+eligible ; 1 crop attribué
    # (prior be-2007) résolu+eligible → la classe t1 pool les deux membres.
    _seed_si(store, "si1", BE_1999.eurio_id)
    _seed_ia(store, "ia1", "si1", 0, eurio_id=BE_1999.eurio_id, eligible=1)
    _seed_ia(store, "ia2", "si1", 1, eurio_id=None, eligible=0)
    _seed_si(store, "si2", BE_2007.eurio_id)
    _seed_ia(store, "ia3", "si2", 0, eurio_id=BE_2007.eurio_id, eligible=1)

    classes = {c.class_id: c for c in collect(store._connection(), "BE", 2.0)}
    t1 = classes["be-2euro-albert-ii-t1"]
    assert t1.attributed == 3            # 2 (be-1999) + 1 (be-2007)
    assert t1.train_eligible == 2        # be-1999 + be-2007 résolus eligibles
    assert set(t1.members) == {BE_1999.eurio_id, BE_2007.eurio_id}
    # classes sans images → 0 (déficit honnête).
    assert classes["be-2euro-philippe-t1"].attributed == 0
