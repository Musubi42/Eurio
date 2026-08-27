"""`crop_edit_observations` — le recadrage manuel devient une vérité terrain.

Pourquoi cette table existe, et pourquoi ces gardes :

Sept chantiers « crop » entre mai et août 2026 ont chacun atteint leur cible sur
leur PROPRE oracle et produit des crops que l'humain jette. Le dépôt n'a aucune
vérité terrain sur le cadrage — `review_queue.decision_notes` ne prend que
`rejected` et `other`, et `serving/crop_edit.py` écrase la géométrie proposée
EN PLACE, au moment même où elle devient une étiquette.

Ce que ces tests verrouillent :

1. le delta se mesure depuis `start_*` (ce qui était à l'écran), **jamais**
   depuis `before_*` — sinon on attribue à l'humain le déplacement fait par la
   suggestion Hough ;
2. l'AVANT est relu en base, jamais cru sur parole du client ;
3. `outcome='inchange'` avec `touched=1` n'est PAS la même observation qu'avec
   `touched=0` : le premier est un accord APRÈS examen, le second peut être un
   clic par erreur. Le jeu d'or veut le premier ;
4. l'applier s'importe dans l'image LEAN — ni torch, ni cv2, ni `training`.
"""
from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from store import Store
from store.crop_observations import apply_crop_observation, classify, compute_deltas


@dataclass
class Obs:
    asset_id: str = "A1"
    actor: str = "admin"
    start_origin: str = "hint"
    review_id: str | None = "R1"
    start_cx: float | None = None
    start_cy: float | None = None
    start_r: float | None = None
    after_cx: float | None = None
    after_cy: float | None = None
    after_r: float | None = None
    suggestion_cx: float | None = None
    suggestion_cy: float | None = None
    suggestion_r: float | None = None
    suggestion_reason: str | None = None
    touched: bool = False
    saved: bool = True
    editor_version: str = "v1"


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    c.row_factory = sqlite3.Row
    c.execute("INSERT INTO source_images (id, source, source_ref) "
              "VALUES ('SI','ebay','r1')")
    c.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, bbox_json, "
        " detection_method, storage_path, storage_status, resolution_status) "
        "VALUES ('A1','SI',0,'{\"x\":100,\"y\":100,\"w\":200,\"h\":200}',"
        " 'yolo+hough+rimrefine','a1.png','present','needs_review')")
    c.commit()
    return c


def _last(conn):
    return conn.execute(
        "SELECT * FROM crop_edit_observations ORDER BY id DESC LIMIT 1").fetchone()


# ── L'avant vient de la base, pas du client ────────────────────────────────

def test_l_avant_est_relu_en_base(conn):
    """Un client peut se tromper ou mentir ; la base, non. `before_*` est le
    cercle inscrit de la bbox stockée, et `before_method` dit QUEL détecteur
    l'humain corrige — la colonne qui manquait le plus."""
    apply_crop_observation(conn, Obs(after_cx=200, after_cy=200, after_r=100))
    conn.commit()
    r = _last(conn)
    assert (r["before_cx"], r["before_cy"], r["before_r"]) == (200.0, 200.0, 100.0)
    assert r["before_method"] == "yolo+hough+rimrefine"


def test_un_asset_inconnu_est_nomme_jamais_ecrit(conn):
    """Un `missing` non lu, c'est une observation qu'on croit enregistrée."""
    res = apply_crop_observation(conn, Obs(asset_id="FANTOME"))
    conn.commit()
    assert res == {"written": False, "outcome": None, "missing": ["FANTOME"]}
    assert conn.execute("SELECT COUNT(*) c FROM crop_edit_observations"
                        ).fetchone()["c"] == 0


# ── Le delta part de l'ÉCRAN, pas du stockage ──────────────────────────────

def test_le_delta_part_de_start_pas_de_before(conn):
    """LE point qui compte. L'éditeur démarre sur `hint`, puis la suggestion
    Hough le remplace en différé si l'humain n'a pas encore touché. Mesurer
    depuis `before_*` attribuerait à l'humain un déplacement fait par le Hough.

    Ici : bbox à r=100, la suggestion a posé r=150 à l'écran, l'humain sauve à
    r=150 — il n'a RIEN fait. Le delta doit valoir 1,0, pas 1,5.
    """
    apply_crop_observation(conn, Obs(
        start_origin="suggestion", start_cx=200, start_cy=200, start_r=150,
        after_cx=200, after_cy=200, after_r=150))
    conn.commit()
    r = _last(conn)
    assert r["d_r_ratio"] == pytest.approx(1.0)
    assert r["outcome"] == "inchange"


