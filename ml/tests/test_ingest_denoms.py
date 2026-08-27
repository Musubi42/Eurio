"""`/ingest/denoms` — le seul endroit où un verdict « 2€ vs junk » atterrit.

Pourquoi la route existe, et pourquoi ce test la garde :

La probe (`vision/denom_probe.py`) est une régression logistique sur
l'embedding DINOv2 vitl14 **gelé** ⊕ `bimetal_score` : elle a besoin de torch,
de l'encodeur et des octets du crop. Le VPS — SEUL writer du canonique — n'a
aucun des trois, et pas par accident : `infra/eurio-api/Dockerfile:7` écrit
« torch / ultralytics : DÉLIBÉRÉMENT ABSENTS ». Le Mac a le moteur et les
images, mais lit une réplique **read-only**. Avant cette route, ce calcul
n'avait littéralement aucune destination — et le backfill portait un
`guard_vps_only` qui l'envoyait sur la seule machine incapable de le faire
tourner. Le calcul reste où sont les images, les LIGNES voyagent.

Ce que ce test verrouille :

1. l'applier est **SQL pur** — s'il importe `cv2`/`numpy`/`torch`/`training`,
   le routeur entier est skippé au boot de l'image lean, en silence ;
2. **anti-clobber** : `denom` n'écrase jamais une étiquette déjà posée (elle
   peut être humaine), mais le SCORE d'audit, lui, se réécrit — c'est la
   sortie continue du modèle, pas un verdict ;
3. un asset inconnu est **refusé et nommé**, jamais écrit ;
4. le backfill ne porte plus le garde, et pousse bien par la route.
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
from store.denoms import apply_ingest_denoms


@dataclass(frozen=True)
class R:
    asset_id: str
    denom: str
    denom_2eur_score: float | None = 0.87
    anchors_kind: str = "2eur_all"


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    c.row_factory = sqlite3.Row
    c.execute("INSERT INTO source_images (id, source, source_ref) "
              "VALUES ('SI','ebay','r1')")
    for idx, aid in enumerate(("A1", "A2")):
        c.execute("INSERT INTO image_assets (id, source_image_id, crop_index, "
                  " storage_path, storage_status, resolution_status) "
                  f"VALUES ('{aid}','SI',{idx},'{aid}.png','present','needs_review')")
    c.execute(
        "INSERT INTO image_asset_dino_predictions "
        "(asset_id, encoder_version, anchors_kind, anchors_count, top_k_json) "
        "VALUES ('A1','dinov2-vitl14','2eur_all',2062,'[]')")
    c.commit()
    return c


def test_pose_le_verdict_et_le_score(conn):
    res = apply_ingest_denoms(conn, [R("A1", "not_2eur", 0.11)])
    conn.commit()
    assert res == {"updated": 1, "skipped": 0, "missing": []}
    assert conn.execute("SELECT denom FROM image_assets WHERE id='A1'"
                        ).fetchone()["denom"] == "not_2eur"
    got = conn.execute(
        "SELECT denom_2eur_score FROM image_asset_dino_predictions "
        "WHERE asset_id='A1' AND anchors_kind='2eur_all'").fetchone()
    assert got["denom_2eur_score"] == pytest.approx(0.11)


def test_n_ecrase_jamais_une_etiquette_deja_posee(conn):
    """`denom` porte aussi des labels HUMAINS. Un re-run de la probe ne doit
    pas les effacer — c'est la sémantique qu'avait déjà l'UPDATE local
    (`WHERE id=? AND denom IS NULL`), et passer par le réseau ne la change pas.
    """
    conn.execute("UPDATE image_assets SET denom='2eur' WHERE id='A1'")
    conn.commit()
    res = apply_ingest_denoms(conn, [R("A1", "not_2eur", 0.03)])
    conn.commit()
    assert res["updated"] == 0 and res["skipped"] == 1
    assert conn.execute("SELECT denom FROM image_assets WHERE id='A1'"
                        ).fetchone()["denom"] == "2eur"


def test_le_score_d_audit_s_ecrit_meme_quand_le_verdict_est_skippe(conn):
    """Savoir ce que la probe pense d'un crop DÉJÀ étiqueté à la main est
    exactement ce qui permet de mesurer sa justesse. Si le score suivait le
    garde du verdict, on ne pourrait jamais confronter le modèle à l'humain.
    """
    conn.execute("UPDATE image_assets SET denom='2eur' WHERE id='A1'")
    conn.commit()
    apply_ingest_denoms(conn, [R("A1", "not_2eur", 0.04)])
    conn.commit()
    got = conn.execute(
        "SELECT denom_2eur_score FROM image_asset_dino_predictions "
        "WHERE asset_id='A1'").fetchone()
    assert got["denom_2eur_score"] == pytest.approx(0.04)


def test_un_asset_inconnu_est_nomme_jamais_ecrit(conn):
    """Un `missing` non lu, c'est une écriture qu'on croit faite."""
    res = apply_ingest_denoms(conn, [R("FANTOME", "2eur")])
    conn.commit()
    assert res["missing"] == ["FANTOME"]
    assert res["updated"] == 0


def test_sans_prediction_le_verdict_passe_quand_meme(conn):
    """A2 n'a aucune ligne de prédiction. Le verdict doit atterrir malgré tout
    — sinon un crop encodé hors du scope de la banque resterait éternellement
    non trié, sans la moindre erreur."""
    res = apply_ingest_denoms(conn, [R("A2", "not_2eur", 0.09)])
    conn.commit()
    assert res["updated"] == 1
    assert conn.execute("SELECT denom FROM image_assets WHERE id='A2'"
                        ).fetchone()["denom"] == "not_2eur"


def test_l_applier_est_sql_pur():
    """S'il tire numpy/torch/cv2, `ingest_routes` explose à l'import et l'image
    lean sert 404 sur TOUTES les routes d'ingest — sans un message."""
    src = (ML_DIR / "store/denoms.py").read_text()
    for lourd in ("import numpy", "import cv2", "import torch", "from training"):
        assert lourd not in src, f"dep lourde interdite dans store/denoms.py : {lourd}"


