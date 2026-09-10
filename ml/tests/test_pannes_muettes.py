"""Trois pannes muettes du catalogue de `.claude/skills/eurio-verify/SKILL.md`
ont maintenant un test qui crie (chantier de-la-base-a-la-nef, étape 2, 2.4).

Chaque test nomme dans son docstring la panne visée et la MUTATION exacte
(fichier, ligne, changement) qui doit le faire rougir. La règle de la skill :
un test qui ne peut pas échouer ne prouve rien — les trois mutations ont été
jouées à la main le 2026-09-10 (rouge vérifié, revert vérifié), les trois
sorties rouges sont dans le rapport de l'exécutant de l'étape 2
(`docs/work-in-progress/de-la-base-a-la-nef/SUIVI.md`).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from store import Store


def _seed_coin(conn: sqlite3.Connection, eurio_id: str, numista_id: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO coins (eurio_id, country, country_name, year, "
        "face_value, is_commemorative, numista_id, raw_payload_json) "
        "VALUES (?, 'XX', 'XX', 2016, 2.0, 1, ?, '{}')",
        (eurio_id, numista_id),
    )


# ─── 1. « Un DB_PATH littéral : une base périmée répond normalement » ────────


def test_le_mapping_numista_lit_la_base_injectee_pas_le_chemin_ambiant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Panne visée (catalogue eurio-verify) : « Banque d'ancres 30 % trop
    petite pendant des semaines, aucun log — un `DB_PATH` littéral : le script
    lisait `eurio.db` au lieu de la réplique. Une base périmée répond
    normalement. » La même famille a fait passer 5 tests de `test_lab_api.py`
    pendant des mois sur un `eurio.db` hors dépôt (run CI 34493861491).

    Deux bases qui répondent toutes les deux, avec des valeurs différentes :
    l'ambiante (`EURIO_DB_PATH`, celle que résout un chemin de module) et
    l'injectée (`lab_routes.bind`). Le mapping doit rendre la valeur de
    l'injectée. Si le chemin de module gagne, la réponse est plausible, sans
    erreur, et fausse.

    Mutation qui doit rougir : `ml/serving/lab_routes.py`, dans `bind()`,
    supprimer la ligne `coin_lookup.bind(store.db_path)` (ou, équivalent,
    dans `ml/serving/coin_lookup.py::_db_path` rendre
    `resolve_db_path(_DEFAULT_DB)` sans regarder `_bound_db_path`).
    """
    from serving import coin_lookup
    import serving.lab_routes as lr

    ambiant = Store(tmp_path / "ambiant.db")
    with ambiant._writing() as conn:  # noqa: SLF001
        _seed_coin(conn, "xx-2016-a", 111)
    monkeypatch.setenv("EURIO_DB_PATH", str(tmp_path / "ambiant.db"))
    # Un état de cache hérité d'un autre test ne doit pas décider ici.
    monkeypatch.setattr(coin_lookup, "_bound_db_path", None)
    monkeypatch.setattr(coin_lookup, "_loaded", False)
    assert coin_lookup.numista_id_for("xx-2016-a") == 111, (
        "sans bind, le repli doit lire EURIO_DB_PATH — sinon le test ne compare rien"
    )

    injectee = Store(tmp_path / "injectee.db")
    with injectee._writing() as conn:  # noqa: SLF001
        _seed_coin(conn, "xx-2016-a", 222)
    lr.bind(injectee, runner=None)  # type: ignore[arg-type]

    assert coin_lookup.numista_id_for("xx-2016-a") == 222, (
        "le mapping a lu la base ambiante (111) et non celle que la route a "
        "reçue par bind() (222) : une base périmée répond normalement"
    )


# ─── 2. « immutable=1 ignore le -wal, sans un mot » ──────────────────────────


