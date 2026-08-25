"""`/ingest/quality-scores` — le seul endroit où une mesure de cadrage atterrit.

Pourquoi la route existe, et pourquoi ce test la garde :

L'oracle de cadrage (Otsu `_probe_true_rim` + `measure_tilt`) travaille sur les
**raws**, et les raws sont en cache sur le Mac (~12 Go), pas au VPS. Le Mac a le
moteur et les images mais lit une réplique **read-only** ; le VPS écrit mais n'a
pas les images. Avant cette route, ce calcul n'avait littéralement aucune
destination — et le backfill portait un `guard_vps_only` qui l'envoyait sur la
seule machine incapable de le faire tourner. Le calcul reste où sont les images,
les LIGNES voyagent.

Ce que ce test verrouille :

1. l'applier est **SQL pur** — s'il importe `cv2`/`numpy`/`training`, le routeur
   entier est skippé au boot de l'image lean, en silence ;
2. **jamais de rétrogradation** : une mesure d'un `quality_pipeline_version`
   supérieur ou égal fait autorité ;
3. **`quality_reason` n'est jamais touchée** — elle porte des labels HUMAINS
   (`too_tilted` vient du banc, `rejected_in_review` d'un opérateur) ;
4. un asset inconnu est **refusé et nommé**, jamais écrit.
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
from store.quality import apply_ingest_quality_scores


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


def _row(aid="A1", *, version=1, score=0.92, tilt=3.5, axis=0.998, trust=1):
    p = {"asset_id": aid, "quality_pipeline_version": version}
    if score is not None:
        p["quality_score"] = score
    if tilt is not None:
        p["tilt_deg"] = tilt
        p["axis_ratio"] = axis
        p["tilt_trustworthy"] = trust
    return p


def _asset(conn, aid="A1"):
    return conn.execute("SELECT * FROM image_assets WHERE id=?", (aid,)).fetchone()


def test_l_applier_est_sql_pur():
    """Aucun import lourd — sinon l'image lean du VPS ne sert plus la route.

    La panne serait MUETTE : le routeur `ingest` entier serait skippé au boot
    pour avoir cohabité avec un `import cv2`. Piège documenté dans la skill
    `eurio-vps-deploy`, et déjà refermé pour `consensus_verdicts`.
    """
    import ast

    arbre = ast.parse((ML_DIR / "store/quality.py").read_text())
    importes: set[str] = set()
    for node in ast.walk(arbre):
        if isinstance(node, ast.Import):
            importes |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            importes.add(node.module)
    for mod in importes:
        assert mod.split(".")[0] not in {
            "review", "training", "numpy", "torch", "cv2", "PIL", "scripts", "vision",
        }, (f"store/quality.py importe {mod} — l'image lean ne l'a pas, et son "
            "routeur ENTIER serait skippé au boot, en silence")


def test_ecrit_les_cinq_colonnes_du_meme_payload(conn):
    assert apply_ingest_quality_scores(conn, [_row()]) == {
        "updated": 1, "skipped": 0, "missing": []}
    conn.commit()
    a = _asset(conn)
    assert (a["quality_score"], a["tilt_deg"], a["axis_ratio"],
            a["tilt_trustworthy"], a["quality_pipeline_version"]) == (
        0.92, 3.5, 0.998, 1, 1)


def test_rejouer_la_meme_version_ne_change_rien(conn):
    """Idempotence : la seconde passe SKIP, elle ne réécrit pas.

    C'est ce qui rend le backfill relançable sur 17 678 crops sans craindre
    qu'une interruption coûte un second passage complet.
    """
    apply_ingest_quality_scores(conn, [_row()])
    conn.commit()
    res = apply_ingest_quality_scores(conn, [_row(score=0.10, tilt=None)])
    conn.commit()
    assert res == {"updated": 0, "skipped": 1, "missing": []}
    assert _asset(conn)["quality_score"] == 0.92, "une même version ne se réécrit pas"


def test_ne_retrograde_jamais_une_mesure_plus_recente(conn):
    """Un pipeline v2 déjà passé ne se fait pas écraser par un v1 en retard.

    Sous Direction A le backfill tourne depuis une RÉPLIQUE : elle retarde par
    construction. Sans ce garde, une passe lancée sur une réplique périmée
    rétrograderait des mesures que le canonique avait déjà améliorées, et
    personne ne le verrait.
    """
    apply_ingest_quality_scores(conn, [_row(version=2, score=0.77, tilt=None)])
    conn.commit()
    res = apply_ingest_quality_scores(conn, [_row(version=1, score=0.11, tilt=None)])
    conn.commit()
    assert res == {"updated": 0, "skipped": 1, "missing": []}
    a = _asset(conn)
    assert (a["quality_score"], a["quality_pipeline_version"]) == (0.77, 2)


def test_n_ecrase_jamais_un_label_humain(conn):
    """`quality_reason` porte des labels HUMAINS — un oracle géométrique n'a pas
    qualité à les écraser.

    `too_tilted` vient du banc (un humain a regardé la pièce) ;
    `rejected_in_review` et `vision_standard_gate` sont des états de review.
    Les 1 352 `rejected_in_review` de la base sont des décisions, pas des
    mesures.
    """
    conn.execute("UPDATE image_assets SET quality_reason='too_tilted' WHERE id='A1'")
    conn.commit()
    apply_ingest_quality_scores(conn, [_row()])
    conn.commit()
    assert _asset(conn)["quality_reason"] == "too_tilted"

    # …et la colonne n'est nommée dans AUCUNE chaîne exécutable du module : ni
    # dans `_MEASURE_COLUMNS`, ni dans un SQL. On lit l'ARBRE, pas le texte —
    # le module PARLE de `quality_reason` dans sa docstring, et c'est exactement
    # ce qu'il doit faire. Un détecteur qui crie sur un commentaire apprend à
    # être ignoré, et c'est comme ça qu'une vraie écriture finit par passer.
    import ast

    arbre = ast.parse((ML_DIR / "store/quality.py").read_text())
    litteraux = [
        n.value for n in ast.walk(arbre)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and n is not arbre.body[0].value  # la docstring de module
    ]
    docstrings = {
        n.body[0].value.value for n in ast.walk(arbre)
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
        and isinstance(n.body[0].value.value, str)
    }
    for lit in litteraux:
        if lit in docstrings:
            continue
        assert "quality_reason" not in lit, (
            "quality_reason apparaît dans une chaîne EXÉCUTABLE de l'applier — "
            "elle ne doit vivre que dans les docstrings qui expliquent pourquoi "
            "on n'y touche pas")


def test_un_champ_absent_n_ecrase_pas_par_un_null(conn):
    """L'oracle est muet sur ~35 % des crops : il rend un payload SANS
    `quality_score`. Ce silence ne doit pas effacer une mesure existante."""
    apply_ingest_quality_scores(conn, [_row(version=1)])
    conn.commit()
    apply_ingest_quality_scores(
        conn, [{"asset_id": "A1", "quality_pipeline_version": 2}])
    conn.commit()
    a = _asset(conn)
    assert a["quality_score"] == 0.92, "un champ absent n'est pas un NULL à écrire"
    assert a["tilt_deg"] == 3.5
    assert a["quality_pipeline_version"] == 2, (
        "la version est posée même sans mesure : elle dit « examiné par vN », "
        "sinon les 35 % muets sont re-téléchargés à chaque passage")


def test_un_asset_inconnu_est_refuse_et_nomme(conn):
    res = apply_ingest_quality_scores(conn, [_row(), _row(aid="FANTOME")])
    conn.commit()
    assert res == {"updated": 1, "skipped": 0, "missing": ["FANTOME"]}
    assert _asset(conn, "FANTOME") is None


def test_l_ecriture_est_journalisee(conn):
    """Une colonne qui bouge sans event est une mutation qu'on ne saura pas
    expliquer trois mois plus tard."""
    apply_ingest_quality_scores(conn, [_row()])
    conn.commit()
    ev = conn.execute(
        "SELECT reason, actor, detail_json FROM image_state_events "
        "WHERE asset_id='A1' ORDER BY id DESC LIMIT 1").fetchone()
    assert ev["reason"] == "quality_ingest"
    assert ev["actor"] == "pipeline"
    assert "image_assets.quality_score" in ev["detail_json"]


def test_la_route_est_montee_sur_le_lean():
    """Elle DOIT être servie par le VPS : c'est lui, le writer canonique."""
    from serving import ingest_routes

    assert "/ingest/quality-scores" in {r.path for r in ingest_routes.router.routes}
    serve = (ML_DIR / "serving/server_serve.py").read_text()
    assert "ingest_routes" in serve or "ingest_router" in serve


