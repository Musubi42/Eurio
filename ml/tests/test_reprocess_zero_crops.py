"""`scripts.reprocess_zero_crops` — le reprocess des annonces eBay sans crop (O7).

Trois familles de pannes muettes visées :

- une annonce mal sélectionnée (une image a un crop → l'annonce n'est PAS
  perdue ; une cible courante non représentante → la classe est résolue via
  `bank_classes`, pas via l'eurio_id brut) ;
- un câblage qui oublie l'opt-out `retry_zero_crops=True` ou un step aval
  (le script rapporterait 0 sur N sans erreur, ou les portes face/denom ne
  tireraient pas) ;
- un run qui tourne recover OFF (le témoin doit refuser de créer le run) ou
  dont les images ne sont pas liées au run (le push au canonique serait vide).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store  # noqa: E402

import scripts.reprocess_zero_crops as rzc  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "t.db")


@pytest.fixture()
def conn(store):
    return store._connection()  # noqa: SLF001


def _seed_image(conn, sid: str, listing: str, idx: int, *, crop_status: str | None,
                target: str | None = None, country: str | None = "FR",
                with_asset: bool = False, storage_path: str | None = "auto") -> None:
    sp = f"raws/{sid}.jpg" if storage_path == "auto" else storage_path
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, storage_path, fetched_at,"
        " license, crop_status, target_eurio_id, listing_country)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (sid, "ebay", f"{listing}_img{idx}", sp, "2026-08-21 00:00:00",
         "fair_use_research", crop_status, target, country),
    )
    if with_asset:
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, storage_path,"
            " storage_status) VALUES (?,?,?,?,?)",
            (f"asset-{sid}", sid, 0, f"crops/{sid}.jpg", "present"),
        )
    conn.commit()


def _seed_bank(conn, class_id: str, n_fps: int) -> None:
    conn.execute(
        "INSERT INTO dino_class_references (anchors_kind, class_id, eurio_id, method, rank)"
        " VALUES ('2eur_all', ?, ?, 'canonical', 0)",
        (class_id, class_id),
    )
    for i in range(n_fps):
        conn.execute(
            "INSERT INTO dino_class_references (anchors_kind, class_id, eurio_id, asset_id,"
            " method, rank) VALUES ('2eur_all', ?, ?, ?, 'fps', ?)",
            (class_id, class_id, _seed_bank_asset(conn, f"{class_id}-fps{i}"), i + 1),
        )
    conn.commit()


def _seed_bank_asset(conn, key: str) -> str:
    """Un image_asset porteur pour une ligne `fps` (asset_id est une FK)."""
    sid = f"bank-si-{key}"
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, fetched_at, license)"
        " VALUES (?,?,?,?,?)",
        (sid, "numista", f"bank-{key}", "2026-08-21 00:00:00", "fair_use_research"),
    )
    aid = f"bank-asset-{key}"
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, storage_path)"
        " VALUES (?,?,?,?)",
        (aid, sid, 0, f"crops/{aid}.jpg"),
    )
    return aid


# ── Sélection ────────────────────────────────────────────────────────────────


def test_une_annonce_avec_un_crop_present_nest_pas_perdue(conn):
    _seed_image(conn, "a0", "ebay_v1|1|0", 0, crop_status="zero_crops")
    _seed_image(conn, "a1", "ebay_v1|1|0", 1, crop_status="success", with_asset=True)
    _seed_image(conn, "b0", "ebay_v1|2|0", 0, crop_status="zero_crops")
    _seed_image(conn, "b1", "ebay_v1|2|0", 1, crop_status="zero_crops")

    lost = rzc.select_lost_listings(conn, scope="all")
    assert [ll.listing for ll in lost] == ["ebay_v1|2|0"]
    assert lost[0].images == {"ebay_v1|2|0_img0": "b0", "ebay_v1|2|0_img1": "b1"}


def test_une_annonce_sans_raw_nest_pas_rejouable(conn):
    _seed_image(conn, "c0", "ebay_v1|3|0", 0, crop_status="zero_crops", storage_path=None)
    assert rzc.select_lost_listings(conn, scope="all") == []


def test_scope_deficit_garde_les_classes_sous_la_cible_et_jette_les_pleines(conn):
    _seed_bank(conn, "fr-2eur-commemo-a", 3)
    _seed_bank(conn, "fr-2eur-commemo-b", 10)
    _seed_image(conn, "d0", "ebay_v1|4|0", 0, crop_status="zero_crops", target="fr-2eur-commemo-a")
    _seed_image(conn, "e0", "ebay_v1|5|0", 0, crop_status="zero_crops", target="fr-2eur-commemo-b")
    _seed_image(conn, "f0", "ebay_v1|6|0", 0, crop_status="zero_crops", target=None)

    deficit = rzc.select_lost_listings(conn, scope="deficit")
    assert [(ll.listing, ll.class_state, ll.n_fps) for ll in deficit] == [
        ("ebay_v1|4|0", "deficit", 3),
    ]
    everything = rzc.select_lost_listings(conn, scope="all")
    assert {ll.listing: ll.class_state for ll in everything} == {
        "ebay_v1|4|0": "deficit", "ebay_v1|5|0": "full", "ebay_v1|6|0": "unresolvable",
    }


def test_un_membre_non_representant_est_traduit_via_bank_classes(conn):
    """La banque indexe une courante sous le REPRÉSENTANT de son groupe (le plus
    ancien millésime), pas sous son eurio_id. Ici `fr-2007-2eur` vise une classe
    indexée `fr-1999-2eur` avec 2 fps : déficitaire.

    Mutation : remplacer `bank_class_ids(conn, target)` par `[target]` dans
    `_class_state` rend cette annonce « unresolvable » → le `scope='deficit'`
    la perd, et ce test échoue.
    """
    conn.execute("INSERT INTO design_groups (id, designation) VALUES ('fr-2euro-standard-t1', 'FR std')")
    for eid, year in (("fr-1999-2eur", 1999), ("fr-2007-2eur", 2007)):
        conn.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative,"
            " design_group_id) VALUES (?,?,?,?,?,?)",
            (eid, "FR", year, 2.0, 0, "fr-2euro-standard-t1"),
        )
    _seed_bank(conn, "fr-1999-2eur", 2)
    _seed_image(conn, "g0", "ebay_v1|7|0", 0, crop_status="zero_crops", target="fr-2007-2eur")

    lost = rzc.select_lost_listings(conn, scope="deficit")
    assert [(ll.listing, ll.class_state, ll.n_fps) for ll in lost] == [
        ("ebay_v1|7|0", "deficit", 2),
    ]


def test_limit_compte_des_annonces_et_le_seed_rend_lordre_stable(conn):
    for i in range(6):
        _seed_image(conn, f"h{i}a", f"ebay_v1|{10 + i}|0", 0, crop_status="zero_crops")
        _seed_image(conn, f"h{i}b", f"ebay_v1|{10 + i}|0", 1, crop_status="zero_crops")
    a = rzc.select_lost_listings(conn, scope="all", limit=3, seed=7)
    b = rzc.select_lost_listings(conn, scope="all", limit=3, seed=7)
    assert len(a) == 3 and [x.listing for x in a] == [x.listing for x in b]
    assert sum(x.n_images for x in a) == 6
    full = rzc.select_lost_listings(conn, scope="all")
    assert [x.listing for x in full] == sorted(x.listing for x in full)


def test_filtres_listing_ids_et_target(conn):
    _seed_image(conn, "i0", "ebay_v1|20|0", 0, crop_status="zero_crops", target="x")
    _seed_image(conn, "j0", "ebay_v1|21|0", 0, crop_status="zero_crops", target="y")
    by_listing = rzc.select_lost_listings(conn, scope="all", listing_ids=["ebay_v1|21|0"])
    assert [ll.listing for ll in by_listing] == ["ebay_v1|21|0"]
    by_target = rzc.select_lost_listings(conn, scope="all", target_eurio_ids=["x"])
    assert [ll.listing for ll in by_target] == ["ebay_v1|20|0"]


# ── Câblage ──────────────────────────────────────────────────────────────────


class _DetectResult:
    n_crops_added = 0
    n_errors = 0


@pytest.fixture()
def spies(monkeypatch):
    """Remplace les quatre steps par des espions qui notent l'ordre d'appel."""
    calls: list[tuple[str, dict]] = []

    def _mk(name, ret=None):
        def _spy(**kw):
            calls.append((name, kw))
            return ret
        return _spy

    monkeypatch.setattr(rzc, "run_detect_crop", _mk("detect", _DetectResult()))
    monkeypatch.setattr(rzc, "run_resolve", _mk("resolve"))
    monkeypatch.setattr(rzc, "run_auto_validate_dino", _mk("auto_validate"))
    monkeypatch.setattr(rzc, "run_enqueue", _mk("enqueue"))
    return calls


def _seed_lost_listing(conn):
    _seed_image(conn, "k0", "ebay_v1|30|0", 0, crop_status="zero_crops")
    _seed_image(conn, "k1", "ebay_v1|30|0", 1, crop_status="zero_crops")
    return {"ebay_v1|30|0_img0": "k0", "ebay_v1|30|0_img1": "k1"}


def test_les_steps_tournent_dans_lordre_avec_loptout(store, conn, spies, monkeypatch):
    expected = _seed_lost_listing(conn)
    monkeypatch.delenv("EURIO_CENSUS_RECOVER", raising=False)

    rc = rzc.main(["--scope", "all", "--no-push", "--db", str(store.db_path)])
    assert rc == 0

    assert [name for name, _ in spies] == ["detect", "resolve", "auto_validate", "enqueue"]
    detect_kw = spies[0][1]
    assert detect_kw["retry_zero_crops"] is True, "sans l'opt-out le skip B6 vide le reprocess"
    assert detect_kw["source_id"] == "ebay"
    for _, kw in spies:
        assert kw["source_image_ids"] == expected
    runs = conn.execute("SELECT status, filters_json, error_summary FROM source_runs").fetchall()
    assert len(runs) == 1 and runs[0]["status"] == "success"
    assert json.loads(runs[0]["filters_json"])["recover"] == "on"
    summary = json.loads(runs[0]["error_summary"])
    assert summary["n_listings"] == 1 and summary["n_images"] == 2
    assert summary["n_zero_again"] == 2, "les espions n'ont rien croppé : tout reste zero_crops"


def test_le_temoin_recover_off_refuse_de_creer_un_run(store, conn, spies, monkeypatch):
    _seed_lost_listing(conn)
    monkeypatch.setattr(rzc.normalize_snap, "_census_recover_enabled", lambda: False)

    rc = rzc.main(["--scope", "all", "--no-push", "--db", str(store.db_path)])
    assert rc == 2
    assert spies == [], "aucun step ne doit tourner recover OFF"
    assert conn.execute("SELECT COUNT(*) AS n FROM source_runs").fetchone()["n"] == 0


def test_le_log_annonce_recover_on_et_le_perimetre(store, conn, spies, caplog):
    _seed_lost_listing(conn)
    import logging

    with caplog.at_level(logging.INFO, logger="scripts.reprocess_zero_crops"):
        rzc.main(["--scope", "all", "--no-push", "--db", str(store.db_path)])
    header = [r.getMessage() for r in caplog.records if r.getMessage().startswith("recover=ON")]
    assert header and header[0].endswith("scope=all listings=1 images=2"), header


def test_dry_run_ne_cree_pas_de_run(store, conn, spies, capsys):
    _seed_lost_listing(conn)
    assert rzc.main(["--scope", "all", "--dry-run", "--db", str(store.db_path)]) == 0
    assert spies == []
    assert conn.execute("SELECT COUNT(*) AS n FROM source_runs").fetchone()["n"] == 0
    out = capsys.readouterr().out
    assert "1 annonce(s) perdue(s)" in out and "2 image(s)" in out


# ── Push / lien ──────────────────────────────────────────────────────────────


def test_les_images_rejouees_voyagent_avec_le_run(store, conn, spies):
    """`export_run` scope `source_images` par `source_image_runs` : sans le lien,
    le push au canonique emporterait un run vide et la mutation crop_status
    resterait locale, sans un mot."""
    from client.runbatch import export_run

    expected = _seed_lost_listing(conn)
    assert rzc.main(["--scope", "all", "--db", str(store.db_path)]) == 0
    run_id = conn.execute("SELECT id FROM source_runs").fetchone()["id"]

    batch = export_run(conn, run_id)
    assert {r["id"] for r in batch["tables"]["source_images"]} == set(expected.values())
    assert {r["source_image_id"] for r in batch["tables"]["source_image_runs"]} == set(expected.values())
