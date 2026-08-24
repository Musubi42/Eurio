"""L'écart DINO servi à l'accueil, et le job qui le referme.

Trois choses sont verrouillées ici, et chacune casserait SANS ERREUR :

1. **L'écart se compare en `datetime()`, jamais en chaînes.** Trois formats
   d'horodatage cohabitent dans la base ; une comparaison de chaînes classe
   toute prédiction comme antérieure à tout build du même jour. Le piège a déjà
   coûté 12 454 faux « périmés » en août 2026 (`store/encoder_bench.py`).
2. **Une mesure impossible ne se lit pas « tout va bien ».** Table absente ⇒
   409, pas un écart de zéro.
3. **Le geste est lourd, le chiffre ne l'est pas.** La route de lecture doit
   vivre sur les DEUX apps, celle qui lance le rebuild sur la workstation
   seulement — sinon le VPS expose un bouton qui ne peut pas marcher, ou
   l'accueil perd son chiffre dès que le Mac est éteint.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from store import Store
from store.dino_drift import DriftNotMeasurable, dino_drift

KIND, ENCODER = "2eur_all", "dinov2-vitl14"


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    c.row_factory = sqlite3.Row
    return c


def _build(c, built_at: str, build_id: str = "b1") -> None:
    c.execute(
        "INSERT INTO dino_anchor_builds (build_id, anchors_kind, encoder_version, "
        " built_at, n_classes, n_rows, n_canonical, n_exemplars, n_no_canonical) "
        "VALUES (?,?,?,?,10,20,10,10,0)",
        (build_id, KIND, ENCODER, built_at))
    c.commit()


def _asset(c, aid: str, *, eurio_id: str | None = None, eligible: int = 0) -> None:
    c.execute("INSERT OR IGNORE INTO source_images (id, source, source_ref, "
              " storage_path) VALUES ('SI','ebay','r1','raw.jpg')")
    c.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, storage_path, "
        " storage_status, eurio_id, training_eligible, resolution_status) "
        "VALUES (?, 'SI', 0, ?, 'present', ?, ?, 'needs_review')",
        (aid, f"{aid}.png", eurio_id, eligible))
    c.commit()


def _prediction(c, aid: str, computed_at: str) -> None:
    c.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
        " anchors_kind, anchors_count, top_k_json, computed_at) "
        "VALUES (?,?,?,1,'[]',?)",
        (aid, ENCODER, KIND, computed_at))
    c.commit()


def test_une_prediction_du_meme_jour_n_est_pas_declaree_perimee(conn):
    """Le piège des trois formats d'horodatage, verrouillé.

    Le build est écrit en ISO avec un `T` (`2026-08-22T18:06:22+00:00`), la
    prédiction avec un espace (`2026-08-22 18:14:50`) — et elle lui est
    POSTÉRIEURE de huit minutes. Comparées comme des chaînes, `' '` (0x20) passe
    avant `'T'` (0x54) : la prédiction paraît antérieure, et l'écran réclame un
    backfill de 20 minutes qui ne sert à rien.
    """
    _build(conn, "2026-08-22T18:06:22+00:00")
    _asset(conn, "A1")
    _prediction(conn, "A1", "2026-08-22 18:14:50")

    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_predictions_stale == 0
    assert d.n_assets_without_prediction == 0


def test_une_prediction_anterieure_au_build_est_bien_perimee(conn):
    """Le contrôle inverse — sans lui, le test précédent passerait aussi avec
    un compteur câblé à zéro."""
    _build(conn, "2026-08-22T18:06:22+00:00")
    _asset(conn, "A1")
    _prediction(conn, "A1", "2026-08-21 09:00:00")

    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_predictions_stale == 1
    assert d.is_stale


def test_un_crop_sans_prediction_compte_dans_l_ecart(conn):
    _build(conn, "2026-08-22T18:06:22+00:00")
    _asset(conn, "A1")
    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_assets_without_prediction == 1
    assert d.is_stale


def test_une_banque_jamais_batie_est_perimee_pas_a_jour(conn):
    """Zéro écart et « jamais bâtie » ne doivent pas avoir la même tête.

    C'est l'état où un écart nul serait le plus trompeur : rien à rattraper
    parce que rien n'existe.
    """
    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.built_at is None
    assert d.is_stale, "aucune banque n'est le PIRE état, pas un état neutre"


def test_une_table_absente_leve_au_lieu_de_rendre_zero(tmp_path):
    c = sqlite3.connect(tmp_path / "vide.db")
    c.row_factory = sqlite3.Row
    with pytest.raises(DriftNotMeasurable):
        dino_drift(c, anchors_kind=KIND, encoder_version=ENCODER)


def test_le_chiffre_vit_sur_les_deux_apps_le_bouton_sur_une_seule():
    """La lecture partout, le geste sur la machine de calcul.

    Monter le rebuild sur le lean donnerait au VPS un bouton qui ne peut pas
    marcher (ni torch ni banque) ; ne pas monter l'écart sur le lean ferait
    disparaître le chiffre dès que le Mac est éteint — or savoir ce qui manque
    n'a pas à dépendre d'une machine allumée.
    """
    lean = (ML_DIR / "serving/server_serve.py").read_text()
    full = (ML_DIR / "serving/server.py").read_text()

    assert "dino_drift_router" in lean and "dino_drift_router" in full
    assert "dino_rebuild_router" in full
    assert "dino_rebuild_router" not in lean, (
        "le VPS n'a ni torch ni banque : ce bouton y serait un mensonge")


def test_un_job_orphelin_ne_bloque_pas_les_suivants(conn):
    """Un `running` dont le processus est mort doit être fauché.

    Sans ce filet, la garde 409 refuse TOUT rebuild ultérieur, définitivement,
    et l'écran affiche « en cours » sur un processus qui n'existe plus. Cette
    panne-là ressemble à de la patience — c'est ce qui la rend coûteuse.
    """
    from store.dino_rebuild_jobs import (
        latest_rebuild, reap_orphan_rebuilds, rebuild_set_pid, rebuild_start,
    )

    job_id = rebuild_start(conn, anchors_kind=KIND, encoder_version=ENCODER)
    rebuild_set_pid(conn, job_id, 2_147_483_600)  # PID qui n'existe pas
    assert reap_orphan_rebuilds(conn) == 1

    row = latest_rebuild(conn)
    assert row["status"] == "failed" and row["error"]
    assert latest_rebuild(conn, status="running") is None


def test_la_route_d_ecart_repond_par_HTTP(conn, tmp_path):
    """Le câblage, pas seulement le calcul : dépendances, modèle, 409.

    Le test de montage ci-dessus ne dit que « le chemin existe ». Une dépendance
    mal typée ou un `response_model` incompatible le passe et rend 500 en
    production — sur une carte d'accueil que personne ne surveille. Le même
    trou, sur la route de recadrage, cachait un 500 depuis toujours (garde
    `if asset_id is None` sur une fonction qui lève au lieu de rendre None).
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from serving.auth_principal import Principal, require_principal
    from serving.deps import db_connection
    from serving import dino_drift_routes

    _build(conn, "2026-08-22T18:06:22+00:00")
    _asset(conn, "A1")
    _prediction(conn, "A1", "2026-08-22 18:14:50")

    app = FastAPI()
    app.include_router(dino_drift_routes.router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="t", email="t@test.local", roles=["admin"],
        scopes={"lab:read"}, auth_method="api_token",
    )
    app.dependency_overrides[db_connection] = lambda: conn
    client = TestClient(app)

    r = client.get("/dino/drift")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["anchors_kind"] == KIND
    assert body["n_predictions_stale"] == 0
    assert body["build_id"] == "b1"
    assert body["is_stale"] is False

    # Une banque qui n'existe pas ne lève pas : elle rend l'aveu qu'elle n'a
    # jamais été bâtie. C'est la vérité, et c'est actionnable.
    r = client.get("/dino/drift?anchors_kind=nexistepas&encoder_version=x")
    assert r.status_code == 200, r.text
    assert r.json()["built_at"] is None and r.json()["is_stale"] is True


