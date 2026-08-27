"""`backfill_face` — deux phases, deux machines, et le transport de chacune.

Le script portait un `guard_vps_only` alors que `/ingest/faces` existait déjà
depuis des semaines : le garde décoratif que sa propre docstring dénonce. Mais
le retirer sans rien faire d'autre aurait été faux — le script écrit TROIS
choses, et une seule était transportée :

| écriture                          | avant          | maintenant |
|-----------------------------------|----------------|------------|
| `image_assets.face`               | `/ingest/faces`| idem       |
| `reverse_sim` / `face_margin`     | **rien**       | portées par la même route |
| rejet des revers + reroute        | **rien**       | phase `--reject`, SQL pur, sur le VPS |

D'où la structure en deux phases, calquée sur `backfill_denom` :

- **SCORE** (Mac) — torch + encodeur + octets du crop, pousse par la route ;
- **REJET** (VPS) — SQL pur, lit `face='reverse'` en base.

Ce que ce test verrouille, et pourquoi chaque point a coûté quelque chose :

1. `--reject` ne tire **aucune dep lourde au niveau module** — sinon il échoue
   à l'import dans l'image lean, avant d'avoir rien tenté. Défaut rencontré
   trois fois le 2026-08-27 ;
2. le littéral `_FACE_ENGINE_VERSION`, recopié parce que son module d'origine
   tire `training`, **suit sa source** ;
3. les sims d'audit voyagent **même quand le verdict est skippé** — c'est ce
   qui rend la dérive du seuil mesurable, et cette dérive était réelle
   (rappel 73,3 % → 40,0 % entre juin et août, à seuil inchangé) ;
4. le garde de PROVENANCE (migration 0017) tient : un verdict humain ne bouge
   pour personne.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from store import Store
from store.faces import apply_ingest_faces


@dataclass(frozen=True)
class F:
    asset_id: str
    face: str
    reverse_sim: float | None = None
    face_margin: float | None = None
    anchors_kind: str = "2eur_all"


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    c.row_factory = sqlite3.Row
    c.execute("INSERT INTO source_images (id, source, source_ref) "
              "VALUES ('SI','ebay','r1')")
    c.execute("INSERT INTO image_assets (id, source_image_id, crop_index, "
              " storage_path, storage_status, resolution_status) "
              "VALUES ('A1','SI',0,'a1.png','present','needs_review')")
    c.execute(
        "INSERT INTO image_asset_dino_predictions "
        "(asset_id, encoder_version, anchors_kind, anchors_count, top_k_json) "
        "VALUES ('A1','dinov2-vitl14','2eur_all',2062,'[]')")
    c.commit()
    return c


def test_les_sims_d_audit_voyagent_avec_le_verdict(conn):
    apply_ingest_faces(conn, [F("A1", "reverse", -0.0123, 0.0456)])
    conn.commit()
    got = conn.execute(
        "SELECT reverse_sim, face_margin FROM image_asset_dino_predictions "
        "WHERE asset_id='A1' AND anchors_kind='2eur_all'").fetchone()
    assert got["reverse_sim"] == pytest.approx(-0.0123)
    assert got["face_margin"] == pytest.approx(0.0456)


def test_les_sims_s_ecrivent_meme_quand_le_verdict_est_skippe(conn):
    """C'est ce qui rend la dérive du détecteur MESURABLE.

    Le seuil de face compare 34 ancres de revers à 2 062 d'avers : il dérive
    tout seul à mesure que la banque des avers grossit. On ne l'a vu qu'en
    confrontant la marge du détecteur à des verdicts humains. Si la marge
    suivait le garde du verdict, cette confrontation serait impossible.
    """
    conn.execute("UPDATE image_assets SET face='obverse', face_source='human' "
                 "WHERE id='A1'")
    conn.commit()
    res = apply_ingest_faces(conn, [F("A1", "reverse", -0.02, 0.09)])
    conn.commit()
    assert res["updated"] == 0 and res["skipped"] == 1
    assert conn.execute("SELECT face FROM image_assets WHERE id='A1'"
                        ).fetchone()["face"] == "obverse"
    got = conn.execute("SELECT face_margin FROM image_asset_dino_predictions "
                       "WHERE asset_id='A1'").fetchone()
    assert got["face_margin"] == pytest.approx(0.09)


def test_le_garde_porte_sur_la_provenance_pas_sur_la_presence(conn):
    """Migration 0017 : une face posée par la MACHINE se recalcule, un verdict
    HUMAIN ne bouge pour personne. L'ancienne règle (`face IS NULL`) protégeait
    bien l'humain mais gelait aussi la machine — donc une étiquette machine
    fausse le restait à jamais."""
    conn.execute("UPDATE image_assets SET face='obverse', face_source='pipeline' "
                 "WHERE id='A1'")
    conn.commit()
    res = apply_ingest_faces(conn, [F("A1", "reverse")])
    conn.commit()
    assert res["updated"] == 1
    assert conn.execute("SELECT face FROM image_assets WHERE id='A1'"
                        ).fetchone()["face"] == "reverse"


def test_sans_sims_rien_n_est_touche_cote_predictions(conn):
    """Un appelant qui n'a que le verdict (le scan live) ne doit pas écraser
    des sims existantes par des NULL."""
    conn.execute("UPDATE image_asset_dino_predictions SET reverse_sim=-0.5, "
                 "face_margin=0.1 WHERE asset_id='A1'")
    conn.commit()
    apply_ingest_faces(conn, [F("A1", "obverse")])
    conn.commit()
    got = conn.execute("SELECT reverse_sim FROM image_asset_dino_predictions "
                       "WHERE asset_id='A1'").fetchone()
    assert got["reverse_sim"] == pytest.approx(-0.5)


def test_la_phase_reject_ne_tire_aucune_dep_lourde_au_niveau_module():
    """`--reject` est du SQL pur : il doit tourner sur le VPS, seul writer.

    Contrôle STATIQUE (ast) : bloquer `numpy` dans le process de test le casse
    pour tout le monde — il est déjà chargé et refuse d'être rechargé.
    """
    src = (ML_DIR / "scripts/backfill_face.py").read_text()
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
    """Un littéral recopié qui dérive écrit une version de moteur fausse dans
    `review_queue.decision_engine_version` — invisible jusqu'au jour où l'on
    veut savoir qui a rejeté quoi."""
    from scripts import backfill_face
    from sources._base.steps import enqueue

    assert backfill_face._FACE_ENGINE_VERSION == enqueue._FACE_ENGINE_VERSION


def test_le_backfill_ne_porte_plus_de_garde_vps_only():
    """Le garde envoyait le calcul sur la seule machine qui n'a ni torch ni les
    images, alors que `/ingest/faces` existait déjà."""
    code = (ML_DIR / "scripts/backfill_face.py").read_text()
    assert "from scripts._vps_only_guard import" not in code
    assert "guard_vps_only(" not in code
    assert "i-know-this-is-canonical" not in code
    assert "from client.ingest import push_faces" in code


def test_le_client_poste_bien_sur_ingest_faces():
    """Un `push_faces` aliasé sur une autre route écrirait la mauvaise colonne
    en silence. Le seul invariant qui mord est le CHEMIN."""
    import inspect

    from client import ingest

    assert '"/ingest/faces"' in inspect.getsource(ingest.push_faces)
    assert ingest.push_faces([]) is None  # pas d'appel réseau pour rien


def test_le_perimetre_ne_depend_plus_de_la_presence_d_une_cible():
    """Même élargissement que `backfill_denom` : un JOIN INNER sur
    `target_eurio_id` écartait sans le dire les crops que personne ne trie."""
    src = (ML_DIR / "scripts/backfill_face.py").read_text()
    assert "LEFT JOIN coins c  ON c.eurio_id = s.target_eurio_id" in src
    assert "JOIN coins c ON c.eurio_id = s.target_eurio_id" not in src
    assert "cc.face_value = 2.0" in src
    assert "a.eval_corpus IS NULL" in src


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
        "import scripts.backfill_face\n"
        "print('OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=ML_DIR,
                       env={**os.environ, "PYTHONPATH": str(ML_DIR)},
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, (
        "le script ne s'importe pas dans l'image lean — `--reject` mourra en prod :"
        f"\n{r.stderr[-2000:]}")
