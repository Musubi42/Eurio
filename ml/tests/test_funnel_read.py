"""C3 — filet de parité de l'extraction `store.funnel` (lecture funnel).

Miroir lecture de ``test_decisions_parity.py`` (C2a, les écritures) : teste
directement le helper SQL-pur ``store.funnel.list_training_crops`` — source
unique partagée par la route full-server (``serving/lab_routes``) ET la route
lean/VPS (``serving/lab_read_routes``).

Couvre : rollup design_group, compteurs état-DB-portable, filtrage
resolution_status/storage_status, `routed` via review_queue, erreurs 404
cohorte inconnue (id et name), et — point critique du blueprint blocker #1 —
l'ABSENCE de tout champ dérivé GPU (r_at_1/confused_with/intruder_*) ou
filesystem (has_numista_ref/n_bce_ref) dans la sortie.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from store import Store
from store.decisions import DecisionError
from store.funnel import list_training_crops


def _design_group(conn, gid, designation="grp") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO design_groups (id, designation) VALUES (?, ?)",
        (gid, designation),
    )


def _coin(conn, eurio_id, numista_id, design_group_id=None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO coins (eurio_id, country, country_name, year, "
        "face_value, is_commemorative, numista_id, design_group_id, "
        "raw_payload_json) VALUES (?, 'XX', 'XX', 2016, 2.0, 1, ?, ?, '{}')",
        (eurio_id, numista_id, design_group_id),
    )


def _crop(conn, eurio_id, *, face="obverse", eligible=True, status="manual",
          quality=0.5, denom="2eur", storage_status="present", routed=False,
          source="ebay") -> str:
    sid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
        "listing_title) VALUES (?, ?, ?, ?, 'titre')",
        (sid, source, f"{source}_{sid}", eurio_id),
    )
    aid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, eurio_id, "
        "resolution_status, face, denom, quality_score, training_eligible, "
        "storage_path, storage_status) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, sid, eurio_id, status, face, denom, quality,
         1 if eligible else 0, f"{source}/{sid}/{aid}.png", storage_status),
    )
    if routed:
        conn.execute(
            "INSERT INTO review_queue (id, image_asset_id, status, priority, "
            "enqueued_at, kind, lane, lane_source) "
            "VALUES (?, ?, 'open', 100, '2026-01-01T00:00:00Z', 'single', "
            "'manual', 'human')",
            (f"rq_{aid}", aid),
        )
    return aid


def _cohort(conn, cohort_id, name, eurio_ids) -> None:
    import json
    conn.execute(
        "INSERT INTO experiment_cohorts (id, name, eurio_ids_json, status) "
        "VALUES (?, ?, ?, 'frozen')",
        (cohort_id, name, json.dumps(eurio_ids)),
    )


@pytest.fixture()
def conn(tmp_path):
    return Store(tmp_path / "t.db")._connection()  # noqa: SLF001


# ─── Rollup + compteurs état-DB-portable ────────────────────────────────────


def test_list_training_crops_rolls_up_design_group(conn):
    _design_group(conn, "grp-portrait", "Portrait")
    _coin(conn, "xx-2016-a", 900101, "grp-portrait")
    _coin(conn, "xx-2016-b", 900102, "grp-portrait")
    a_obv = _crop(conn, "xx-2016-a", face="obverse", eligible=True, quality=0.9)
    _crop(conn, "xx-2016-a", face="obverse", eligible=True, quality=0.8)
    _crop(conn, "xx-2016-a", face="unknown", eligible=True, quality=0.5)
    _crop(conn, "xx-2016-a", face="reverse", eligible=False, status="rejected",
          quality=0.2)
    _crop(conn, "xx-2016-b", face="obverse", eligible=True, quality=0.7)
    _cohort(conn, "cg", "cohort-grp", ["xx-2016-a", "xx-2016-b"])

    result = list_training_crops(conn, "cg")

    assert result["cohort_id"] == "cg"
    assert result["cohort_name"] == "cohort-grp"
    assert len(result["classes"]) == 1  # A+B collapsed into grp-portrait
    cls = result["classes"][0]
    assert cls["class_id"] == "grp-portrait"
    assert cls["class_kind"] == "design_group_id"
    assert set(cls["member_eurio_ids"]) == {"xx-2016-a", "xx-2016-b"}
    assert cls["n_eligible"] == 4  # 3 from A + 1 from B
    assert cls["n_unknown_face"] == 1
    assert cls["n_rejected"] == 1
    assert cls["n_obverse"] == 3
    assert len(cls["crops"]) == 5
    assert any(c["asset_id"] == a_obv for c in cls["crops"])


def test_list_training_crops_no_design_group_falls_back_to_eurio_id(conn):
    _coin(conn, "xx-2016-solo", 910000, None)
    _crop(conn, "xx-2016-solo", face="obverse", eligible=True)
    _cohort(conn, "cs", "cohort-solo", ["xx-2016-solo"])

    result = list_training_crops(conn, "cs")
    cls = result["classes"][0]
    assert cls["class_id"] == "xx-2016-solo"
    assert cls["class_kind"] == "eurio_id"


def test_list_training_crops_underfed_flag(conn):
    _coin(conn, "xx-2016-poor", 920000, None)
    for _ in range(3):
        _crop(conn, "xx-2016-poor", face="obverse", eligible=True)
    _cohort(conn, "cp", "cohort-poor", ["xx-2016-poor"])

    cls = list_training_crops(conn, "cp")["classes"][0]
    assert cls["n_eligible"] == 3
    assert cls["underfed"] is True  # < MIN_REAL (10)


def test_list_training_crops_routed_flag(conn):
    _coin(conn, "xx-2016-r", 930000, None)
    routed = _crop(conn, "xx-2016-r", face="obverse", eligible=False,
                    status="needs_review", routed=True)
    unrouted = _crop(conn, "xx-2016-r", face="obverse", eligible=False,
                      status="needs_review", routed=False)
    _cohort(conn, "cr", "cohort-routed", ["xx-2016-r"])

    cls = list_training_crops(conn, "cr")["classes"][0]
    by_id = {c["asset_id"]: c for c in cls["crops"]}
    assert by_id[routed]["routed"] is True
    assert by_id[unrouted]["routed"] is False
    assert cls["n_review_unrouted"] == 1  # only the unrouted one counts


def test_list_training_crops_filters_out_of_scope_status(conn):
    """`resolution_status` hors TRIAGE_STATUSES (ex. 'confirmed') n'apparaît pas."""
    _coin(conn, "xx-2016-f", 940000, None)
    kept = _crop(conn, "xx-2016-f", face="obverse", eligible=True, status="manual")
    _crop(conn, "xx-2016-f", face="obverse", eligible=True, status="pending_match")
    _cohort(conn, "cf", "cohort-filter", ["xx-2016-f"])

    cls = list_training_crops(conn, "cf")["classes"][0]
    ids = {c["asset_id"] for c in cls["crops"]}
    assert ids == {kept}