def test_un_lecteur_mode_ro_voit_les_lignes_encore_dans_le_wal(tmp_path: Path) -> None:
    """Panne visée (catalogue eurio-verify, fiche WAL, piège B) : « Un
    instantané périmé, `exit=0`, sans un mot — `immutable=1` ignore le `-wal` :
    dès qu'un écrivain tourne, il rend le contenu du fichier principal seul. »
    La règle : `immutable=1` au repos, `mode=ro` sinon. Les lecteurs des
    routes (`scrape_plan_routes.connect_ro`) doivent lire le `-wal`, parce
    qu'un écrivain (`:8042`, un job) tourne pendant qu'ils lisent.

    Un écrivain reste ouvert, checkpoint automatique coupé : ses lignes
    commitées sont dans le `-wal`, pas dans le `.db`. Le lecteur de la route
    doit les compter toutes.

    Mutation qui doit rougir : `ml/serving/scrape_plan_routes.py`, dans
    `connect_ro`, remplacer `f"file:{db_path}?mode=ro"` par
    `f"file:{db_path}?immutable=1"`.
    """
    from serving.scrape_plan_routes import connect_ro

    db = tmp_path / "wal.db"
    writer = sqlite3.connect(str(db))
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE x (i INTEGER)")
        writer.executemany("INSERT INTO x VALUES (?)", [(1,), (2,), (3,), (4,), (5,)])
        writer.commit()
        assert (tmp_path / "wal.db-wal").stat().st_size > 0, (
            "le montage du test est faux : rien n'est resté dans le -wal"
        )

        reader = connect_ro(db)
        try:
            n = reader.execute("SELECT COUNT(*) FROM x").fetchone()[0]
        finally:
            reader.close()
        assert n == 5, f"le lecteur rend {n} lignes sur 5 : il ignore le -wal"
    finally:
        writer.close()


# ─── 3. « Un seuil entier stocké en REAL, accepté fractionnaire » ────────────


def test_un_seuil_entier_fractionnaire_est_refuse_par_la_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Panne visée (catalogue eurio-verify, S1) : « Un seuil "réglé",
    `source='db'`, et un comportement de seuil désarmé — la valeur est un
    COMPTE relu en `int()` : `min_exemplars = 1,9` franchissait les bornes
    [0, 50] et posait un plancher effectif de 1. Un seuil entier stocké en
    REAL doit être refusé fractionnaire à l'écriture. » Et la ligne d'à côté :
    « un garde posé, testé, muté — et jamais appelé : il gardait le CLI ; le
    chemin réel était la route HTTP. » Le test passe donc par la route,
    `PUT /lab/dino-thresholds`, pas par `store.dino_thresholds` en direct.

    Mutation qui doit rougir : `ml/store/dino_thresholds.py`, dans
    `set_threshold`, la ligne `if key in CLES_ENTIERES and value != int(value):`
    devient `if False:`.
    """
    from serving import dino_thresholds_routes
    from serving.auth_principal import Principal, require_principal
    from serving.deps import db_connection

    conn = Store(tmp_path / "t.db")._connection()  # noqa: SLF001

    app = FastAPI()
    app.include_router(dino_thresholds_routes.router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="t", email="t@test.local", roles=["owner"],
        scopes={"lab:read", "training:run"}, auth_method="api_token",
    )
    app.dependency_overrides[db_connection] = lambda: conn
    client = TestClient(app)

    couple = {"anchors_kind": "2eur_all", "encoder_version": "dinov2-vitl14"}
    r = client.put(
        "/lab/dino-thresholds",
        json={**couple, "key": "min_exemplars", "value": 1.9, "note": "S1"},
    )
    assert r.status_code == 400, (
        f"la route a accepté min_exemplars = 1.9 ({r.status_code}) : le plancher "
        f"effectif serait int(1.9) = 1, avec source='db' pour caution — {r.text}"
    )

    rows = conn.execute(
        "SELECT value FROM dino_thresholds WHERE key = 'min_exemplars'"
    ).fetchall()
    assert rows == [], f"un seuil fractionnaire a été écrit : {[r[0] for r in rows]}"

    state = client.get("/lab/dino-thresholds", params=couple)
    assert state.status_code == 200, state.text
    effective = state.json()["effective"]
    assert effective["source"]["min_exemplars"] != "db", effective["source"]
    assert effective["values"]["min_exemplars"] == int(effective["values"]["min_exemplars"])