def test_les_deltas_de_centre_sont_signes_et_separes(conn):
    """Un biais systématique (« le détecteur cadre toujours trop haut »)
    s'annulerait dans une distance euclidienne. On garde x et y, signés."""
    apply_crop_observation(conn, Obs(
        start_cx=200, start_cy=200, start_r=100,
        after_cx=180, after_cy=230, after_r=100))
    conn.commit()
    r = _last(conn)
    assert r["d_cx_norm"] == pytest.approx(-0.20)
    assert r["d_cy_norm"] == pytest.approx(0.30)
    assert r["d_center_norm"] == pytest.approx(0.3605, abs=1e-3)


# ── L'étiquette ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("d_r, d_c, attendu", [
    (1.00, 0.00, "inchange"),
    (1.20, 0.00, "agrandi"),
    (0.80, 0.00, "retreci"),
    (1.00, 0.30, "recentre"),
    (1.00, 0.90, "remplace"),
    (1.50, 0.90, "remplace"),   # 'remplace' l'emporte sur le rayon
    (1.05, 0.10, "inchange"),   # sous tous les seuils : c'est un accord
])
def test_l_etiquette_suit_les_seuils(d_r, d_c, attendu):
    assert classify(d_r, d_c, touched=True, saved=True) == attendu


def test_inchange_touche_n_est_pas_inchange_non_touche(conn):
    """« Bougé puis remis en place » (touched=1) est un ACCORD APRÈS EXAMEN —
    c'est le meilleur signal positif du jeu. « Pas touché » (touched=0) peut
    n'être qu'un clic par erreur. Les deux portent `outcome='inchange'` : c'est
    `touched` qui les sépare, et c'est pour ça que la colonne existe à part."""
    apply_crop_observation(conn, Obs(
        start_cx=200, start_cy=200, start_r=100,
        after_cx=200, after_cy=200, after_r=100, touched=True))
    apply_crop_observation(conn, Obs(
        start_cx=200, start_cy=200, start_r=100, saved=False, touched=False))
    conn.commit()
    rows = conn.execute(
        "SELECT outcome, touched FROM crop_edit_observations ORDER BY id"
    ).fetchall()
    assert [(r["outcome"], r["touched"]) for r in rows] == [
        ("inchange", 1), ("inchange", 0)]


def test_ferme_apres_avoir_bouge_est_abandonne_pas_un_accord(conn):
    """Ni un accord ni un désaccord : à exclure du jeu d'or. Un taux qui monte
    signale un éditeur qui frustre."""
    apply_crop_observation(conn, Obs(
        start_cx=200, start_cy=200, start_r=100, saved=False, touched=True))
    conn.commit()
    assert _last(conn)["outcome"] == "abandonne"


def test_la_suggestion_est_gardee_meme_non_appliquee(conn):
    """C'est ce qui permet d'évaluer le Hough contre la main humaine sans
    relancer un seul calcul. Aujourd'hui elle est affichée puis jetée."""
    apply_crop_observation(conn, Obs(
        start_origin="hint", start_cx=200, start_cy=200, start_r=100,
        after_cx=200, after_cy=200, after_r=100,
        suggestion_cx=210, suggestion_cy=190, suggestion_r=130,
        suggestion_reason="cercle_aberrant"))
    conn.commit()
    r = _last(conn)
    assert (r["suggestion_r"], r["suggestion_reason"]) == (130.0, "cercle_aberrant")


def test_un_geste_sans_reference_ne_fabrique_pas_de_delta(conn):
    """Pas de `start_r` exploitable → pas de delta inventé. Un zéro plausible
    est pire qu'un NULL : il entre dans les moyennes."""
    d = compute_deltas(None, None, 0, 200, 200, 100)
    assert d == (None, None, None, None)


# ── Contrats structurels ───────────────────────────────────────────────────

def test_l_applier_ne_tire_aucune_dep_lourde_au_niveau_module():
    """Contrôle STATIQUE (ast). Le contrôle RÉEL est le test suivant : celui-ci
    seul ne verrait pas une chaîne transitive."""
    import ast

    src = (ML_DIR / "store/crop_observations.py").read_text()
    LOURD = {"torch", "cv2", "ultralytics", "numpy", "training", "vision",
             "sources", "review"}
    fautifs = []
    for node in ast.parse(src).body:
        noms = ([a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module or ""] if isinstance(node, ast.ImportFrom)
                else [])
        fautifs += [f"ligne {node.lineno}: {n}" for n in noms
                    if any(n == h or n.startswith(h + ".") for h in LOURD)]
    assert not fautifs, f"deps lourdes au niveau module : {fautifs}"