def test_la_route_est_montee_sur_le_lean():
    """Elle DOIT être servie par le VPS : c'est lui, le writer canonique."""
    from serving import ingest_routes

    assert "/ingest/denoms" in {r.path for r in ingest_routes.router.routes}


def test_le_client_ne_pousse_pas_une_liste_vide(monkeypatch):
    """Pas d'appel réseau pour rien — et surtout pas de faux « poussé »."""
    from client import ingest

    monkeypatch.setenv("EURIO_API_URL", "https://exemple.test")
    assert ingest.push_denoms([]) is None


def test_le_backfill_ne_porte_plus_de_garde_vps_only():
    """Le garde existait parce qu'AUCUNE route ne transportait cette écriture.

    Maintenant qu'elle existe, il protégerait d'un danger disparu — et il
    envoyait le calcul sur la seule machine qui n'a ni torch ni les images.
    Même mouvement que `backfill_quality_score` le 2026-08-25.
    """
    code = (ML_DIR / "scripts/backfill_denom.py").read_text()
    # On vise le CODE, pas la prose : le commentaire qui explique le retrait du
    # garde cite forcément son nom. Un test qui grep le fichier entier
    # interdirait d'expliquer pourquoi on l'a retiré.
    assert "from scripts._vps_only_guard import" not in code
    assert "guard_vps_only(" not in code
    assert "i-know-this-is-canonical" not in code
    assert "from client.ingest import push_denoms" in code, "…et il pousse par la route"
    assert "push_quality_scores" not in code, "…par la SIENNE, pas celle d'à côté"


def test_le_client_poste_bien_sur_ingest_denoms():
    """M6 : un `push_denoms` aliasé sur une autre route passerait tous les
    tests ci-dessus et écrirait la mauvaise colonne, en silence. Le seul
    invariant qui mord est le CHEMIN.
    """
    import inspect

    from client import ingest

    assert '"/ingest/denoms"' in inspect.getsource(ingest.push_denoms)


def test_le_perimetre_ne_depend_plus_de_la_presence_d_une_cible():
    """Le JOIN INNER sur `target_eurio_id` excluait 3 333 crops — ceux-là mêmes
    que la porte doit trier, puisqu'ils tombent en verdict `unknown` et que
    personne ne les regarde. Un JOIN qui restreint sans le dire est le patron
    de panne muette le plus fréquent de ce dépôt.
    """
    src = (ML_DIR / "scripts/backfill_denom.py").read_text()
    assert "LEFT JOIN coins c  ON c.eurio_id = s.target_eurio_id" in src
    assert "JOIN coins c ON c.eurio_id = s.target_eurio_id" not in src
    assert "cc.face_value = 2.0" in src, "…et le repli passe par les candidats"
    assert "a.eval_corpus IS NULL" in src, "…un crop d'éval vit dans un autre bucket"


