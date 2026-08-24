"""Le recadrage servi par le canonique (lot 6b) — routes lean, contrat, DINO.

`review-collaborative-v2` : 18,4 % des crops sont recadrés à la main. Tant que
ce geste vivait sur l'API ML locale, un ami invité n'en faisait que la moitié.

Ce qui est verrouillé ici, et pourquoi chacun casserait en SILENCE :

1. **Les routes sont sur l'app LEAN** — celle du VPS. `serving/server.py` ≠
   `serving/server_serve.py` : tester sur `:8042` n'exerce pas le code de
   production (piège n°2 du chantier). Le contrat vient d'un module léger, et
   c'est justement ce qui rend l'enregistrement possible : tant que les modèles
   vivaient dans `review/review_queue_routes`, les importer traînait tout le
   router legacy et le VPS n'enregistrait rien.

2. **Les URLs sont ABSOLUES.** Une URL relative `/sources/…/file` fait répondre
   l'API 200 avec un éditeur qui n'affiche que deux carrés gris — panne muette
   déjà payée au lot 1.

3. **Le format est celui de la PROD.** `_crop_mask_resize_float`, pas un crop
   maison : ces pixels nourrissent l'entraînement (D5).

4. **DINO est marqué « à réencoder » — sans disparaître de l'écran.** La
   prédiction a été calculée sur l'ANCIEN cadrage, donc elle est suspecte ; mais
   le geste réel du reviewer est « je recadre au micro, PUIS je choisis la
   pièce », et la supprimer lui retirait son aide juste au moment où elle sert.
   On date la péremption (migration 0013) : servie et annoncée comme telle,
   réencodée en lot. La première version supprimait — corrigée après la première
   vraie session de review.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

import pytest

from store import Store
from test_review_requalify import _seed_listing

_TARGET = "fr-2015-2eur-paix"  # la cible que `_seed_listing` pose sur le listing


# ─── 1. Les routes existent sur l'app lean, et le contrat est léger ─────────


def test_le_contrat_du_recadrage_n_importe_rien_de_lourd():
    """`crop_edit_api` doit rester importable sans le router legacy.

    C'est LA condition qui a débloqué le lot 6b : les modèles vivaient dans
    `review/review_queue_routes`, donc les importer traînait `sources.ebay`,
    `review.validation` et leur suite. Si quelqu'un rebranche le contrat sur le
    legacy, le VPS cessera d'enregistrer ces routes — sans erreur, juste des
    boutons qui répondent 404.
    """
    source = (ML_DIR / "serving/crop_edit_api.py").read_text()
    for interdit in ("review.review_queue_routes", "import torch", "ultralytics"):
        assert interdit not in source, f"crop_edit_api ne doit pas importer {interdit}"


def test_les_routes_de_recadrage_sont_montees_sur_le_lean():
    """`serving/server.py` ≠ `serving/server_serve.py` — c'est le second qui vole."""
    from serving.review_queue import crop_routes

    assert crop_routes.CROP_EDIT_AVAILABLE, "cv2 est présent ici : les routes doivent exister"
    paths = {r.path for r in crop_routes.router.routes}
    assert "/review-queue/{review_id}/crop-edit-context" in paths
    assert "/review-queue/{review_id}/manual-crop" in paths

    serve = (ML_DIR / "serving/server_serve.py").read_text()
    assert "review_crop_router" in serve, "le router doit être monté sur l'app lean"
    server = (ML_DIR / "serving/server.py").read_text()
    assert "review_crop_router" not in server, (
        "l'app full sert déjà ces chemins par le legacy — les monter deux fois "
        "ferait gagner l'un des deux au hasard de l'ordre d'inclusion"
    )


def test_le_recadrage_est_ouvert_a_un_ami_pas_reserve_a_l_arbitre():
    """Recadrer n'est pas arbitrer : c'est la DÉCISION qui est en quarantaine.

    Si ces routes passaient sous `review:arbitrate`, le lot 6b n'aurait servi à
    rien — l'ami retrouverait un bouton mort, juste avec un autre message.
    """
    source = (ML_DIR / "serving/review_queue/crop_routes.py").read_text()
    assert 'require_scope("review:write")' in source
    assert "review:arbitrate" not in source.split('"""', 2)[2]


# ─── 2. Les URLs servies sont absolues ──────────────────────────────────────


