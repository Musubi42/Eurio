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


# ─── O4c · le désarmement du filtre pays (D10) ─────────────────────────────
#
# Pourquoi ces tests existent, en un chiffre : mesuré le 2026-08-22 sur la
# réplique (banque a55e6594), le filtre pays — ACTIF par défaut — viderait
# entièrement 147 des 293 classes en besoin, soit 558 crops, et 82 % des
# classes du palier 1. Le « ~5 % de vrais positifs perdus » qui a fondé D9 est
# un agrégat : il vaut 100 % pour un cinquième du catalogue.


def _enqueue(conn, ref: str) -> None:
    """Met le crop dans la file OUVERTE — la population que la sonde regarde."""
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status) "
        f"VALUES ('rq-{ref}', 'a-{ref}', 'open')",
    )
    conn.commit()


def test_le_filtre_pays_se_desarme_quand_il_ne_laisse_rien(conn):
    """La classe IT n'a que des annonces DE : servir zéro serait un mensonge.

    C'est le cas mesuré de `lu-2002-…henri-i-1st-map` : 66 candidats, 0 du pays
    de la classe. Sans ce désarmement la file est vide et se lit « rien à
    trancher » — plausible, et faux.
    """
    _listed(conn, "de1", "DE", "it-2002-std")
    _listed(conn, "de2", "DE", "it-2002-std")
    _enqueue(conn, "de1")
    _enqueue(conn, "de2")

    scope = build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", country_only=True,
    )
    assert scope.country == "IT", "le pays visé reste nommé"
    assert scope.country_disarmed is True
    assert scope.country_active is False
    assert scope.n_hidden_by_country == 0, "un filtre retiré ne masque rien"
    assert _matching_listed(conn, scope) == ["a-de1", "a-de2"]


def test_le_filtre_pays_mord_encore_quand_la_classe_a_de_quoi_servir(conn):
    """Le désarmement ne doit JAMAIS toucher une classe qui a du stock local.

    Cas mesuré : `at-2002-2eur-standard-1st-map`, 90 candidats du pays sur 133.
    Un désarmement qui mordrait ici rendrait au tri les faux positifs que le
    filtre coupe (91 % des faux, mesuré le 2026-08-20).
    """
    _listed(conn, "ital", "IT", "it-2002-std")
    _listed(conn, "alle", "DE", "it-2002-std")
    _enqueue(conn, "ital")
    _enqueue(conn, "alle")

    scope = build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", country_only=True,
    )
    assert scope.country_disarmed is False
    assert scope.country_active is True
    assert scope.n_hidden_by_country == 1, "l'écran doit pouvoir dire « 1 masqué »"
    assert _matching_listed(conn, scope) == ["a-ital"]


def test_un_pool_brut_vide_n_est_pas_un_desarmement(conn):
    """Rien à trancher n'est pas « le filtre m'empêche de trancher ».

    La distinction porte tout O2 §3 : une classe sans aucun candidat relève du
    SCRAPE, pas de la review. Les confondre enverrait l'opérateur vers une file
    vide en lui disant que c'est la faute d'un filtre.
    """
    scope = build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", country_only=True,
    )
    assert scope.country_disarmed is False
    assert scope.n_hidden_by_country == 0
    assert scope.country_active is True


def test_le_desarmement_ignore_les_crops_hors_file_ouverte(conn):
    """La sonde compte EXACTEMENT ce que la file sert : `status = 'open'`.

    Même exigence que `dino_candidates_summary` : deux populations pour un même
    fait, c'est un badge qui annonce 4 au-dessus d'une file qui en sert 3. Ici
    un crop `done` du bon pays ne doit pas empêcher le désarmement.
    """
    _listed(conn, "ital", "IT", "it-2002-std")   # du pays, mais TRANCHÉ
    _listed(conn, "alle", "DE", "it-2002-std")
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status) "
        "VALUES ('rq-ital','a-ital','done')",
    )
    _enqueue(conn, "alle")

    scope = build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", country_only=True,
    )
    assert scope.country_disarmed is True


