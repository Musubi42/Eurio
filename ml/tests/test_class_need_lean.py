"""`class_need_routes` doit s'importer sur l'image LEAN — sans cv2, torch, numpy.

POURQUOI CE TEST EST PLUS STRICT QUE `test_coin_assets_lean`
------------------------------------------------------------
Là-bas, un import lourd fait **skipper le routeur** : la prod perd des routes,
elle démarre quand même. Ici, `server_serve.py` importe `class_need_router` au
**niveau module** (mount inconditionnel, comme `thresholds` et `encoder_bench`) :
un import lourd n'entraînerait pas un skip, il empêcherait **l'app entière de
démarrer**. Le canonique tomberait — writer compris.

Et c'est tout l'enjeu d'O2 §Où elle vit : `/besoin` n'est pas `meta.heavy`
précisément parce que ce calcul est du SQL pur. Si une dépendance lourde se
glissait dans la chaîne d'import, la promesse « savoir ce qui manque ne dépend
pas d'un Mac allumé » tomberait sans que rien ne le dise en local — la
workstation, elle, a torch et cv2.

COMMENT ON SIMULE L'IMAGE LEAN
-----------------------------
Un sous-processus avec un `MetaPathFinder` qui lève `ModuleNotFoundError` sur
les paquets absents de `infra/eurio-api/Dockerfile`. Un sous-processus, et pas
un `monkeypatch.setitem(sys.modules, …)` : la chaîne à vérifier est
**transitive** (class_need → bank_classes → …), et un module déjà chargé par un
autre test masquerait l'échec. Ici l'interpréteur part vierge.

Liste tenue à jour avec le Dockerfile : `pip install` n'y pose que fastapi,
uvicorn, pydantic, boto3, httpx, python-jose — et les `COPY` excluent
`sources/`, `vision/`, `training/`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent

#: Ce que l'image lean N'A PAS. `sources`/`vision`/`training` ne sont pas
#: `COPY`és ; les autres ne sont pas `pip install`és.
ABSENT = (
    "cv2", "torch", "torchvision", "numpy", "PIL", "ultralytics",
    "sklearn", "scipy", "matplotlib",
    "sources", "vision", "training",
)

_PROBE = """
import sys, importlib.abc, importlib.machinery

ABSENT = {absent!r}

class _Lean(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".")[0]
        if root in ABSENT:
            raise ModuleNotFoundError(f"No module named {{root!r}}", name=root)
        return None

sys.meta_path.insert(0, _Lean())
sys.path.insert(0, {ml!r})

import {module}
print("OK", len({module}.router.routes))
"""


def _import_under_lean(module: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c",
         _PROBE.format(absent=ABSENT, ml=str(ML_DIR), module=module)],
        capture_output=True, text=True, timeout=120,
    )


def test_le_routeur_du_besoin_s_importe_sans_dependance_lourde():
    r = _import_under_lean("serving.class_need_routes")
    assert r.returncode == 0, (
        "L'app lean ne démarrerait pas — le canonique tomberait, writer compris.\n"
        f"stderr:\n{r.stderr}"
    )
    assert r.stdout.startswith("OK"), r.stdout
    # La route doit être effectivement déclarée, pas juste le module importable.
    assert r.stdout.split()[1] == "1"


def test_les_modules_de_calcul_sont_stdlib_only():
    """Le contrat d'import de `shared/` — il porte tout le reste.

    `class_need` et `dino_scope` le déclarent dans leur en-tête ; ce test le
    vérifie au lieu de le croire.
    """
    for module in ("shared.class_need", "shared.dino_scope",
                   "shared.class_family", "shared.bank_classes"):
        r = subprocess.run(
            [sys.executable, "-c",
             _PROBE.format(absent=ABSENT, ml=str(ML_DIR), module=module)
             .replace('print("OK", len({}.router.routes))'.format(module),
                      'print("OK", 1)')],
            capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, f"{module} tire une dépendance lourde :\n{r.stderr}"


def test_la_sonde_detecte_vraiment_un_import_lourd():
    """Le garde-fou du garde-fou.

    Si le `MetaPathFinder` ne bloquait rien, les deux tests ci-dessus passeraient
    sur la workstation (qui A torch et cv2) et ne verraient jamais une
    régression. On vérifie donc qu'un module notoirement lourd ÉCHOUE.
    """
    r = _import_under_lean("training.foundation.anchors")
    assert r.returncode != 0, (
        "la sonde lean ne bloque rien : les autres tests de ce fichier ne "
        "prouvent alors rien du tout"
    )
