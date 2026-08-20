"""`coin_assets_routes` doit s'importer sans cv2 — B3, direction 1.

Le compteur d'enrichissement et la galerie sont du SQL pur, mais ils vivaient
dans un module qui importait `crop_edit` (→ cv2) au niveau module. Sur l'image
lean du VPS, l'import échouait et `server_serve.py` skippait le routeur ENTIER :
le canonique ne pouvait pas servir ces deux lectures, et le compteur restait
branché sur le ML API local pendant que la review écrivait sur le VPS.

Ce test verrouille la propriété qui rend la direction 1 possible : lourd gaté
route par route, pas fichier par fichier.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

_MODULE = "serving.coin_assets_routes"
_LEAN_ROUTES = {"/coins/enrichment-counts", "/coins/{eurio_id}/assets"}
_HEAVY_ROUTES = {
    "/coins/assets/{asset_id}/crop-edit-context",
    "/coins/assets/{asset_id}/manual-crop",
}


def _paths(mod) -> set[str]:
    return {getattr(r, "path", "") for r in mod.router.routes}


@pytest.fixture()
def restore_module():
    """Le reload sous cv2 absent laisse le module amputé — on le remet après.

    On restaure l'OBJET module d'origine, on ne le ré-importe pas. Un
    `sys.modules.pop` suivi d'un import neuf fabrique un SECOND objet
    `serving.crop_edit` : les modules qui en gardaient une référence (dont
    `serving.review_queue`) continuent de pointer l'ancien, et un
    `monkeypatch.setattr(crop_edit, "create_manual_crop", …)` posé par un autre
    test ne porte plus sur la fonction réellement appelée — la route part alors
    chercher le raw sur MinIO et rend un 410. C'est exactement la panne muette
    qui faisait échouer `test_review_lots_api::test_add_lot_crop_returns_new_crop`
    en suite complète alors qu'il passait isolément.
    `importlib.reload`, lui, réutilise l'objet existant : les références tiennent.
    """
    original = sys.modules.get("serving.crop_edit")
    yield
    if original is not None:
        sys.modules["serving.crop_edit"] = original
    else:
        sys.modules.pop("serving.crop_edit", None)
    importlib.reload(importlib.import_module(_MODULE))


def test_lean_routes_survive_without_cv2(monkeypatch, restore_module):
    # Une entrée None dans sys.modules fait lever ImportError à l'import.
    monkeypatch.setitem(sys.modules, "serving.crop_edit", None)
    mod = importlib.reload(importlib.import_module(_MODULE))

    assert mod.CROP_EDIT_AVAILABLE is False
    assert _LEAN_ROUTES <= _paths(mod), (
        "les lectures SQL doivent rester servies sans cv2 — c'est ce qui permet "
        "au canonique de servir le compteur d'enrichissement"
    )


def test_heavy_routes_are_not_registered_without_cv2(monkeypatch, restore_module):
    """Une route absente vaut mieux qu'une route qui existe et explose : le front
    découvre la capacité via `hasLocalMlApi`, pas par essai/erreur HTTP."""
    monkeypatch.setitem(sys.modules, "serving.crop_edit", None)
    mod = importlib.reload(importlib.import_module(_MODULE))

    assert not (_HEAVY_ROUTES & _paths(mod))


def test_everything_is_registered_when_cv2_is_available():
    mod = importlib.import_module(_MODULE)
    if not mod.CROP_EDIT_AVAILABLE:
        pytest.skip("cv2 absent de cet environnement")
    paths = _paths(mod)
    assert _LEAN_ROUTES <= paths
    assert _HEAVY_ROUTES <= paths