def test_l_url_du_contexte_est_signee_quand_la_cle_minio_existe(monkeypatch):
    from serving import crop_edit_api
    from serving.crop_edit import CropEditContextData

    monkeypatch.setitem(
        sys.modules, "shared.storage",
        type(sys)("shared.storage"),
    )
    sys.modules["shared.storage"].signed_url = (
        lambda bucket, key: f"https://minio.test/{bucket}/{key}?sig=x"
    )

    ctx = CropEditContextData(
        asset_id="A1", source="ebay", source_image_id="SI1",
        raw_storage_path="ebay/si1.jpg", crop_storage_path="ebay/a1.png",
        raw_width=800, raw_height=600, hint={"cx": 1, "cy": 2, "r": 3},
    )
    out = crop_edit_api.crop_edit_context_response(ctx)
    assert out.raw_url.startswith("https://minio.test/enrichment-raws/")
    assert out.crop_url.startswith("https://minio.test/enrichment-crops/")
    assert out.hint == {"cx": 1, "cy": 2, "r": 3}


# ─── 3 et 4. Le recadrage lui-même ──────────────────────────────────────────


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    """Un asset avec un vrai RAW sur disque, MinIO simulé.

    On ne parle pas au vrai MinIO : un recadrage ÉCRASE l'objet en place (D9),
    et le faire depuis un test toucherait une image de production.
    """
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    db = tmp_path / "t.db"
    store = Store(db)
    conn = store._connection()
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    _, assets, reviews = _seed_listing(conn, item_id="R1")
    conn.execute(
        "UPDATE image_assets SET storage_path='ebay/crop.png' WHERE id=?", (assets[0],))
    conn.execute(
        "UPDATE source_images SET storage_path='ebay/raw.jpg', width=600, height=600 "
        "WHERE id='SI_R1'")
    conn.commit()

    # Un raw synthétique : fond sombre, disque clair au centre.
    raw = np.zeros((600, 600, 3), dtype=np.uint8)
    cv2.circle(raw, (300, 300), 200, (200, 200, 200), -1)
    raw_p = tmp_path / "raw.jpg"
    cv2.imwrite(str(raw_p), raw)

    uploads: list[tuple[str, str, int]] = []
    from shared.storage import local_cache

    monkeypatch.setattr(local_cache, "local_path", lambda bucket, key: raw_p)
    monkeypatch.setattr(
        local_cache, "cache_path_for", lambda bucket, key: tmp_path / "cache" / key)
    monkeypatch.setattr(
        local_cache, "upload_through",
        lambda bucket, key, data: uploads.append((bucket, key, len(data))))
    monkeypatch.setenv("EURIO_API_URL", "")  # pas de forward /ingest : on EST le canonique
    return store, conn, assets[0], reviews[0], uploads


def test_le_recadrage_ecrit_le_format_de_prod_et_la_geometrie(rig):
    from serving.crop_edit import apply_manual_crop

    store, conn, asset_id, _, uploads = rig
    data = apply_manual_crop(store, asset_id, cx=300, cy=300, r=200)

    assert data.detection_method == "manual"
    assert (data.width, data.height) == (224, 224), (
        "224 est LE format de prod (`_crop_mask_resize_float`) — un autre "
        "chiffre voudrait dire qu'on a réimplémenté le crop à côté"
    )
    assert data.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert uploads == [("enrichment-crops", "ebay/crop.png", len(data.png_bytes))], (
        "le crop est écrasé EN PLACE, sur la même clé MinIO (D9)"
    )

    row = conn.execute(
        "SELECT bbox_json, detection_method, width, height, phash, "
        "       eurio_id, resolution_status, training_eligible "
        "  FROM image_assets WHERE id = ?", (asset_id,)).fetchone()
    assert row["detection_method"] == "manual"
    assert json.loads(row["bbox_json"]) == {"x": 100.0, "y": 100.0, "w": 400.0, "h": 400.0}
    assert row["phash"] is not None
    # Recadrer n'est PAS décider : l'attribution et l'éligibilité ne bougent pas.
    assert row["eurio_id"] is None
    assert row["resolution_status"] == "needs_review"
    assert row["training_eligible"] == 0