def test_le_client_ne_pousse_pas_une_liste_vide(monkeypatch):
    """Pas d'appel réseau pour rien — et surtout pas de faux « poussé »."""
    from client import ingest

    monkeypatch.setenv("EURIO_API_URL", "https://exemple.test")
    assert ingest.push_quality_scores([]) is None


def test_le_backfill_ne_porte_plus_de_garde_vps_only():
    """Le garde existait parce qu'AUCUNE route ne transportait cette écriture.

    Maintenant qu'elle existe, il protégerait d'un danger disparu — et il
    envoyait le calcul sur la seule machine qui n'a pas les images. C'est le
    motif `train_embedder.py:53` : un garde décoratif qu'on contourne par
    réflexe, jusqu'au jour où il gardait quelque chose.
    """
    source = (ML_DIR / "scripts/backfill_quality_score.py").read_text()
    code = source.split('"""', 2)[2]
    assert "guard_vps_only" not in code
    assert "i-know-this-is-canonical" not in code
    assert "push_quality_scores" in code, "…et il pousse par la route"


def test_le_diag_ne_porte_plus_de_plafond_en_dur():
    """`_MAX_SAMPLE = 2274` était « tout le parc » au 5 juin 2026. C'est cette
    constante, et elle seule, qui a gelé la couverture de `quality_score` à
    5,6 % pendant que le parc quadruplait."""
    source = (ML_DIR / "scripts/crop_quality_diag.py").read_text()
    assert "_MAX_SAMPLE" not in source
    assert "_DEFAULT_LIMIT: int | None = None" in source


def test_le_diag_passe_par_local_path():
    """Un crop absent du cache était SILENCIEUSEMENT sauté au lieu d'être
    téléchargé, et le bucket était reconstruit à la main alors qu'il se dérive
    (`bucket_for_asset`). `storage_path` est la CLÉ S3, pas un chemin."""
    import ast

    arbre = ast.parse((ML_DIR / "scripts/crop_quality_diag.py").read_text())
    fns = {n.name: ast.unparse(n) for n in ast.walk(arbre)
           if isinstance(n, ast.FunctionDef)}
    for nom in ("_crop_local_path", "_raw_local_path"):
        assert "local_path(" in fns[nom], f"{nom} ne passe pas par local_path"
        assert "_CACHE" not in fns[nom], f"{nom} reconstruit encore le chemin de cache"
    assert "bucket_for_asset" in fns["_crop_local_path"]
    assert "bucket_for_source_image" in fns["_raw_local_path"]
