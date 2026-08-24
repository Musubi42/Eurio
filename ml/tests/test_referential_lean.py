"""`referential_routes` doit pouvoir LIRE LA BASE sur l'image lean du VPS.

CE QUE CE TEST GARDE, ET CE QU'IL A COÛTÉ DE NE PAS L'AVOIR
-----------------------------------------------------------
Le router `referential` était monté sur le VPS, visible dans l'OpenAPI, et
**toutes ses routes qui touchent la base répondaient 500**. `_store()` faisait
`from .server import _store`, et `serving/server.py` tire `serving.training_runner`
→ `training.pipeline` : l'image lean ne COPIE pas `training/`.

L'échec arrivait **à l'appel**, jamais au montage — donc aucun test d'import ne
pouvait le voir, et le boot était parfaitement vert. Côté navigateur, le symptôme
était une balise `<img>` vide : plus aucune vignette canonique sur le front
hébergé, écran de review compris — celui qu'utilise un ami. Vérifié en prod le
2026-08-24 : `GET /referential/canonical-index` → 500, trace
`ModuleNotFoundError: No module named 'training'`.

D'où la forme de ces tests : ils n'importent pas, ils **appellent**. Un test
d'import serait passé au vert pendant toute la durée de la panne.

COMMENT ON SIMULE L'IMAGE LEAN
------------------------------
Un sous-processus avec un `MetaPathFinder` qui lève `ModuleNotFoundError` sur les
paquets absents de `infra/eurio-api/Dockerfile`. Un sous-processus, et pas un
`monkeypatch.setitem(sys.modules, …)` : la chaîne est transitive, et un module
déjà chargé par un autre test masquerait l'échec.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent

#: Ce que l'image lean N'A PAS (même liste que `test_class_need_lean`).
ABSENT = (
    "cv2", "torch", "torchvision", "numpy", "PIL", "ultralytics",
    "sklearn", "scipy", "matplotlib",
    "sources", "vision", "training",
)

_PREAMBULE = """
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

import sqlite3
from serving import referential_routes as rr

class FauxStore:
    def __init__(self, conn):
        self._conn = conn
    def _connection(self):
        return self._conn

conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.execute(
    "CREATE TABLE coin_canonical_images "
    "(eurio_id TEXT, role TEXT, source TEXT, url TEXT)"
)
conn.execute(
    "INSERT INTO coin_canonical_images VALUES "
    "('fr-2015-2eur-paix', 'obverse', 'numista', 'https://exemple/paix.jpg')"
)
"""


def _sous_lean(corps: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c",
         _PREAMBULE.format(absent=ABSENT, ml=str(ML_DIR)) + corps],
        capture_output=True, text=True, timeout=120,
    )


def test_lire_la_base_marche_quand_l_app_a_cable_le_store():
    """Le chemin du VPS : `bind()` puis lecture. C'est CE chemin qui était mort."""
    r = _sous_lean("""
rr.bind(FauxStore(conn))
print("SOURCE", rr._lookup_source("fr-2015-2eur-paix", "obverse"))
print("URL", rr._lookup_url("fr-2015-2eur-paix", "obverse"))
""")
    assert r.returncode == 0, (
        "Le router referential ne peut pas lire la base sur l'image lean — "
        "c'est la panne du 2026-08-24 : montage vert, 500 à chaque appel, et "
        "plus une seule vignette canonique sur le front hébergé.\n"
        f"stderr:\n{r.stderr}"
    )
    assert "SOURCE numista" in r.stdout, r.stdout
    assert "URL https://exemple/paix.jpg" in r.stdout, r.stdout


def test_les_urls_de_vignettes_se_calculent_sans_dependance_lourde():
    """`/referential/canonical-thumbs` sert l'accueil d'un ami : s'il tombe, la
    liste perd ses images sans un mot. Le bucket est vide ici — on doit donc
    retomber sur l'URL externe du référentiel, pas sur `None`."""
    r = _sous_lean("""
rr.bind(FauxStore(conn))
print("THUMB", rr._thumb_url("fr-2015-2eur-paix", "obverse", set()))
print("ABSENT", rr._thumb_url("xx-inconnue", "obverse", set()))
""")
    assert r.returncode == 0, r.stderr
    assert "THUMB https://exemple/paix.jpg" in r.stdout, r.stdout
    assert "ABSENT None" in r.stdout, r.stdout


def test_sans_bind_le_lean_retombe_sur_l_import_qui_casse():
    """Le garde-fou du garde-fou.

    Si `_store()` marchait sans `bind()` sous cette sonde, les deux tests
    ci-dessus ne prouveraient rien : ils passeraient aussi avec le code d'AVANT.
    On vérifie donc que le chemin de repli EST bien celui qui échoue — c'est lui
    qui tournait en production.
    """
    r = _sous_lean("""
try:
    rr._lookup_source("fr-2015-2eur-paix", "obverse")
except ModuleNotFoundError as e:
    print("ATTENDU", e.name)
""")
    assert r.returncode == 0, r.stderr
    assert "ATTENDU training" in r.stdout, (
        "la sonde lean ne bloque plus `training` : les tests de ce fichier ne "
        f"prouvent alors rien du tout.\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )


def test_le_lean_declare_bien_le_bind():
    """La source, et non l'app : importer `server_serve` déclenche le boot
    complet. Même convention que `test_serve_router_order`.

    Sans le `True`, `bind()` existe mais n'est jamais appelé — et la panne
    revient telle quelle, sans qu'aucun test unitaire ne rougisse.
    """
    src = (ML_DIR / "serving" / "server_serve.py").read_text(encoding="utf-8")
    assert '("referential", "serving.referential_routes", True)' in src, (
        "referential doit être monté AVEC bind sur l'image lean"
    )
