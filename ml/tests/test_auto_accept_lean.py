"""L'auto-acceptation, portée en LEAN et branchée sur le verdict recalculé.

Deux défauts corrigés le 2026-08-27, et il fallait les deux :

1. la route vivait dans `review/review_queue_routes.py`, que l'image du VPS ne
   charge pas — elle était donc ABSENTE de l'OpenAPI de production (vérifié),
   alors que le VPS est le seul writer. L'auto-accept n'était exécutable nulle
   part, et c'est la vraie raison de son zéro depuis le 2026-07-08 ;
2. elle filtrait `rq.lane='auto_accept'` — une étiquette écrite UNE FOIS à
   l'enqueue. Mesuré : la lane disait 960 quand le verdict du jour qualifiait
   2 308. 1 396 crops bons, invisibles.
"""

from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from serving.auth_principal import Principal, require_principal  # noqa: E402
from shared.verdict_scope import (  # noqa: E402
    VERDICT_ANCHORS_KIND,
    VERDICT_ENCODER_VERSION,
)
from store import Store  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = Store(db)._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))

    from serving.review_queue import auto_accept

    app = FastAPI()
    app.include_router(auto_accept.router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="t", email="t@test.local", roles=["owner"],
        scopes={"review:write"}, auth_method="api_token",
    )
    return conn, TestClient(app)


def _crop(conn, aid, *, lane="manual", lane_source="auto", sim=0.80,
          spread=0.20, texte=None, notes=None, cible="fr-x"):
    conn.execute("PRAGMA foreign_keys=OFF")
    sid = f"si_{aid}"
    conn.execute(
        "INSERT OR IGNORE INTO coins (eurio_id, country, year, face_value) "
        "VALUES (?, 'FR', 2015, 2.0)", (cible,))
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, target_eurio_id, "
        " listing_title) VALUES (?, 'ebay', ?, ?, 'un titre')",
        (sid, f"ref_{aid}", cible))
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, crop_index, "
        " resolution_status, face, storage_status, storage_path) "
        "VALUES (?, ?, 0, 'needs_review', 'obverse', 'present', ?)",
        (aid, sid, f"ebay/{sid}/{aid}.png"))
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status, kind, lane, "
        " lane_source, decision_notes) VALUES (?, ?, 'open', 'single', ?, ?, ?)",
        (f"rq_{aid}", aid, lane, lane_source, notes))
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, "
        " anchors_kind, anchors_count, top_k_json, top1_eurio_id, "
        " top1_country_eurio_id, top1_sim, top1_country_sim, spread, "
        " country_spread) VALUES (?, ?, ?, 1, '[]', ?, ?, ?, ?, ?, ?)",
        (aid, VERDICT_ENCODER_VERSION, VERDICT_ANCHORS_KIND, cible, cible,
         sim, sim, spread, spread))
    if texte is not None:
        conn.execute(
            "INSERT INTO listing_text_signals (source_image_id, coverage, "
            " vs_target_verdict) VALUES (?, 'rich', ?)", (sid, texte))
    conn.commit()
    return f"rq_{aid}"


# ─── 1. Le verdict décide, plus la lane ─────────────────────────────────────


def test_un_crop_en_lane_manual_est_quand_meme_servi(env):
    """Mutation : remettre `AND rq.lane = 'auto_accept'` dans le SELECT → rouge.

    C'est LE défaut : la lane est figée à l'enqueue, le verdict se recalcule.
    Un crop qualifié aujourd'hui mais entré hier sous une autre banque restait
    invisible — 1 396 crops dans ce cas au canonique.
    """
    conn, client = env
    _crop(conn, "a1", lane="manual", lane_source="auto")

    r = client.post("/review-queue/auto-accept/run?dry_run=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_eligible_total"] == 1
    assert [p["review_id"] for p in body["preview"]] == ["rq_a1"]


def test_le_deplacement_humain_reste_souverain(env):
    """Mutation : retirer `AND NOT (rq.lane='manual' AND rq.lane_source='human')`
    → rouge.

    C'est le SEUL usage de la lane qui subsiste, et il faut qu'il tienne : un
    humain qui tire un crop hors de l'auto ne doit pas le voir revenir.
    """
    conn, client = env
    _crop(conn, "a2", lane="manual", lane_source="human")

    body = client.post("/review-queue/auto-accept/run?dry_run=true").json()
    assert body["n_eligible_total"] == 0
    assert body["preview"] == []


def test_un_crop_restaure_a_la_main_est_epargne(env):
    """Mutation : retirer la clause `decision_notes != 'restored'` → rouge."""
    conn, client = env
    _crop(conn, "a3", notes="restored")
    assert client.post(
        "/review-queue/auto-accept/run?dry_run=true"
    ).json()["n_eligible_total"] == 0


def test_le_veto_texte_bloque_toujours(env):
    """Mutation : retirer la règle 2 du port lean → rouge."""
    conn, client = env
    _crop(conn, "a4", texte="contradict")
    body = client.post("/review-queue/auto-accept/run?dry_run=true").json()
    assert body["n_eligible_total"] == 0
    assert body["by_category"]["divergent"] == 1


