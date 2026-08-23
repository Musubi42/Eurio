"""Suggestions DINO servies en LECTURE PURE par l'image lean (lot 6a).

Le jumeau lourd (`review/review_queue_routes.py`) encode le crop à la demande
quand la prédiction manque — il tire torch, donc il est skippé sur le VPS. Ici
on sert la MÊME réponse depuis la base seule : prédiction absente ⇒ 404.

Ce qui doit être verrouillé, parce que la divergence serait muette :
  - les SEUILS lus par la voie lean et par `training.foundation` sont les mêmes
    (sinon deux badges différents pour le même crop, sans erreur nulle part) ;
  - l'échelle de décision du verdict est la même ;
  - l'ordre des routes (`asset/…` avant `{review_id}`), sans quoi le détail
    avale la suggestion et répond un 404 parfaitement crédible.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from serving.review_queue import repository, service
from shared.verdict_scope import (
    SUGGESTIONS_ANCHORS_KIND,
    SUGGESTIONS_ENCODER_VERSION,
    VERDICT_ANCHORS_KIND,
    VERDICT_ENCODER_VERSION,
)
from store import Store
from test_review_requalify import _seed_listing


def _principal():
    return Principal(
        user_id="t", email="t@test.local", roles=["reviewer"],
        scopes={"review:read"}, auth_method="api_token",
    )


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    # `serving.review_queue.__init__` ré-exporte l'APIRouter sous le nom
    # `router` : importer le MODULE demande le chemin complet.
    from serving.review_queue.router import router as api_router

    db = tmp_path / "t.db"
    conn = Store(db)._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    app = FastAPI()
    app.include_router(api_router)
    app.dependency_overrides[require_principal] = _principal
    return conn, TestClient(app)


def _seed_prediction(conn, asset_id, *, kind, encoder, top_k, **cols):
    conn.execute(
        """
        INSERT INTO image_asset_dino_predictions
          (asset_id, encoder_version, anchors_kind, anchors_count, top_k_json,
           top1_eurio_id, top1_sim, spread, duration_ms,
           target_country, country_anchors_count, top_k_country_json,
           top1_country_eurio_id, top1_country_sim, country_spread)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id, encoder, kind, cols.get("anchors_count", 42),
            json.dumps(top_k),
            cols.get("top1_eurio_id"), cols.get("top1_sim"), cols.get("spread"),
            cols.get("duration_ms", 0),
            cols.get("target_country"), cols.get("country_anchors_count"),
            json.dumps(cols.get("top_k_country", [])),
            cols.get("top1_country_eurio_id"), cols.get("top1_country_sim"),
            cols.get("country_spread"),
        ),
    )
    conn.commit()


def _seed_coin(conn, eurio_id, **cols):
    conn.execute(
        "INSERT OR IGNORE INTO coins (eurio_id, country, country_name, year, "
        "  theme, face_value, is_commemorative) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (eurio_id, cols.get("country", "FR"), cols.get("country_name", "France"),
         cols.get("year", 2015), cols.get("theme", "Paix"),
         cols.get("face_value", 2.0), cols.get("is_commemorative", 1)),
    )
    conn.commit()


# ─── Le contrat ─────────────────────────────────────────────────────────────


def test_prediction_absente_donne_404_sans_rien_calculer(rig):
    conn, client = rig
    _, [aid], _ = _seed_listing(conn, item_id="D0")
    r = client.get(f"/review-queue/asset/{aid}/dino-suggestions")
    assert r.status_code == 404
    assert "backfill" in r.json()["detail"]


def test_top_k_est_hydrate_des_metadonnees(rig):
    conn, client = rig
    _, [aid], _ = _seed_listing(conn, item_id="D1")
    _seed_coin(conn, "fr-2015-2eur-paix", country="FR", year=2015, theme="Paix")
    _seed_prediction(
        conn, aid, kind=SUGGESTIONS_ANCHORS_KIND, encoder=SUGGESTIONS_ENCODER_VERSION,
        top_k=[{"eurio_id": "fr-2015-2eur-paix", "sim": 0.91},
               {"eurio_id": "inconnu-en-base", "sim": 0.42}],
        top1_eurio_id="fr-2015-2eur-paix", top1_sim=0.91, spread=0.49,
    )

    body = client.get(f"/review-queue/asset/{aid}/dino-suggestions").json()
    assert body["asset_id"] == aid
    assert body["anchors_kind"] == SUGGESTIONS_ANCHORS_KIND
    assert body["duration_ms"] == 0, "vient de la base, aucun encodage"

    first, second = body["top_k"]
    assert (first["country_name"], first["year"], first["theme"]) == ("France", 2015, "Paix")
    assert first["obverse_url"], "une vignette canonique doit toujours être proposée"
    assert second["eurio_id"] == "inconnu-en-base"
    assert second["country_name"] is None, "un eurio_id hors référentiel dégrade, ne casse pas"