def test_un_echec_minio_n_ecrit_pas_la_geometrie(rig, monkeypatch):
    """Sinon la base décrit un crop que MinIO ne contient pas — en silence.

    L'échec était avalé (`minio_ok=False`) et la suite s'exécutait : `bbox_json`,
    `detection_method='manual'`, 224×224 et un phash tout neuf en base, un 200 à
    l'écran, le crop redessiné dans l'éditeur… et l'ANCIEN objet dans MinIO. Ce
    sont ces pixels-là qui partent à l'entraînement, et `minio_ok` n'était lu
    NULLE PART côté front.
    """
    from fastapi import HTTPException

    from shared.storage import local_cache

    store, conn, asset_id, _, _ = rig

    def refuse(bucket, key, data):
        raise RuntimeError("MinIO injoignable")

    monkeypatch.setattr(local_cache, "upload_through", refuse)

    from serving.crop_edit import apply_manual_crop

    avant = dict(conn.execute(
        "SELECT bbox_json, detection_method, width, height, phash FROM image_assets "
        " WHERE id = ?", (asset_id,)).fetchone())

    with pytest.raises(HTTPException) as exc:
        apply_manual_crop(store, asset_id, cx=300, cy=300, r=200)
    assert exc.value.status_code == 502

    apres = dict(conn.execute(
        "SELECT bbox_json, detection_method, width, height, phash FROM image_assets "
        " WHERE id = ?", (asset_id,)).fetchone())
    assert apres == avant, (
        "aucune écriture ne doit survivre à un stockage raté : une géométrie "
        "qui décrit un objet inexistant est pire qu'un recadrage perdu"
    )


def test_un_cercle_hors_du_raw_est_refuse(rig):
    from fastapi import HTTPException

    from serving.crop_edit import apply_manual_crop

    store, _, asset_id, _, _ = rig
    with pytest.raises(HTTPException) as exc:
        apply_manual_crop(store, asset_id, cx=5000, cy=5000, r=10)
    assert exc.value.status_code == 422


def test_dino_est_marque_perime_mais_reste_servi(rig, monkeypatch):
    """Sur le VPS il n'y a pas de DINO (D6) — mais la suggestion NE DISPARAÎT PAS.

    Première version : on supprimait la prédiction, l'absence servant de marqueur.
    Le PO l'a réfuté à la première vraie session : « je commence toujours par
    faire le recadrage et après je pick la bonne pièce. Souvent, la suggestion de
    Dino de base est bonne. » Le geste réel est un ajustement AU MICRO, suivi du
    choix de la pièce : supprimer retirait l'aide juste au moment où elle sert.

    On date donc la péremption (migration 0013). La prédiction reste servie,
    l'écran le dit, et `_existing_keys` la traite comme absente — donc le
    backfill la réencode SANS `--force`.
    """
    store, conn, asset_id, _, _ = rig
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
        "  anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim) "
        "VALUES (?, 'dinov2-vits14', '2eur_commemo', 8, '[]', 'fr-2015-2eur-paix', 0.9)",
        (asset_id,))
    conn.commit()

    # Simule l'image lean : `sources._base.steps.auto_validate` n'y est pas.
    import builtins

    vrai_import = builtins.__import__

    def sans_auto_validate(name, *a, **kw):
        if name == "sources._base.steps.auto_validate":
            raise ImportError("No module named 'torch'")
        return vrai_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", sans_auto_validate)

    from serving.crop_edit import apply_manual_crop

    data = apply_manual_crop(store, asset_id, cx=300, cy=300, r=180)
    monkeypatch.undo()

    assert data.dino_recomputed is False
    row = conn.execute(
        "SELECT top1_eurio_id, stale_since FROM image_asset_dino_predictions "
        " WHERE asset_id = ?", (asset_id,)).fetchone()
    assert row is not None, "la prédiction doit RESTER — c'est tout l'objet de 0013"
    assert row["top1_eurio_id"] == "fr-2015-2eur-paix", "et garder sa suggestion"
    assert row["stale_since"], "datée comme périmée par le recadrage"


def test_une_prediction_perimee_est_a_reencoder_sans_force(rig):
    """Le marquage ne sert à rien si le backfill continue de la sauter."""
    from sources._base.steps.auto_validate import _existing_keys

    _, conn, asset_id, _, _ = rig
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
        "  anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim) "
        "VALUES (?, 'dinov2-vits14', '2eur_commemo', 8, '[]', 'x', 0.9)",
        (asset_id,))
    conn.commit()

    args = ([asset_id], "dinov2-vits14", "2eur_commemo")
    assert _existing_keys(conn, *args) == {asset_id}, "fraîche → sautée"

    conn.execute(
        "UPDATE image_asset_dino_predictions SET stale_since = datetime('now') "
        " WHERE asset_id = ?", (asset_id,))
    conn.commit()
    assert _existing_keys(conn, *args) == set(), (
        "périmée → traitée comme ABSENTE, donc réencodée sans --force"
    )