def test_l_applier_s_importe_vraiment_dans_l_image_LEAN():
    """Le contrôle qui a manqué le 2026-08-27 et coûté un déploiement.

    `review.review_lanes` a l'air inoffensif et tire `training.foundation` en
    TRANSITIF ; un contrôle statique des imports DIRECTS ne le voit pas. Et le
    bloqueur doit utiliser `find_spec` — depuis Python 3.12 `find_module` n'est
    plus consulté sur `meta_path`, un bloqueur écrit à l'ancienne ne bloque
    RIEN et le test passe sans rien prouver.

    En sous-process : vider `sys.modules` en place casse les tests voisins
    (28 échecs en 401, mesuré).
    """
    import os
    import subprocess

    code = (
        "import sys\n"
        "ABSENTS = {'training', 'torch', 'ultralytics', 'cv2'}\n"
        "class _Absent:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ABSENTS:\n"
        "            raise ModuleNotFoundError('No module named ' + repr(name.split('.')[0]))\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Absent())\n"
        "import store.crop_observations\n"
        "print('OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=ML_DIR,
                       env={**os.environ, "PYTHONPATH": str(ML_DIR)},
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, (
        "l'applier ne s'importe pas dans l'image lean — le routeur entier "
        f"serait skippé, en silence :\n{r.stderr[-2000:]}")


# ── La route ───────────────────────────────────────────────────────────────

@pytest.fixture()
def api(tmp_path, monkeypatch):
    """App montée à la main, routeur par routeur — hermétique et rapide.
    Patron de `test_recadrage_a_distance.py` et `test_ingest_dino.py`."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from serving.auth_principal import Principal, require_principal
    from serving.deps import db_connection
    from serving.review_queue import crop_routes

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO source_images (id, source, source_ref) "
                 "VALUES ('SI','ebay','r1')")
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, bbox_json, "
        " detection_method, storage_path, storage_status, resolution_status) "
        "VALUES ('A1','SI',0,'{\"x\":100,\"y\":100,\"w\":200,\"h\":200}',"
        " 'yolo+hough+rimrefine','a1.png','present','needs_review')")
    conn.execute("INSERT INTO review_queue (id, image_asset_id) VALUES ('R1','A1')")
    conn.commit()
    monkeypatch.setattr(crop_routes, "_store", lambda: store)

    app = FastAPI()
    app.include_router(crop_routes.router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="le-po", email="po@test.local", roles=["reviewer"],
        scopes={"review:write"}, auth_method="api_token",
    )
    app.dependency_overrides[db_connection] = lambda: conn
    return conn, TestClient(app)


def test_la_route_d_abandon_enregistre_l_etiquette_positive(api):
    """L'observation qui n'existe nulle part aujourd'hui. `touched=false` veut
    dire « j'ai regardé ce cadrage et je l'ai laissé » — c'est le seul accord
    humain sur un crop que le dispositif sache enregistrer."""
    conn, client = api
    r = client.post("/review-queue/R1/crop-edit-abandon", json={
        "start_origin": "hint", "start_cx": 200, "start_cy": 200, "start_r": 100,
        "touched": False,
    })
    assert r.status_code == 204, r.text
    row = _last(conn)
    assert row["outcome"] == "inchange" and row["touched"] == 0
    assert row["actor"] == "le-po"           # l'auteur, aujourd'hui perdu
    assert row["after_cx"] is None           # pas de geste ≠ geste identique
    assert row["before_method"] == "yolo+hough+rimrefine"


def test_la_route_est_montee_et_repond_204(api):
    from serving.review_queue import crop_routes

    assert "/review-queue/{review_id}/crop-edit-abandon" in {
        r.path for r in crop_routes.router.routes}


def test_une_observation_qui_echoue_ne_casse_JAMAIS_le_geste(api, monkeypatch):
    """L'ordre de priorité n'est pas discutable : une observation perdue coûte
    une ligne de jeu d'or, une observation bloquante coûte le travail du
    reviewer. La route doit rendre 204 même si l'écriture explose."""
    import store.crop_observations as mod

    conn, client = api
    monkeypatch.setattr(mod, "apply_crop_observation",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boum")))
    r = client.post("/review-queue/R1/crop-edit-abandon", json={"touched": False})
    assert r.status_code == 204, r.text
    assert conn.execute("SELECT COUNT(*) c FROM crop_edit_observations"
                        ).fetchone()["c"] == 0
