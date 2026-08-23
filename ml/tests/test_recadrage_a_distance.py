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

4. **DINO est marqué « à réencoder ».** Sans ça, le crop garde une prédiction
   calculée sur l'ANCIEN cadrage — celui que l'humain vient de corriger. Une
   suggestion sûre d'elle et fausse est pire qu'un panneau vide.
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


def test_un_cercle_hors_du_raw_est_refuse(rig):
    from fastapi import HTTPException

    from serving.crop_edit import apply_manual_crop

    store, _, asset_id, _, _ = rig
    with pytest.raises(HTTPException) as exc:
        apply_manual_crop(store, asset_id, cx=5000, cy=5000, r=10)
    assert exc.value.status_code == 422


def test_dino_est_marque_a_reencoder_faute_de_torch(rig, monkeypatch):
    """Sur le VPS il n'y a pas de DINO (D6) : la prédiction périmée doit partir.

    Elle a été calculée sur l'ANCIEN cadrage. La garder afficherait à l'ami
    suivant une suggestion confiante et fausse ; l'absence, elle, programme le
    rattrapage — `backfill_dino_predictions` encode exactement les assets sans
    ligne pour `(encoder_version, anchors_kind)`.
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
    reste = conn.execute(
        "SELECT count(*) FROM image_asset_dino_predictions WHERE asset_id = ?",
        (asset_id,)).fetchone()[0]
    assert reste == 0, "la prédiction du cadrage d'AVANT doit disparaître"


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