def test_list_training_crops_filters_missing_storage(conn):
    """`storage_status != 'present'` (asset local-only jamais poussé MinIO,
    ou supprimé) n'apparaît pas dans la liste VPS."""
    _coin(conn, "xx-2016-m", 950000, None)
    present = _crop(conn, "xx-2016-m", face="obverse", eligible=True,
                     storage_status="present")
    _crop(conn, "xx-2016-m", face="obverse", eligible=True,
          storage_status="missing_in_storage")
    _cohort(conn, "cm", "cohort-missing", ["xx-2016-m"])

    cls = list_training_crops(conn, "cm")["classes"][0]
    ids = {c["asset_id"] for c in cls["crops"]}
    assert ids == {present}


def test_list_training_crops_file_url_shape(conn):
    _coin(conn, "xx-2016-u", 960000, None)
    aid = _crop(conn, "xx-2016-u", face="obverse", eligible=True, source="ebay")
    _cohort(conn, "cu", "cohort-url", ["xx-2016-u"])

    crop = list_training_crops(conn, "cu")["classes"][0]["crops"][0]
    assert crop["asset_id"] == aid
    assert crop["file_url"] == f"/sources/ebay/assets/{aid}/file"


# ─── Cohorte : résolution id/name + 404 ─────────────────────────────────────


def test_list_training_crops_resolves_by_name(conn):
    _coin(conn, "xx-2016-n", 970000, None)
    _crop(conn, "xx-2016-n", face="obverse", eligible=True)
    _cohort(conn, "cn-id", "cohort-by-name", ["xx-2016-n"])

    result = list_training_crops(conn, "cohort-by-name")
    assert result["cohort_id"] == "cn-id"


def test_list_training_crops_404_unknown_cohort(conn):
    with pytest.raises(DecisionError) as exc:
        list_training_crops(conn, "nope")
    assert exc.value.status_code == 404


def test_list_training_crops_empty_class_for_unresolved_eurio_id(conn):
    """Un eurio_id de cohorte absent du catalogue `coins` (slug drift) est
    juste ignoré (unresolved) — pas d'erreur, pas de classe vide fantôme."""
    _cohort(conn, "cz", "cohort-unresolved", ["ghost-coin"])
    result = list_training_crops(conn, "cz")
    assert result["classes"] == []


# ─── Blocker #1 : jamais de champ dérivé GPU/FS dans l'état-DB-portable ─────


def test_list_training_crops_never_leaks_derived_fields(conn):
    """L'état-DB-portable ne doit JAMAIS contenir has_numista_ref/n_bce_ref
    (dérivé filesystem) ni r_at_1/confused_with/intruder_* (dérivé GPU) — ces
    champs vivent exclusivement dans l'overlay LOCAL (blueprint blocker #1)."""
    _design_group(conn, "grp-x", "X")
    _coin(conn, "xx-2016-x", 980000, "grp-x")
    _crop(conn, "xx-2016-x", face="obverse", eligible=True)
    _cohort(conn, "cx", "cohort-leak", ["xx-2016-x"])

    result = list_training_crops(conn, "cx")
    forbidden_top = {"r_at_1", "confused_with", "intruder_suspect", "scan"}
    assert not (forbidden_top & result.keys())

    cls = result["classes"][0]
    forbidden_class = {
        "has_numista_ref", "n_bce_ref", "r_at_1", "r_at_1_prev", "r_at_1_delta",
        "confused_with", "n_real_last_bake", "n_real_prev_bake",
    }
    assert not (forbidden_class & cls.keys())

    crop = cls["crops"][0]
    forbidden_crop = {
        "intruder_suspect", "intruder_reason", "intruder_top1_class",
        "intruder_top1_eurio_id", "intruder_margin",
    }
    assert not (forbidden_crop & crop.keys())