def test_le_reencodage_leve_la_peremption_par_le_vrai_chemin(rig):
    """Le cycle marquer → réencoder → démarquer doit BOUCLER.

    ⚠️ La première version de ce test lisait le SQL de
    `sources/_base/steps/auto_validate.py` avec un `str.index` — un grep, sur la
    branche `store is None`, celle qui ne tourne JAMAIS en production. Le vrai
    point de passage est `store/dino.py::_upsert_dino_rows_sql`, partagé par le
    backfill (qui construit un `Store`) et par le write-half de
    `POST /ingest/dino`. Il n'avait pas la clause, et rien ne rougissait.

    Ce qui pourrissait des DEUX côtés, en silence :
      · l'écran annonçait « calculée avant ton recadrage » à jamais, sur une
        prédiction pourtant fraîche — le mensonge exact que 0013 devait éviter ;
      · `_existing_keys` la voyait « absente » à CHAQUE backfill, donc la
        réencodait indéfiniment, pour un coût qui grandit avec les recadrages.

    D'où ce test : on passe par `store.upsert_dino_predictions`, pas par une
    lecture de fichier.
    """
    from sources._base.steps.auto_validate import _existing_keys
    from store.dino import DinoPredictionRow

    store, conn, asset_id, _, _ = rig
    enc, kind = "dinov2-vits14", "2eur_commemo"
    ligne = DinoPredictionRow(
        asset_id=asset_id, encoder_version=enc, anchors_kind=kind,
        anchors_count=8, top_k=[{"eurio_id": _TARGET, "sim": 0.9}],
        top1_eurio_id=_TARGET, top1_sim=0.9,
    )
    store.upsert_dino_predictions([ligne])

    def stale():
        return conn.execute(
            "SELECT stale_since FROM image_asset_dino_predictions WHERE asset_id=?",
            (asset_id,)).fetchone()["stale_since"]

    assert stale() is None
    conn.execute(
        "UPDATE image_asset_dino_predictions SET stale_since='2026-08-23T20:00:00Z' "
        " WHERE asset_id = ?", (asset_id,))
    conn.commit()
    assert stale() is not None
    assert _existing_keys(conn, [asset_id], enc, kind) == set(), "périmée → à réencoder"

    # Le ré-encodage, par le chemin que le backfill emprunte réellement.
    store.upsert_dino_predictions([ligne])

    assert stale() is None, (
        "un ré-encodage doit LEVER la péremption — sinon le bandeau ment pour "
        "toujours et le backfill réencode le même crop à chaque passage"
    )
    assert _existing_keys(conn, [asset_id], enc, kind) == {asset_id}, (
        "et l'asset doit redevenir « déjà fait », sinon la boucle est infinie"
    )


def test_le_forward_ingest_dino_leve_aussi_la_peremption(rig):
    """Sous Direction A, le Mac calcule et POSTe : ce chemin-là compte autant.

    Il partage le même SQL — ce test le VERROUILLE, pour qu'une divergence entre
    les deux write-halves ne puisse pas se réintroduire sans échouer.
    """
    from store.dino import DinoPredictionRow, apply_ingest_dino

    store, conn, asset_id, _, _ = rig
    ligne = DinoPredictionRow(
        asset_id=asset_id, encoder_version="dinov2-vits14",
        anchors_kind="2eur_commemo", anchors_count=8,
        top_k=[{"eurio_id": _TARGET, "sim": 0.9}],
        top1_eurio_id=_TARGET, top1_sim=0.9,
    )
    store.upsert_dino_predictions([ligne])
    conn.execute(
        "UPDATE image_asset_dino_predictions SET stale_since='2026-08-23T20:00:00Z' "
        " WHERE asset_id = ?", (asset_id,))
    conn.commit()

    res = apply_ingest_dino(conn, [ligne])
    conn.commit()
    assert res["updated"] == 1 and not res["missing"]
    assert conn.execute(
        "SELECT stale_since FROM image_asset_dino_predictions WHERE asset_id=?",
        (asset_id,)).fetchone()["stale_since"] is None


