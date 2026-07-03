"""dino_class_references : CRUD + doctrine de réécriture (improvement-loop B)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import Store  # noqa: E402
from store.dino_references import (  # noqa: E402
    DinoRefRow,
    clear_reference_override,
    get_class_references,
    get_reference_overrides,
    get_references_for_assets,
    replace_auto_references,
    set_reference_override,
)


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "t.db")


def _seed_assets(conn, *asset_ids: str) -> None:
    """Assets minimaux (le FK dino_class_references.asset_id l'exige)."""
    import uuid
    for aid in asset_ids:
        sid = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref) "
            "VALUES (?, 'ebay', ?)", (sid, f"ref_{sid}"),
        )
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, "
            "storage_path) VALUES (?, ?, 0, ?)", (aid, sid, f"p/{aid}.png"),
        )


def test_replace_auto_preserves_manual_overrides(tmp_path):
    store = _store(tmp_path)
    with store._writing() as conn:
        _seed_assets(conn, "pin1", "ban1", "fps1", "fps2")
        # Un pin + un exclude humains.
        set_reference_override(conn, class_id="grp-a", eurio_id="a1",
                               asset_id="pin1", method="manual_pin")
        set_reference_override(conn, class_id="grp-a", eurio_id="a1",
                               asset_id="ban1", method="manual_exclude")
        # 1er build : canonique + un fps.
        replace_auto_references(conn, "2eur_all", [
            DinoRefRow("grp-a", "a1", None, "canonical", 0, None),
            DinoRefRow("grp-a", "a1", "fps1", "fps", 1, 0.6),
        ])
    with store._writing() as conn:
        rows = get_class_references(conn, "grp-a")
    methods = sorted(r["method"] for r in rows)
    # canonical + fps réécrits, manual_pin + manual_exclude préservés.
    assert methods == ["canonical", "fps", "manual_exclude", "manual_pin"]

    # 2ᵉ build : les auto changent, les manuels restent.
    with store._writing() as conn:
        replace_auto_references(conn, "2eur_all", [
            DinoRefRow("grp-a", "a1", None, "canonical", 0, None),
            DinoRefRow("grp-a", "a1", "fps2", "fps", 1, 0.7),
        ])
        rows = get_class_references(conn, "grp-a")
    fps = [r for r in rows if r["method"] == "fps"]
    assert len(fps) == 1 and fps[0]["asset_id"] == "fps2"  # remplacé
    overrides = {r["asset_id"] for r in rows if r["method"].startswith("manual")}
    assert overrides == {"pin1", "ban1"}  # intacts


def test_get_reference_overrides_groups_by_class(tmp_path):
    store = _store(tmp_path)
    with store._writing() as conn:
        _seed_assets(conn, "p", "q")
        set_reference_override(conn, class_id="grp-a", eurio_id="a1",
                               asset_id="p", method="manual_pin")
        set_reference_override(conn, class_id="grp-b", eurio_id="b1",
                               asset_id="q", method="manual_exclude")
        ov = get_reference_overrides(conn)
    assert set(ov) == {"grp-a", "grp-b"}
    assert ov["grp-a"][0]["method"] == "manual_pin"


def test_clear_override_returns_to_auto(tmp_path):
    store = _store(tmp_path)
    with store._writing() as conn:
        _seed_assets(conn, "x")
        set_reference_override(conn, class_id="grp-a", eurio_id="a1",
                               asset_id="x", method="manual_exclude")
        assert clear_reference_override(conn, asset_id="x") == 1
        assert get_reference_overrides(conn) == {}


def test_get_references_for_assets_maps_badge(tmp_path):
    store = _store(tmp_path)
    with store._writing() as conn:
        _seed_assets(conn, "fps1")
        replace_auto_references(conn, "2eur_all", [
            DinoRefRow("grp-a", "a1", "fps1", "fps", 1, 0.6),
        ])
        m = get_references_for_assets(conn, ["fps1", "nope"])
    assert set(m) == {"fps1"}
    assert m["fps1"]["method"] == "fps"