def test_lookup_par_review_id_equivaut_au_lookup_par_asset(rig):
    conn, client = rig
    _, [aid], [rid] = _seed_listing(conn, item_id="D2")
    _seed_coin(conn, "fr-2015-2eur-paix")
    _seed_prediction(
        conn, aid, kind=SUGGESTIONS_ANCHORS_KIND, encoder=SUGGESTIONS_ENCODER_VERSION,
        top_k=[{"eurio_id": "fr-2015-2eur-paix", "sim": 0.9}], spread=0.3,
    )
    by_asset = client.get(f"/review-queue/asset/{aid}/dino-suggestions").json()
    by_review = client.get(f"/review-queue/{rid}/dino-suggestions").json()
    assert by_asset == by_review


def test_review_inconnue_donne_404(rig):
    _, client = rig
    r = client.get("/review-queue/nexistepas/dino-suggestions")
    assert r.status_code == 404


def test_le_detail_n_avale_pas_la_route_asset(rig):
    """`/review-queue/{review_id}` déclaré trop tôt répondrait un 404 crédible
    en prenant « asset » pour un id de review. L'ordre est le garde-fou."""
    from serving.review_queue.router import router

    paths = [r.path for r in router.routes]
    assert paths.index("/review-queue/asset/{asset_id}/dino-suggestions") < paths.index(
        "/review-queue/{review_id}/dino-suggestions"
    ) < paths.index("/review-queue/{review_id}")


# ─── Le verdict, et les seuils qui le pilotent ──────────────────────────────


def test_verdict_et_abstention_accompagnent_la_reponse(rig):
    conn, client = rig
    _, [aid], _ = _seed_listing(conn, item_id="D3")
    _seed_coin(conn, "fr-2015-2eur-paix")
    # Suggestions (2eur_all/vitl14) : spread net → « confident ».
    _seed_prediction(
        conn, aid, kind=SUGGESTIONS_ANCHORS_KIND, encoder=SUGGESTIONS_ENCODER_VERSION,
        top_k=[{"eurio_id": "fr-2015-2eur-paix", "sim": 0.9}], spread=0.30,
    )
    # Verdict (2eur_commemo/vits14) : top1 == la cible du listing, sim et spread
    # au-dessus des seuils.
    _seed_prediction(
        conn, aid, kind=VERDICT_ANCHORS_KIND, encoder=VERDICT_ENCODER_VERSION,
        top_k=[], top1_country_eurio_id="fr-2015-2eur-paix",
        top1_country_sim=0.80, country_spread=0.20,
    )

    body = client.get(f"/review-queue/asset/{aid}/dino-suggestions").json()
    assert body["abstention_state"] == "confident"
    assert body["verdict_thresholds"] == {
        "top1_country_sim_min": 0.55, "country_spread_min": 0.05}
    v = body["auto_validate_verdict"]
    assert [c["key"] for c in v["criteria"]] == [
        "top1_target", "top1_country_sim", "country_spread"]
    assert [c["state"] for c in v["criteria"]] == ["pass", "pass", "pass"]
    # Sans signal texte convergent, la règle s'arrête à `partial` — pas
    # `auto_candidate`. C'est l'échelle du legacy, à l'identique.
    assert v["level"] == "partial"


def test_abstention_thresholds_est_toujours_servi(rig):
    """Le front l'AFFICHE sans garde quand l'état est « uncertain » :
    `data.abstention_thresholds.spread_uncertain_max.toFixed(2)`. L'omettre ne
    donne pas une valeur manquante mais une exception de rendu — et seulement sur
    les crops incertains, ceux où le panneau sert le plus.

    Trou révélé par la review du 2026-08-23 : la vérification manuelle était
    tombée sur un crop `confident`, qui ne traverse pas cette branche."""
    conn, client = rig
    _, [aid], _ = _seed_listing(conn, item_id="D8")
    _seed_prediction(
        conn, aid, kind=SUGGESTIONS_ANCHORS_KIND, encoder=SUGGESTIONS_ENCODER_VERSION,
        top_k=[], spread=0.005,  # sous 0,02 → « uncertain », la branche à risque
    )
    body = client.get(f"/review-queue/asset/{aid}/dino-suggestions").json()
    assert body["abstention_state"] == "uncertain"
    assert body["abstention_thresholds"] == {
        "spread_uncertain_max": 0.02, "spread_confident_min": 0.05}