def test_referential_n_a_plus_besoin_de_pillow():
    """`ModuleNotFoundError: No module named 'PIL'` skippait tout le router.

    Mesuré le 2026-08-23 sur le VPS. Le module ne porte pourtant, pour l'API,
    que des helpers de CHEMIN — l'encodage WebP est le seul à vouloir Pillow.
    """
    source = (ML_DIR / "referential/coin_image_storage.py").read_text()
    tete = source.split("def encode_webp", 1)[0]
    assert "from PIL import Image" not in tete, (
        "l'import Pillow doit rester DANS encode_webp"
    )
    assert "from PIL import Image" in source, "l'encodage en a toujours besoin"


# ─── 5. L'ouverture de l'éditeur ne dépend plus du RAW ──────────────────────


@pytest.fixture()
def rig_piece(rig, tmp_path, monkeypatch):
    """Le rig, mais avec un raw que le détecteur voit VRAIMENT, et une bbox.

    Le disque uniforme du rig de base ne rend AUCUN cercle : `_dominant_circle`
    passe par `HoughCircles`, qui travaille sur le gradient — un aplat n'en a
    qu'au bord, et `param2=30` ne s'en contente pas. On ajoute donc un jonc
    (l'anneau clair du listel d'une pièce), et le détecteur le trouve.

    Ce détail n'est pas cosmétique : c'est la même raison qui fait que la
    suggestion ne sort que 3 fois sur 40 en production (mesuré le 2026-08-24 sur
    des items ouverts au hasard). Le batch `scripts/recrop_ebay_refine` utilise,
    lui, `vision.crop_detectors` — un détecteur de rim, pas un Hough nu.
    """
    import numpy as np

    cv2 = pytest.importorskip("cv2")
    store, conn, asset_id, review_id, uploads = rig

    raw = np.full((600, 600, 3), 30, dtype=np.uint8)
    cv2.circle(raw, (300, 300), 200, (200, 200, 200), -1)
    cv2.circle(raw, (300, 300), 185, (150, 150, 150), -1)   # le jonc
    raw_p = tmp_path / "piece.jpg"
    cv2.imwrite(str(raw_p), raw)

    from shared.storage import local_cache

    monkeypatch.setattr(local_cache, "local_path", lambda bucket, key: raw_p)
    conn.execute(
        "UPDATE image_assets SET bbox_json=? WHERE id=?",
        (json.dumps({"x": 100, "y": 100, "w": 400, "h": 400}), asset_id))
    conn.commit()
    return store, conn, asset_id, review_id, uploads


def test_le_contexte_sans_suggestion_ne_touche_jamais_au_raw(rig_piece, monkeypatch):
    """`with_suggestion=False` = que du SQL. C'est la garantie d'ouverture.

    Avant le 2026-08-24, `load_crop_edit_context` lançait un Hough — donc un
    `local_path`, donc un téléchargement MinIO — sur le chemin BLOQUANT de la
    modale. Le chemin nominal est rapide (p50 0,08 s / p90 0,17 s mesurés sur 40
    items ouverts), mais il n'a aucun plafond naturel : un objet lent retenait
    l'OUVERTURE de l'éditeur, pas seulement l'aide facultative qu'il porte.

    Ici on rend `local_path` explosif : si le contexte y touche encore, le test
    rougit. Une régression sur ce point serait autrement **muette** — elle ne se
    verrait qu'un jour de MinIO lent, chez l'opérateur, sans laisser de trace.
    """
    from serving.crop_edit import load_crop_edit_context
    from shared.storage import local_cache

    store, _, asset_id, _, _ = rig_piece

    def _interdit(bucket, key):
        raise AssertionError("le contexte sans suggestion ne doit PAS lire le raw")

    monkeypatch.setattr(local_cache, "local_path", _interdit)

    ctx = load_crop_edit_context(store, asset_id, with_suggestion=False)
    assert ctx.suggested is None
    assert ctx.hint is not None, "le cercle de départ vient de la bbox, pas du raw"


def test_la_suggestion_vit_dans_son_propre_appel(rig_piece):
    """Le cercle proposé sort bien — mais par `compute_crop_suggestion`."""
    from serving.crop_edit import compute_crop_suggestion

    store, _, asset_id, _, _ = rig_piece

    circle, reason = compute_crop_suggestion(store, asset_id)
    assert reason is None and circle is not None, f"aucune suggestion : {reason}"
    assert abs(circle["cx"] - 300) < 40 and abs(circle["cy"] - 300) < 40