# ─── 2. Le dry-run, et le plafond qui ne ment pas ───────────────────────────


def test_le_dry_run_est_le_defaut_et_n_ecrit_rien(env):
    """Mutation : passer le défaut de `dry_run` à False → rouge.

    L'ancienne route avait `dry_run=False` par défaut : une passe qui écrit
    2 000 décisions ne doit pas être ce qu'on obtient en oubliant un paramètre.
    """
    conn, client = env
    _crop(conn, "a5")

    body = client.post("/review-queue/auto-accept/run").json()  # sans paramètre
    assert body["dry_run"] is True
    assert body["accepted"] == 0
    assert conn.execute(
        "SELECT status FROM review_queue WHERE id='rq_a5'").fetchone()[0] == "open"


def test_le_plafond_borne_l_action_pas_le_comptage(env):
    """Mutation : appliquer `limit` au SELECT SQL → rouge.

    Un lot borné à 1 doit dire qu'il en reste 3. Si le plafond bornait
    l'examen, `n_eligible_total` vaudrait 1 et l'écran ferait croire le
    gisement épuisé — exactement le genre de chiffre plausible et faux qui
    coûte cher ici.
    """
    conn, client = env
    for i in range(3):
        _crop(conn, f"b{i}")

    body = client.post("/review-queue/auto-accept/run?dry_run=true&limit=1").json()
    assert len(body["preview"]) == 1
    assert body["n_eligible_total"] == 3
    assert body["by_category"]["auto_candidate"] == 3


# ─── 3. L'écriture ──────────────────────────────────────────────────────────


def test_l_acceptation_est_estampillee_auto_dino(env):
    """Mutation : écrire `decided_by=principal.user_id` → rouge.

    `auto_dino` est le SEUL compteur qui distingue le travail de la machine de
    celui de l'humain. La route `decide` estampille l'appelant : elle ne peut
    donc pas servir de raccourci pour l'auto-accept sans détruire la mesure.
    """
    conn, client = env
    _crop(conn, "c1")

    body = client.post("/review-queue/auto-accept/run?dry_run=false").json()
    assert body["accepted"] == 1

    row = conn.execute(
        "SELECT status, decided_by, decided_eurio_id FROM review_queue "
        "WHERE id='rq_c1'").fetchone()
    assert row["status"] == "done"
    assert row["decided_by"] == "auto_dino"
    assert row["decided_eurio_id"] == "fr-x"
    a = conn.execute(
        "SELECT resolution_status, training_eligible, eurio_id "
        "FROM image_assets WHERE id='c1'").fetchone()
    assert a["resolution_status"] == "manual"
    assert a["training_eligible"] == 1
    assert a["eurio_id"] == "fr-x"


def test_un_item_decoche_est_demote_en_manual_sticky(env):
    """Mutation : retirer la branche de démotion → rouge.

    C'est le geste « j'ai décoché » de l'écran : il doit être DURABLE, donc
    poser `lane_source='human'` — que le SELECT exclut ensuite.
    """
    conn, client = env
    _crop(conn, "d1")
    _crop(conn, "d2")

    body = client.post(
        "/review-queue/auto-accept/run?dry_run=false",
        json={"review_ids": ["rq_d1"]},
    ).json()
    assert body["accepted"] == 1

    d2 = conn.execute(
        "SELECT status, lane, lane_source FROM review_queue WHERE id='rq_d2'"
    ).fetchone()
    assert d2["status"] == "open"
    assert (d2["lane"], d2["lane_source"]) == ("manual", "human")
    # et il ne revient pas à la passe suivante
    assert client.post(
        "/review-queue/auto-accept/run?dry_run=true"
    ).json()["n_eligible_total"] == 0


# ─── 4. Le module doit rester chargeable par l'image du VPS ─────────────────


def test_le_module_reste_atteignable_depuis_l_image_lean():
    """Mutation : importer `training.foundation.auto_validate` dans le module
    → rouge.

    Sans ce garde, la route retomberait dans le trou d'où on vient de la
    sortir : absente de la production, donc l'auto-accept inexécutable, sans
    qu'aucun test ne rougisse.
    """
    src = (ML_DIR / "serving" / "review_queue" / "auto_accept.py").read_text(
        encoding="utf-8")
    arbre = ast.parse(src)
    importes = {
        n.module.split(".")[0]
        for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module
    } | {
        a.name.split(".")[0]
        for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names
    }
    interdits = importes & {"training", "cv2", "torch", "numpy", "PIL", "review"}
    assert not interdits, f"auto_accept.py importe {interdits}"


def test_la_route_a_bien_quitte_le_module_lourd():
    """Mutation : la remettre dans `review/review_queue_routes.py` → rouge.

    Deux définitions du même chemin, montées par deux serveurs, se
    masqueraient l'une l'autre selon l'ordre d'enregistrement.
    """
    lourd = (ML_DIR / "review" / "review_queue_routes.py").read_text(
        encoding="utf-8")
    assert "/review-queue/auto-accept/run" not in lourd
    assert "def run_auto_accept" not in lourd
    assert sqlite3  # utilisé par les autres tests du module