def test_le_contrat_lean_couvre_celui_de_la_voie_lourde(rig):
    """Tout champ que la voie lourde renvoie doit exister côté lean : le front
    est le MÊME, il ne sait pas de quelle voie vient la réponse."""
    from review.review_queue_routes import (
        DinoSuggestionsResponse as HeavyResponse,
    )

    from serving.review_queue.models import DinoSuggestionsResponse as LeanResponse

    manquants = set(HeavyResponse.model_fields) - set(LeanResponse.model_fields)
    assert not manquants, f"champs absents de la réponse lean : {sorted(manquants)}"


def test_consensus_absent_rend_null_au_lieu_de_recalculer(rig):
    """La voie lourde recalcule depuis les experts (numpy/torch). Ici on rend
    `null`, valeur que le contrat front prévoit déjà."""
    conn, client = rig
    _, [aid], _ = _seed_listing(conn, item_id="D4")
    _seed_prediction(
        conn, aid, kind=SUGGESTIONS_ANCHORS_KIND, encoder=SUGGESTIONS_ENCODER_VERSION,
        top_k=[], spread=0.01,
    )
    body = client.get(f"/review-queue/asset/{aid}/dino-suggestions").json()
    assert body["consensus_verdict"] is None
    assert body["abstention_state"] == "uncertain", "spread sous 0,02"


def test_consensus_persiste_est_servi(rig):
    conn, client = rig
    _, [aid], _ = _seed_listing(conn, item_id="D5")
    _seed_prediction(
        conn, aid, kind=SUGGESTIONS_ANCHORS_KIND, encoder=SUGGESTIONS_ENCODER_VERSION,
        top_k=[], spread=0.03,
    )
    conn.execute(
        "INSERT INTO consensus_verdicts (image_asset_id, rule_version, outcome, "
        "  lane, confidence, reason, rule) VALUES (?, 1, 'needs_review', 'manual', "
        "  0.4, 'signaux partiels', 'C3')",
        (aid,),
    )
    conn.commit()

    cv = client.get(f"/review-queue/asset/{aid}/dino-suggestions").json()["consensus_verdict"]
    assert cv == {"outcome": "needs_review", "lane": "manual",
                  "reason": "signaux partiels", "rule": "C3", "confidence": 0.4}


# ─── Les miroirs, qui divergeraient en silence ──────────────────────────────


def test_les_seuils_lean_valent_ceux_de_foundation():
    """Deux copies des seuils = deux badges possibles pour le même crop, sans
    la moindre erreur. Ce test est le seul endroit qui l'empêche."""
    from training.foundation.thresholds import (
        DINO_ABSTENTION_THRESHOLDS,
        DINO_VERDICT_THRESHOLDS,
    )

    assert service.DINO_VERDICT_THRESHOLDS == dict(DINO_VERDICT_THRESHOLDS)
    assert service.DINO_ABSTENTION_THRESHOLDS == dict(DINO_ABSTENTION_THRESHOLDS)


@pytest.mark.parametrize(
    ("spread", "attendu"),
    [(None, "unknown"), (0.0, "uncertain"), (0.019, "uncertain"),
     (0.02, "low_margin"), (0.049, "low_margin"), (0.05, "confident"), (0.9, "confident")],
)
def test_abstention_aux_bornes(spread, attendu):
    assert service.abstention_state(spread) == attendu


def test_la_regle_multi_pays_est_partagee_avec_la_voie_lourde():
    """Une seule définition : `shared/listing_titles`. Si la voie lourde s'en
    détachait, la bande pays serait démotée d'un côté seulement."""
    from review.review_queue_routes import _is_multi_country_lot
    from shared.listing_titles import is_multi_country_lot

    assert _is_multi_country_lot is is_multi_country_lot


def test_multi_country_lot_remonte_dans_la_reponse(rig):
    conn, client = rig
    _, [aid], _ = _seed_listing(conn, item_id="D6")
    conn.execute(
        "UPDATE source_images SET listing_title = ? WHERE id = ?",
        ("2 Euro Kursmünze 2011 Diverse Länder nach Wahl", "SI_D6"),
    )
    _seed_prediction(
        conn, aid, kind=SUGGESTIONS_ANCHORS_KIND, encoder=SUGGESTIONS_ENCODER_VERSION,
        top_k=[], spread=0.1,
    )
    body = client.get(f"/review-queue/asset/{aid}/dino-suggestions").json()
    assert body["multi_country_lot"] is True


def test_prediction_missing_est_une_erreur_typee(rig):
    """Le 404 vient d'une exception métier, pas d'un `None` qui traîne."""
    conn, _ = rig
    _, [aid], _ = _seed_listing(conn, item_id="D7")
    with pytest.raises(repository.DinoPredictionMissing):
        service.dino_suggestions(conn, aid, anchors_kind=SUGGESTIONS_ANCHORS_KIND)