def test_la_route_se_charge_dans_l_image_LEAN():
    """Le contrôle qui manquait trois fois le 2026-08-27.

    Ce jour-là, la règle de face, les helpers de rejet et la route d'auto-accept
    ont tour à tour été écrits dans un module que l'image lean du VPS ne peut
    pas importer. Le VPS est le SEUL writer : une logique qu'il ne peut pas
    charger est une logique **inexécutable** — et l'échec est muet, FastAPI
    sert simplement 404 sur tout le routeur.

    Le test tourne dans un SOUS-PROCESS. Bloquer torch/cv2 impose de vider
    `sys.modules`, et le faire en place casse les bindings d'auth de tous les
    tests suivants — mesuré : 28 échecs en 401, dont aucun ne parle d'imports.
    Un test qui pollue ses voisins ne prouve rien et coûte une soirée.
    """
    import subprocess

    import os

    # `find_spec`, PAS `find_module` — cf. le test lean plus bas : l'ancien
    # protocole n'est plus consulté depuis Python 3.12 et ne bloque rien.
    code = (
        "import sys\n"
        "ABSENTS = {'training', 'torch', 'ultralytics'}\n"
        "class _Absent:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ABSENTS:\n"
        "            raise ModuleNotFoundError(\n"
        "                'No module named ' + repr(name.split('.')[0]))\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Absent())\n"
        "from serving import ingest_routes\n"
        "assert '/ingest/denoms' in {r.path for r in ingest_routes.router.routes}\n"
        "print('OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=ML_DIR,
                       env={**os.environ, "PYTHONPATH": str(ML_DIR)},
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, f"la route ne se charge pas en lean :\n{r.stderr[-2000:]}"


def test_la_phase_reject_ne_tire_aucune_dep_lourde_au_niveau_module():
    """`--reject` est du SQL pur : il doit tourner sur le VPS, seul writer.

    Si un import LOURD (torch/cv2/numpy, ou un module qui les tire — `training`,
    `vision`, `sources`) remonte au niveau MODULE, `--reject` échoue **à
    l'import** dans l'image lean : avant d'avoir rien tenté, et sans rapport
    avec ce qu'il fait. C'est le défaut rencontré trois fois le 2026-08-27.
    Les imports lourds doivent rester dans `_score_phase`.

    Contrôle STATIQUE (ast) et non par import réel : bloquer `numpy` dans le
    process de test le casse pour tout le monde — il est déjà chargé, et il
    refuse d'être rechargé. Un test qui pollue les suivants ne prouve rien.
    """
    import ast

    src = (ML_DIR / "scripts/backfill_denom.py").read_text()
    LOURD = {"torch", "cv2", "ultralytics", "numpy", "training", "vision",
             "sources", "shared.storage"}
    fautifs = []
    for node in ast.parse(src).body:  # body = NIVEAU MODULE uniquement
        if isinstance(node, ast.Import):
            noms = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            noms = [node.module or ""]
        else:
            continue
        for n in noms:
            if any(n == h or n.startswith(h + ".") for h in LOURD):
                fautifs.append(f"ligne {node.lineno}: {n}")
    assert not fautifs, (
        "imports lourds au niveau module — `--reject` ne tournera pas sur le "
        f"lean : {fautifs}")


def test_le_litteral_recopie_suit_sa_source():
    """`_DENOM_ENGINE_VERSION` est recopié parce que son module d'origine tire
    `training`. Un littéral recopié qui dérive écrit une version de moteur
    fausse dans `review_queue.decision_engine_version` — invisible jusqu'au
    jour où l'on veut savoir qui a rejeté quoi.
    """
    from scripts import backfill_denom
    from sources._base.steps import enqueue

    assert backfill_denom._DENOM_ENGINE_VERSION == enqueue._DENOM_ENGINE_VERSION


def test_le_reject_s_importe_vraiment_SANS_training():
    """Le contrôle qui a manqué, et qui a coûté un déploiement.

    Le test statique d'à côté ne voit que les imports DIRECTS. Or
    `review.review_lanes` — d'apparence inoffensive — tire
    `training.foundation.auto_validate` en TRANSITIF. Tous les tests locaux
    passaient (`training` existe sur le Mac), la prod est morte à l'import :

        File "/srv/ml/review/review_lanes.py", line 45
        ModuleNotFoundError: No module named 'training'

    Seul un import RÉEL, avec les modules absents de l'image lean rendus
    introuvables, attrape une chaîne transitive. En sous-process : vider
    `sys.modules` en place casse les tests voisins (28 échecs en 401, mesuré).
    """
    import os
    import subprocess

    # ⚠️ `find_spec`, PAS `find_module` : depuis Python 3.12, `find_module`
    # n'est plus consulté sur `meta_path`. Un bloqueur écrit avec l'ancien
    # protocole ne bloque RIEN — le test passe et ne prouve rien. C'est
    # exactement ce qui s'est produit le 2026-08-27 : trois tests « lean »
    # verts, et la prod morte à l'import.
    code = (
        "import sys\n"
        "ABSENTS = {'training', 'torch', 'ultralytics'}\n"
        "class _Absent:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ABSENTS:\n"
        "            raise ModuleNotFoundError(\n"
        "                'No module named ' + repr(name.split('.')[0]))\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Absent())\n"
        "import scripts.backfill_denom\n"
        "print('OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=ML_DIR,
                       env={**os.environ, "PYTHONPATH": str(ML_DIR)},
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, (
        "le script ne s'importe pas dans l'image lean — `--reject` mourra en prod :"
        f"\n{r.stderr[-2000:]}")


@pytest.mark.parametrize("script", ["backfill_denom", "backfill_face"])
def test_reject_ne_resout_aucune_destination(script, monkeypatch, capsys):
    """`--reject` écrit la base qu'il LIT, sur le VPS. Il n'a pas de push à
    résoudre — et le lui faire faire le tuait sur le canonique, où
    `EURIO_API_URL` n'existe pas :

        EURIO_API_URL absent : impossible de pousser au canonique.

    Mesuré en prod le 2026-08-27, après le déploiement. Le contrôle est
    statique : c'est la CONDITION qui doit exclure `--reject`.
    """
    src = (ML_DIR / f"scripts/{script}.py").read_text()
    assert "if not args.dry and not args.reject:" in src, (
        f"{script} : la résolution de destination doit exclure --reject")