def test_un_lot_dit_POURQUOI_il_n_a_pas_de_suggestion(rig_piece):
    """Sur une source multi-crops, la suggestion est refusée — et NOMMÉE.

    Un Hough global sauterait sur la plus grosse pièce du plateau, pas celle
    qu'on édite. Mesuré le 2026-08-24 : 5 548 des 8 496 items ouverts (65 %)
    sont dans ce cas — c'est-à-dire que l'opérateur voyait « le cadre n'a pas
    bougé cette fois » deux fois sur trois, sans jamais savoir pourquoi. La
    raison rendue est ce qui permet à l'écran de le DIRE.
    """
    from serving.crop_edit import compute_crop_suggestion

    store, conn, asset_id, _, _ = rig_piece
    row = conn.execute(
        "SELECT source_image_id, bbox_json FROM image_assets WHERE id=?",
        (asset_id,)).fetchone()
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, bbox_json, "
        "storage_path, storage_status) "
        "VALUES ('A_SECOND', ?, 1, ?, 'ebay/crop2.png', 'present')",
        (row["source_image_id"], row["bbox_json"]))
    conn.commit()

    circle, reason = compute_crop_suggestion(store, asset_id)
    assert circle is None and reason == "lot"


def test_la_route_de_suggestion_existe_sur_le_lean_et_sur_le_lourd():
    """Les deux jumeaux doivent la porter : le VPS sert la review des amis.

    ⚠️ Ce test ne cherchait qu'une CHAÎNE dans le source du jumeau lourd. Il
    passait donc au vert sur un module dont les cinq routes de recadrage
    levaient `NameError` — `_asset_id_for_review` n'y était **définie nulle
    part**. Trouvé en revue le 2026-08-24. On importe désormais le module et on
    vérifie que l'aide existe : chercher un nom de chemin dans un fichier n'est
    pas tester un chemin.
    """
    from serving.review_queue import crop_routes
    from review import review_queue_routes as lourd

    paths = {r.path for r in crop_routes.router.routes}
    assert "/review-queue/{review_id}/crop-suggestion" in paths

    paths_lourd = {r.path for r in lourd.router.routes}
    assert "/review-queue/{review_id}/crop-suggestion" in paths_lourd
    assert callable(lourd._asset_id_for_review), (
        "les cinq routes de recadrage du jumeau lourd l'appellent — "
        "sans elle, elles rendent 500 sur toutes leurs requêtes")


def test_la_route_de_suggestion_repond_par_HTTP(rig_piece, monkeypatch):
    """Le câblage HTTP, pas seulement la fonction : dépendances, modèle, 404.

    Le test de registration ci-dessus ne dit que « le chemin existe ». Une
    dépendance mal typée ou un `response_model` incompatible passe ce test-là et
    rend 500 en production — sur une route que personne ne surveille, parce
    qu'elle ne sert qu'une aide facultative.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from serving.auth_principal import Principal, require_principal
    from serving.deps import db_connection
    from serving.review_queue import crop_routes

    store, conn, asset_id, review_id, _ = rig_piece
    monkeypatch.setattr(crop_routes, "_store", lambda: store)

    app = FastAPI()
    app.include_router(crop_routes.router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="t", email="t@test.local", roles=["reviewer"],
        scopes={"review:write"}, auth_method="api_token",
    )
    app.dependency_overrides[db_connection] = lambda: conn
    client = TestClient(app)

    r = client.get(f"/review-queue/{review_id}/crop-suggestion")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset_id"] == asset_id
    assert body["reason"] is None and body["circle"] is not None

    # Le contexte, lui, doit savoir se passer du raw quand on le lui demande.
    r = client.get(f"/review-queue/{review_id}/crop-edit-context?suggestion=0")
    assert r.status_code == 200, r.text
    assert r.json()["suggested_circle"] is None

    # 404, pas 500 : `asset_id_for_review` LÈVE, elle ne rend pas None — la
    # garde `if asset_id is None` des trois handlers était morte, et un id
    # inconnu sortait en 500. Corrigé le 2026-08-24, verrouillé ici.
    assert client.get("/review-queue/nexistepas/crop-suggestion").status_code == 404
    assert client.get(
        "/review-queue/nexistepas/crop-edit-context").status_code == 404
    assert client.post(
        "/review-queue/nexistepas/manual-crop",
        json={"cx": 1, "cy": 1, "r": 1}).status_code == 404
