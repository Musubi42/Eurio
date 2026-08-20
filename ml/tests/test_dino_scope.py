"""Le périmètre « ce que DINO reconnaît » — `shared/dino_scope`.

Ce qui est verrouillé ici, et pourquoi chaque point a coûté quelque chose :

1. **Une classe se traduit en étiquettes de banque.** La banque indexe une
   courante sous le plus ancien millésime de son ère ; demander la classe par
   son `design_group_id` doit ramener les crops étiquetés par le représentant.
   Sans traduction : zéro ligne, et rien pour le dire.
2. **`rank` descend dans `top_k_json`.** Un top-3 doit rattraper ce que le top-1
   manque — c'est le seul recours d'une classe affamée (BE : 2 candidats à marge
   en top-1, 7 en élargissant).
3. **La marge se lit en `COALESCE(country_spread, spread)`.** Un filtre sur la
   seule colonne country écarte en silence des crops que le verdict évalue.
4. **Un rang inconnu lève.** Le silence donnerait un périmètre plausible et faux.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from shared.bank_classes import bank_class_ids_for_class
from shared.dino_scope import DINO_RANKS, build_dino_scope, suggestions_join_sql
from shared.verdict_scope import (
    SUGGESTIONS_ANCHORS_KIND,
    SUGGESTIONS_ENCODER_VERSION,
)
from store import Store


@pytest.fixture()
def conn(tmp_path):
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    c.execute(
        "INSERT INTO design_groups (id, designation) "
        "VALUES ('it-2euro-standard-t1','IT 2€ standard (1er type)')",
    )
    # Une ère à deux millésimes : c'est 2002 qui porte l'ancre, 2008 non.
    for eid, year, nid in (
        ("it-2002-std", 2002, 1), ("it-2008-std", 2008, 2),
    ):
        c.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, numista_id,"
            " is_commemorative, design_group_id) VALUES (?,?,?,2.0,?,0,?)",
            (eid, "IT", year, nid, "it-2euro-standard-t1"),
        )
    c.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, numista_id,"
        " is_commemorative) VALUES ('fr-2016-commemo','FR',2016,2.0,9,1)",
    )
    return c


def _asset(conn, ref: str, *, top_k, top1, spread=None, country_spread=None):
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, storage_path) "
        f"VALUES ('si-{ref}','ebay','r-{ref}','x.jpg')",
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, "
        f"storage_status) VALUES ('a-{ref}','si-{ref}','c.jpg','present')",
    )
    import json
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
        "anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim, "
        "spread, country_spread) VALUES (?,?,?,?,?,?,?,?,?)",
        (f"a-{ref}", SUGGESTIONS_ENCODER_VERSION, SUGGESTIONS_ANCHORS_KIND, 10,
         json.dumps([{"eurio_id": e, "sim": 0.8} for e in top_k]),
         top1, 0.8, spread, country_spread),
    )
    conn.commit()
    return f"a-{ref}"


def _matching(conn, scope) -> list[str]:
    rows = conn.execute(
        f"SELECT a.id FROM image_assets a {suggestions_join_sql()} "
        f"WHERE {scope.sql} ORDER BY a.id",
        scope.args,
    ).fetchall()
    return [r["id"] for r in rows]


def test_une_classe_se_traduit_en_etiquettes_de_banque(conn):
    assert bank_class_ids_for_class(conn, "it-2euro-standard-t1") == [
        "it-2002-std", "it-2008-std",
    ]
    scope = build_dino_scope(conn, dino_class="it-2euro-standard-t1")
    assert set(scope.class_ids) == {"it-2002-std", "it-2008-std"}


def test_top1_ne_ramene_que_la_classe(conn):
    _asset(conn, "dedans", top_k=["it-2002-std"], top1="it-2002-std")
    _asset(conn, "dehors", top_k=["fr-2016-commemo"], top1="fr-2016-commemo")

    scope = build_dino_scope(conn, dino_class="it-2euro-standard-t1", rank=1)
    assert _matching(conn, scope) == ["a-dedans"]


def test_le_rang_3_rattrape_ce_que_le_top1_manque(conn):
    # La classe est 3ᵉ : invisible en top-1, atteignable en élargissant. C'est
    # le seul recours d'une classe affamée.
    _asset(
        conn, "troisieme",
        top_k=["fr-2016-commemo", "fr-2016-commemo", "it-2008-std"],
        top1="fr-2016-commemo",
    )
    assert _matching(conn, build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", rank=1)) == []
    assert _matching(conn, build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", rank=3)) == ["a-troisieme"]


def test_le_rang_ne_deborde_pas(conn):
    """4ᵉ position : un top-3 ne doit PAS la ramener. Sans borne stricte,
    « top-3 » deviendrait « tout le top_k », et le palier ne voudrait rien dire.
    """
    _asset(
        conn, "quatrieme",
        top_k=["fr-2016-commemo"] * 3 + ["it-2002-std"],
        top1="fr-2016-commemo",
    )
    assert _matching(conn, build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", rank=3)) == []
    assert _matching(conn, build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", rank=5)) == ["a-quatrieme"]


def test_la_marge_se_lit_avec_repli_sur_le_spread_global(conn):
    # country_spread NULL → le verdict retombe sur le spread global. Un filtre
    # sur la seule colonne country écarterait ce crop en silence.
    _asset(conn, "sans-bande", top_k=["it-2002-std"], top1="it-2002-std",
           spread=0.20, country_spread=None)
    _asset(conn, "bande-faible", top_k=["it-2002-std"], top1="it-2002-std",
           spread=0.90, country_spread=0.01)

    scope = build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", min_spread=0.10,
    )
    assert _matching(conn, scope) == ["a-sans-bande"], (
        "le crop sans bande pays doit passer par son spread global, et celui "
        "dont la bande pays est faible doit être écarté malgré un spread "
        "global énorme"
    )


def test_un_rang_inconnu_leve(conn):
    for bad in (0, 2, 4, 10):
        assert bad not in DINO_RANKS
        with pytest.raises(ValueError):
            build_dino_scope(conn, dino_class="it-2euro-standard-t1", rank=bad)


def test_sans_classe_ni_marge_le_perimetre_ne_contraint_rien(conn):
    scope = build_dino_scope(conn, dino_class=None)
    assert scope.is_empty and scope.sql == "" and scope.args == ()


def test_une_classe_inconnue_ne_ramene_rien_sans_lever(conn):
    _asset(conn, "x", top_k=["it-2002-std"], top1="it-2002-std")
    scope = build_dino_scope(conn, dino_class="zz-inexistante")
    assert _matching(conn, scope) == []


# ─── Le filtre pays ────────────────────────────────────────────────────────


def _listed(conn, ref, country, top1):
    """Un crop, avec le pays de son ANNONCE (pas celui de la pièce)."""
    import json as _json
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, listing_country, "
        "storage_path) VALUES (?,?,?,?,'x.jpg')",
        (f"si-{ref}", "ebay", f"r-{ref}", country),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, "
        f"storage_status) VALUES ('a-{ref}','si-{ref}','c.jpg','present')",
    )
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
        "anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim, "
        "spread) VALUES (?,?,?,?,?,?,?,?)",
        (f"a-{ref}", SUGGESTIONS_ENCODER_VERSION, SUGGESTIONS_ANCHORS_KIND, 10,
         _json.dumps([{"eurio_id": top1, "sim": 0.8}]), top1, 0.8, 0.2),
    )
    conn.commit()


def _matching_listed(conn, scope) -> list[str]:
    rows = conn.execute(
        f"SELECT a.id FROM image_assets a "
        f"JOIN source_images si ON si.id = a.source_image_id "
        f"{suggestions_join_sql()} WHERE {scope.sql} ORDER BY a.id",
        scope.args,
    ).fetchall()
    return [r["id"] for r in rows]


def test_le_pays_d_une_classe_se_resout(conn):
    from shared.dino_scope import class_country
    assert class_country(conn, "it-2euro-standard-t1") == "IT"
    assert class_country(conn, "fr-2016-commemo") == "FR"
    # Classe inconnue : `None`, ce qui DÉSACTIVE le filtre chez l'appelant.
    # Renvoyer un pays faux réduirait la file à zéro sans rien dire.
    assert class_country(conn, "zz-inexistante") is None


def test_le_filtre_pays_ecarte_les_annonces_etrangeres(conn):
    _listed(conn, "ital", "IT", "it-2002-std")
    _listed(conn, "alle", "DE", "it-2002-std")

    sans = build_dino_scope(conn, dino_class="it-2euro-standard-t1")
    avec = build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", country_only=True,
    )
    assert set(_matching_listed(conn, sans)) == {"a-ital", "a-alle"}
    assert _matching_listed(conn, avec) == ["a-ital"]
    assert avec.country == "IT" and sans.country is None


def test_une_classe_sans_pays_n_est_pas_reduite_a_zero(conn):
    """Le filtre se DÉSACTIVE plutôt que de vider la file.

    Une classe dont on ne sait pas résoudre le pays doit être servie entière :
    un filtre qui mord sur une valeur inconnue renverrait zéro ligne, ce qui se
    lit « rien à trancher » — parfaitement plausible, et faux.
    """
    _listed(conn, "orph", "DE", "zz-inconnue")
    scope = build_dino_scope(conn, dino_class="zz-inconnue", country_only=True)
    assert scope.country is None
    assert _matching_listed(conn, scope) == ["a-orph"]
