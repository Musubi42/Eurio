"""`/ingest/consensus` — le seul endroit où un verdict recalculé peut atterrir.

Pourquoi cette route existe, et pourquoi ce test la garde :

Sous Direction A, le Mac a le moteur de consensus (numpy) mais lit une réplique
**read-only** ; le VPS écrit mais son image lean **n'embarque pas `training/`**
(`docker logs eurio-api` : « routers skippés : review_queue (No module named
'training') »). Recalculer un consensus n'avait donc, littéralement, aucune
destination — c'est ce qui a bloqué le lot B3 de la bascule de banque le
2026-08-24. Le calcul reste où sont les dépendances, les LIGNES voyagent.

Ce que ce test verrouille :

1. l'applier est **SQL pur** — s'il se remet à importer le moteur, l'image lean
   cesse de servir la route, en silence, au prochain déploiement ;
2. un asset inconnu est **refusé et listé**, jamais écrit — une ligne orpheline
   serait une écriture réussie et parfaitement inutile ;
3. l'UPSERT est idempotent et versionné, comme son jumeau `persist.py`.
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
from store.consensus_verdicts import apply_ingest_consensus


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    c.row_factory = sqlite3.Row
    c.execute("INSERT INTO source_images (id, source, source_ref) "
              "VALUES ('SI','ebay','r1')")
    c.execute("INSERT INTO image_assets (id, source_image_id, crop_index, "
              " storage_path, storage_status, resolution_status) "
              "VALUES ('A1','SI',0,'a1.png','present','needs_review')")
    c.commit()
    return c


def _row(aid="A1", *, version=2, outcome="accept"):
    return {
        "image_asset_id": aid, "rule_version": version, "outcome": outcome,
        "lane": "auto_accept", "confidence": 0.9, "reason": "r", "rule": "strong",
        "signals_json": "[]",
    }


def test_l_applier_est_sql_pur(conn):
    """Aucun import du moteur — sinon l'image lean ne peut plus servir la route.

    La panne serait MUETTE : le routeur entier serait skippé au boot, et un
    endpoint SQL pur disparaîtrait de la prod pour avoir cohabité avec un import
    lourd. C'est le piège documenté dans la skill `eurio-vps-deploy`.
    """
    import ast

    # On lit l'ARBRE, pas le texte : ce module PARLE de `training/` et de
    # `persist.py` dans son en-tête, et c'est exactement ce qu'il doit faire —
    # expliquer pourquoi il existe. Un détecteur qui crie sur un commentaire
    # apprend à être ignoré, et c'est comme ça qu'un vrai import finit par
    # passer. (Troisième fois que ce piège se referme dans cette session.)
    arbre = ast.parse((ML_DIR / "store/consensus_verdicts.py").read_text())
    importes: set[str] = set()
    for node in ast.walk(arbre):
        if isinstance(node, ast.Import):
            importes |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            importes.add(node.module)

    for mod in importes:
        racine = mod.split(".")[0]
        assert racine not in {"review", "training", "numpy", "torch", "cv2", "PIL"}, (
            f"consensus_verdicts importe {mod} — l'image lean du VPS ne l'a pas, "
            "et son routeur ENTIER serait skippé au boot, en silence")


def test_ecrit_et_reste_idempotent(conn):
    assert apply_ingest_consensus(conn, [_row()]) == {"written": 1, "missing": []}
    conn.commit()
    assert apply_ingest_consensus(conn, [_row(outcome="needs_review")])["written"] == 1
    conn.commit()

    rows = conn.execute("SELECT outcome, rule_version FROM consensus_verdicts").fetchall()
    assert len(rows) == 1, "l'UPSERT remplace, il n'accumule pas"
    assert rows[0]["outcome"] == "needs_review"


def test_les_versions_de_regle_coexistent(conn):
    """Le bump de `RULE_VERSION` doit préserver l'ancien verdict.

    C'est le véhicule d'une bascule auditable : recalculer sous la même version
    écraserait les 12 618 verdicts d'avant, donc le seul point de comparaison
    disponible le jour où quelqu'un demandera ce que la bascule a changé.
    """
    apply_ingest_consensus(conn, [_row(version=1, outcome="needs_review")])
    apply_ingest_consensus(conn, [_row(version=2, outcome="accept")])
    conn.commit()

    par_version = dict(conn.execute(
        "SELECT rule_version, outcome FROM consensus_verdicts").fetchall())
    assert par_version == {1: "needs_review", 2: "accept"}


def test_un_asset_inconnu_est_refuse_et_nomme(conn):
    res = apply_ingest_consensus(conn, [_row(), _row(aid="FANTOME")])
    conn.commit()
    assert res == {"written": 1, "missing": ["FANTOME"]}
    assert conn.execute(
        "SELECT COUNT(*) FROM consensus_verdicts WHERE image_asset_id='FANTOME'"
    ).fetchone()[0] == 0


def test_la_route_est_montee_sur_le_lean():
    """Elle DOIT être servie par le VPS : c'est lui, le writer canonique."""
    from serving import ingest_routes

    assert "/ingest/consensus" in {r.path for r in ingest_routes.router.routes}
    serve = (ML_DIR / "serving/server_serve.py").read_text()
    assert "ingest_routes" in serve or "ingest_router" in serve


def test_le_client_ne_pousse_pas_une_liste_vide(monkeypatch):
    """Pas d'appel réseau pour rien — et surtout pas de faux « poussé »."""
    from client import ingest

    monkeypatch.setenv("EURIO_API_URL", "https://exemple.test")
    assert ingest.push_consensus([]) is None