def test_un_job_qui_demarre_n_est_pas_fauche_avant_d_avoir_son_pid(conn):
    """La course entre l'INSERT et l'écriture du PID.

    🔴 Trouvée en revue le 2026-08-24. `rebuild_start` insère la ligne, puis
    `Popen` tourne, puis `rebuild_set_pid` écrit le PID. `GET .../status`
    faucheait tout job à `pid IS NULL` — donc, si un poll tombait dans cette
    fenêtre : l'écran annonçait un échec sur un job bien vivant, ET la garde 409
    ne voyait plus de job en cours, si bien qu'un second clic lançait un
    DEUXIÈME rebuild de vingt minutes sur la même banque.
    """
    from store.dino_rebuild_jobs import (
        latest_rebuild, reap_orphan_rebuilds, rebuild_start,
    )

    job_id = rebuild_start(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert reap_orphan_rebuilds(conn) == 0, "un job qui démarre n'est pas orphelin"

    row = latest_rebuild(conn, status="running")
    assert row is not None and row["id"] == job_id, (
        "la garde 409 doit encore voir ce job — sinon un second clic double le travail")


def test_le_geste_lourd_n_exige_pas_de_principal(conn):
    """Les routes `:8042` sont appelées en `fetch` NU par le front.

    🔴 Corrigé en revue le 2026-08-24 : elles portaient
    `require_scope("review:arbitrate")`. Or cette API-ci n'a pas de session, et
    le PAT que détient le front vaut pour le CANONIQUE. Le bouton rendait donc
    401 à chaque clic et le statut restait nul — un bouton mort. Ce qui protège
    est ailleurs : l'API n'écoute que la machine de l'opérateur, et le bouton
    n'est dessiné que pour un arbitre (`showHeavyGesture`).
    """
    from serving.auth_principal import Principal
    from serving import dino_rebuild_routes as m

    for route in m.router.routes:
        annotations = getattr(route.endpoint, "__annotations__", {})
        principals = [n for n, t in annotations.items() if t is Principal]
        assert not principals, (
            f"{route.path} exige {principals} — le front appelle :8042 en "
            "`fetch` nu, la route serait inatteignable")


def test_les_classes_gagnantes_se_comptent_a_la_maille_classe(conn):
    """La banque indexe une COURANTE sous le représentant de son groupe.

    🔴 Corrigé en revue le 2026-08-24. Comparer `image_assets.eurio_id` à
    `class_id` classait toute courante non-représentante comme « gagnerait une
    photo », **à jamais** : aucun rebuild ne pouvait faire baisser le compteur,
    puisque rien ne l'y ferait entrer sous ce nom-là. Mesuré sur la réplique le
    jour même : 25 classes annoncées, 16 réelles.
    """
    _build(conn, "2026-08-22T18:06:22+00:00")
    conn.execute(
        "INSERT OR IGNORE INTO design_groups (id, designation) "
        "VALUES ('fr-2euro-standard-t1', 'France 2 € courante, 1er type')")
    # Un groupe de dessin : le représentant est le millésime le plus ancien.
    for eid, year in (("fr-1999-2eur-standard", 1999), ("fr-2007-2eur-standard", 2007)):
        conn.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, "
            " is_commemorative, design_group_id) "
            "VALUES (?, 'FR', ?, 2.0, 0, 'fr-2euro-standard-t1')", (eid, year))
    # La banque ne connaît QUE le représentant — c'est le cas nominal.
    conn.execute(
        "INSERT INTO dino_class_references (anchors_kind, class_id, eurio_id, "
        " method, encoder_version) VALUES (?, 'fr-1999-2eur-standard', "
        " 'fr-1999-2eur-standard', 'fps', ?)", (KIND, ENCODER))
    # Un crop validé sur le MEMBRE, pas sur le représentant.
    _asset(conn, "A1", eurio_id="fr-2007-2eur-standard", eligible=1)
    conn.commit()

    d = dino_drift(conn, anchors_kind=KIND, encoder_version=ENCODER)
    assert d.n_classes_would_gain_anchor == 0, (
        "sa classe A un exemplaire — sous le nom du représentant")