def test_la_sonde_applique_la_marge_comme_le_perimetre(conn):
    """Sonder sans la marge déciderait sur une population qu'on ne sert pas.

    Une classe dont les seuls candidats du pays sont sous le seuil doit se
    désarmer : sinon la file est vide, et le désarmement — calculé sur un pool
    plus large — n'aurait jamais été déclenché.
    """
    import json as _json
    _listed(conn, "faible", "IT", "it-2002-std")   # spread 0,2 par défaut
    _listed(conn, "alle", "DE", "it-2002-std")
    conn.execute(
        "UPDATE image_asset_dino_predictions SET spread = 0.01 "
        "WHERE asset_id = 'a-faible'",
    )
    _enqueue(conn, "faible")
    _enqueue(conn, "alle")

    scope = build_dino_scope(
        conn, dino_class="it-2euro-standard-t1",
        country_only=True, min_spread=0.05,
    )
    assert scope.country_disarmed is True
    assert _matching_listed(conn, scope) == ["a-alle"]


def test_le_desarmement_vaut_aussi_au_rang_3(conn):
    """Le rang fait partie du périmètre, donc de la sonde.

    Élargir le filet est le recours d'une classe affamée — précisément celles
    que le filtre pays vide. Si la sonde ne regardait que le top-1, une classe
    servie en top-3 se croirait pleine de candidats du pays qu'elle n'a pas.
    """
    import json as _json
    _listed(conn, "top3", "DE", "fr-2016-commemo")
    conn.execute(
        "UPDATE image_asset_dino_predictions SET top_k_json = ? "
        "WHERE asset_id = 'a-top3'",
        (_json.dumps([
            {"eurio_id": "fr-2016-commemo", "sim": 0.9},
            {"eurio_id": "it-2002-std", "sim": 0.8},
        ]),),
    )
    _enqueue(conn, "top3")

    rang1 = build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", country_only=True,
    )
    rang3 = build_dino_scope(
        conn, dino_class="it-2euro-standard-t1", rank=3, country_only=True,
    )
    # Au rang 1 la classe n'a aucun candidat : c'est du scrape, pas un filtre.
    assert rang1.country_disarmed is False
    # Au rang 3 elle en a un, allemand : le filtre se retire.
    assert rang3.country_disarmed is True
    assert _matching_listed(conn, rang3) == ["a-top3"]


def test_le_pays_se_resout_aux_DEUX_grains(conn):
    """Défaut V4 : `class_id` désigne deux choses, et le pays doit suivre.

    Mesuré le 2026-08-23 : la seule lecture `COALESCE(design_group_id, eurio_id)`
    rendait `None` sur 52 des 293 classes en besoin — donc filtre pays
    entièrement désactivé, en silence, sur des pièces dont `coins.country` est
    renseigné. Les appelants du grain BANQUE (`class_need`,
    `dino_class_references`) passent un `eurio_id`, pas un groupe.
    """
    from shared.dino_scope import class_country
    # grain `coins` — un design_group_id (l'ancien chemin, inchangé)
    assert class_country(conn, "it-2euro-standard-t1") == "IT"
    # grain BANQUE — l'eurio_id du représentant, QUI A un design_group_id.
    # C'est exactement le cas qui rendait None.
    assert class_country(conn, "it-2002-std") == "IT"
    assert class_country(conn, "it-2008-std") == "IT"
    # commémorative sans groupe : inchangé
    assert class_country(conn, "fr-2016-commemo") == "FR"
    assert class_country(conn, "zz-inexistante") is None


def test_une_emission_commune_porte_SON_pays_pas_celui_du_groupe(conn):
    """L'ordre de résolution n'est pas cosmétique (D4).

    Un `eu-euro-cash-2012` est frappé par 18 pays. Résoudre par le GROUPE
    rendrait le pays majoritaire — faux 17 fois sur 18, et le filtre pays
    écarterait alors précisément les bonnes annonces.
    """
    from shared.dino_scope import class_country
    conn.execute(
        "INSERT INTO design_groups (id, designation) "
        "VALUES ('eu-cash-2012','10 ans de l''euro')",
    )
    # Trois pays, DE majoritaire — pour que la majorité soit un piège visible.
    for eid, country, nid in (
        ("de-2012-cash", "DE", 51), ("de-2012-cash-b", "DE", 52),
        ("cy-2012-cash", "CY", 53),
    ):
        conn.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, numista_id,"
            " is_commemorative, design_group_id) VALUES (?,?,2012,2.0,?,1,'eu-cash-2012')",
            (eid, country, nid),
        )
    conn.commit()
    assert class_country(conn, "cy-2012-cash") == "CY", "SON pays, pas la majorité"
    assert class_country(conn, "de-2012-cash") == "DE"
    # Le groupe lui-même reste résolu par majorité — c'est l'autre grain.
    assert class_country(conn, "eu-cash-2012") == "DE"
