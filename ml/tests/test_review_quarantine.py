"""Quarantaine des décisions d'ami + signature du décideur (lots 2 et 3).

review-collaborative-v2 : un principal SANS le scope ``review:arbitrate`` voit ses
décisions atterrir dans ``peer_review_decisions`` en ``pending`` au lieu d'écrire le
canonique — c'est ce qui permet d'ouvrir la review à des amis sans leur donner un
accès direct au jeu d'entraînement.

La clé est un SCOPE et non un rôle : les scopes effectifs valant ``jeton ∩ rôles``, un
PAT restreint rejoue l'expérience d'un ami depuis un compte owner (DECISIONS.md D7).
Ces tests exercent exactement ça — même principal, deux jeux de scopes.

On vérifie aussi que ``decided_by`` porte enfin l'identité du décideur : il valait le
littéral ``'admin'`` pour 3 809 lignes, ce qui rendait « qui a validé quoi »
impossible à répondre.
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from store import Store
from test_review_requalify import _seed_listing

_USER = "u_paolo"
_REVIEWER_SCOPES = ("coins:read", "review:read", "review:write", "lab:read")
_ARBITER_SCOPES = (*_REVIEWER_SCOPES, "review:arbitrate")
_DECISION = {"eurio_id": "fr-2015-2eur-paix", "face": "obverse", "notes": "n"}


def _principal(scopes):
    return Principal(
        user_id=_USER, email="paolo@test.local", roles=["reviewer"],
        scopes=set(scopes), auth_method="api_token",
    )


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    """(conn, make_client) — `make_client(scopes)` monte le router lean avec
    ces scopes-là, sur la même base tmp."""
    from serving.review_queue import writes

    db = tmp_path / "t.db"
    conn = Store(db)._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    # `peer_review_decisions` est dans state/schema.sql ; `users` NON — il vient
    # de la migration 0001. On ne rejoue pas toute la chaîne de migrations sur une
    # base neuve (elles supposent l'état d'AVANT schema.sql : 0004 rajoute un
    # `run_id` que schema.sql pose déjà) : on prend juste la table utile.
    conn.executescript(
        (ML_DIR / "serving/migrations/0001_auth_redesign.sql").read_text()
    )
    # 0012 : l'index unique partiel qui garantit UNE seule décision pendante par
    # crop. Sans lui la course passe et le test ci-dessous ne prouverait rien.
    conn.executescript(
        (ML_DIR / "serving/migrations/0012_peer_review_une_seule_decision_pendante.sql")
        .read_text()
    )
    conn.execute(
        "INSERT INTO users (id, email, name, active, created_at) "
        "VALUES (?, ?, ?, 1, 0)",
        (_USER, "paolo@test.local", "Paolo"),
    )
    conn.commit()

    def make_client(scopes):
        app = FastAPI()
        app.include_router(writes.router)
        app.dependency_overrides[require_principal] = lambda: _principal(scopes)
        return TestClient(app)

    return conn, make_client


def _canonical(conn, review_id: str):
    return conn.execute(
        "SELECT rq.status, rq.decided_by, a.training_eligible, a.resolution_status "
        "  FROM review_queue rq JOIN image_assets a ON a.id = rq.image_asset_id "
        " WHERE rq.id = ?",
        (review_id,),
    ).fetchone()


def _open_ids_call(repository, conn):
    """`list_queue` a une signature à rallonge (tri, pêche, cohorte…) : ici on ne
    veut que la file brute — les valeurs neutres, rien d'autre."""
    return repository.list_queue(
        conn, status="open", limit=50, order="priority", kind="all",
        lane=None, cohort_id=None, eurio_id=None, review_ids=None,
    )


def _pending(conn):
    return conn.execute(
        "SELECT * FROM peer_review_decisions WHERE arbitration_status = 'pending'"
    ).fetchall()


# ─── Lot 3 : la quarantaine ─────────────────────────────────────────────────


def test_ami_decide_ne_touche_pas_au_canonique(rig):
    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="Q1")

    r = make_client(_REVIEWER_SCOPES).post(f"/review-queue/{rid}/decide", json=_DECISION)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_arbitration"

    row = _canonical(conn, rid)
    assert row["status"] == "open", "la file ne doit pas être tranchée"
    assert row["decided_by"] is None
    assert row["training_eligible"] == 0, "rien n'entre en training sans arbitrage"
    assert row["resolution_status"] == "needs_review"


def test_ami_decide_enregistre_la_decision_signee(rig):
    conn, make_client = rig
    _, [aid], [rid] = _seed_listing(conn, item_id="Q2")

    make_client(_REVIEWER_SCOPES).post(f"/review-queue/{rid}/decide", json=_DECISION)

    rows = _pending(conn)
    assert len(rows) == 1
    d = rows[0]
    assert d["image_asset_id"] == aid
    assert d["review_item_id"] == rid, "sans lui, l'arbitrage ne saura pas quoi clore"
    assert d["reviewer_token"] == _USER
    assert d["reviewer_name"] == "Paolo", "le libellé vient de users.name"
    assert d["action"] == "accept"
    assert d["decided_eurio_id"] == _DECISION["eurio_id"]
    assert d["decided_face"] == "obverse"


def test_ami_reject_part_aussi_en_quarantaine(rig):
    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="Q3")

    r = make_client(_REVIEWER_SCOPES).post(
        f"/review-queue/{rid}/reject", json={"reason": "not_a_coin"})
    assert r.status_code == 200
    assert r.json()["status"] == "pending_arbitration"

    assert _canonical(conn, rid)["status"] == "open"
    d = _pending(conn)[0]
    assert d["action"] == "reject"
    assert d["quality_reason"] == "not_a_coin"


def test_deuxieme_decision_sur_un_crop_en_quarantaine_est_refusee(rig):
    """Sinon deux amis tranchent le même crop et le second travaille pour rien."""
    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="Q4")
    client = make_client(_REVIEWER_SCOPES)

    assert client.post(f"/review-queue/{rid}/decide", json=_DECISION).status_code == 200
    r2 = client.post(f"/review-queue/{rid}/decide", json=_DECISION)
    assert r2.status_code == 409
    assert len(_pending(conn)) == 1


def test_skip_n_est_pas_mis_en_quarantaine(rig):
    """Différer est réversible et n'engage rien — inutile de le faire arbitrer."""
    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="Q5")

    r = make_client(_REVIEWER_SCOPES).post(f"/review-queue/{rid}/skip")
    assert r.status_code == 200
    assert r.json()["status"] == "skipped"
    assert _pending(conn) == []


def test_restore_est_reserve_a_l_arbitre(rig):
    """Défaire une décision est un geste d'arbitre, pas de reviewer."""
    conn, make_client = rig
    assert make_client(_REVIEWER_SCOPES).post(
        "/review-queue/restore", json={"review_ids": []}).status_code == 403
    assert make_client(_ARBITER_SCOPES).post(
        "/review-queue/restore", json={"review_ids": []}).status_code == 200


def test_la_course_sur_la_quarantaine_est_barree_en_base(rig):
    """La garde lue (`_pending_peer_decision`) laisse passer deux reviewers servis
    le même crop en même temps. Sans l'index unique, les deux lignes entrent
    `pending` et l'arbitrage en marque une `superseded` : le travail de quelqu'un
    disparaît SANS ERREUR. On simule la course en court-circuitant la lecture."""
    import sqlite3 as _sqlite3

    from serving.review_queue import writes

    conn, make_client = rig
    _, [aid], [rid] = _seed_listing(conn, item_id="R1")
    make_client(_REVIEWER_SCOPES).post(f"/review-queue/{rid}/decide", json=_DECISION)
    assert len(_pending(conn)) == 1

    with pytest.raises(_sqlite3.IntegrityError):
        writes._insert_quarantine(  # noqa: SLF001
            conn, _principal(_REVIEWER_SCOPES), review_id=rid, asset_id=aid,
            action="accept", decided_eurio_id="fr-2015-2eur-paix",
            decided_face="obverse", decided_variant_kind=None,
            quality_reason=None, notes=None, now_iso="2026-01-01T00:00:00Z",
        )
    conn.rollback()
    assert len(_pending(conn)) == 1, "une seule décision pendante, toujours"


def test_l_historique_garde_plusieurs_decisions_par_crop(rig):
    """L'index est PARTIEL : seul `pending` est contraint. La trace de qui a
    proposé quoi ne doit pas être bridée."""
    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="R2")
    client = make_client(_REVIEWER_SCOPES)
    client.post(f"/review-queue/{rid}/decide", json=_DECISION)
    conn.execute("UPDATE peer_review_decisions SET arbitration_status = 'rejected'")
    conn.commit()
    # Le crop est revenu dans la file : une seconde décision doit passer.
    assert client.post(f"/review-queue/{rid}/decide", json=_DECISION).status_code == 200
    assert conn.execute(
        "SELECT count(*) c FROM peer_review_decisions").fetchone()["c"] == 2


def test_un_identifiant_perime_est_refuse_pas_detourne(rig):
    """Un owner/admin dont le jeton précède `review:arbitrate` ne doit PAS voir
    ses décisions partir en quarantaine : le front jette le corps de la réponse,
    il reviewrait une session entière en croyant chaque item confirmé, et rien
    n'atteindrait le canonique. Un 409 est visible tout de suite."""
    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="P1")

    def perime():
        return Principal(
            user_id=_USER, email="paolo@test.local",
            roles=["owner", "admin", "reviewer"],   # le rôle est là…
            scopes=set(_REVIEWER_SCOPES),           # …le scope n'y est pas
            # COOKIE : ses scopes sont dérivés des rôles au login, il ne peut pas
            # être volontairement restreint — donc il est périmé, sans ambiguïté.
            auth_method="oidc",
        )

    from fastapi import FastAPI
    from serving.review_queue import writes

    app = FastAPI()
    app.include_router(writes.router)
    app.dependency_overrides[require_principal] = perime
    r = TestClient(app).post(f"/review-queue/{rid}/decide", json=_DECISION)

    assert r.status_code == 409
    assert "périmée" in r.json()["detail"]
    assert _pending(conn) == [], "surtout : RIEN n'a été enregistré en quarantaine"
    assert _canonical(conn, rid)["status"] == "open"


def test_un_pat_restreint_reste_utilisable_pour_jouer_l_ami(rig):
    """L'inverse du test précédent, et il compte autant : un PAT se restreint
    DÉLIBÉRÉMENT (scopes effectifs = jeton ∩ rôles). C'est le mécanisme qui permet
    de rejouer l'expérience d'un ami depuis un compte owner sans créer de compte
    Authentik (DECISIONS D7). Refuser sur le rôle seul l'aurait tué — et ne
    distinguait de toute façon pas un jeton périmé d'un jeton restreint."""
    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="P2")

    def owner_restreint():
        return Principal(
            user_id=_USER, email="paolo@test.local",
            roles=["owner", "admin", "reviewer"],
            scopes=set(_REVIEWER_SCOPES),
            auth_method="api_token",   # PAT : restriction volontaire
        )

    from fastapi import FastAPI
    from serving.review_queue import writes

    app = FastAPI()
    app.include_router(writes.router)
    app.dependency_overrides[require_principal] = owner_restreint
    r = TestClient(app).post(f"/review-queue/{rid}/decide", json=_DECISION)

    assert r.status_code == 200
    assert r.json()["status"] == "pending_arbitration"
    assert len(_pending(conn)) == 1


def test_les_compteurs_suivent_la_file(rig):
    """Un compteur qui annonce 4 au-dessus d'une file qui en sert 3 n'est pas une
    imprécision : c'est un écran qui a l'air cassé, sans message d'erreur."""
    from serving.review_queue import repository

    conn, make_client = rig
    _, _, [rid_a] = _seed_listing(conn, item_id="C1")
    _seed_listing(conn, item_id="C2")

    def servis():
        return len(_open_ids_call(repository, conn))

    def annonces():
        return repository.queue_stats(conn).n_pending

    assert servis() == annonces() == 2
    make_client(_REVIEWER_SCOPES).post(f"/review-queue/{rid_a}/decide", json=_DECISION)
    assert servis() == 1
    assert annonces() == 1, "le bandeau doit compter comme la file"


# ─── Lot 2 : la signature ───────────────────────────────────────────────────


def test_arbitre_ecrit_le_canonique_et_le_signe(rig):
    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="A1")

    r = make_client(_ARBITER_SCOPES).post(f"/review-queue/{rid}/decide", json=_DECISION)
    assert r.status_code == 200
    assert r.json()["status"] == "done"

    row = _canonical(conn, rid)
    assert row["status"] == "done"
    assert row["decided_by"] == _USER, "plus jamais le littéral 'admin'"
    assert row["training_eligible"] == 1
    assert _pending(conn) == [], "un arbitre ne passe pas par la quarantaine"


def test_arbitre_reject_est_signe(rig):
    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="A2")

    make_client(_ARBITER_SCOPES).post(
        f"/review-queue/{rid}/reject", json={"reason": "too_low_quality"})

    row = _canonical(conn, rid)
    assert row["decided_by"] == _USER
    assert row["resolution_status"] == "rejected"


def test_qui_a_valide_quoi_se_joint_a_users(rig):
    """L'intérêt de la signature : la question devient une jointure."""
    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="A3")
    make_client(_ARBITER_SCOPES).post(f"/review-queue/{rid}/decide", json=_DECISION)

    rows = conn.execute(
        "SELECT u.name, count(*) AS n FROM review_queue rq "
        "  JOIN users u ON u.id = rq.decided_by GROUP BY 1"
    ).fetchall()
    assert [(r["name"], r["n"]) for r in rows] == [("Paolo", 1)]


# ─── La file ────────────────────────────────────────────────────────────────


def test_la_file_exclut_les_crops_en_quarantaine(rig):
    """`review_queue` reste `open` — c'est la LECTURE qui doit les écarter, sans
    quoi l'ami retomberait sur son propre crop au tour suivant."""
    from serving.review_queue import repository

    conn, make_client = rig
    _, _, [rid_a] = _seed_listing(conn, item_id="F1")
    _, _, [rid_b] = _seed_listing(conn, item_id="F2")

    def ids():
        return {i.id for i in _open_ids_call(repository, conn)}

    assert {rid_a, rid_b} <= ids()
    make_client(_REVIEWER_SCOPES).post(f"/review-queue/{rid_a}/decide", json=_DECISION)
    after = ids()
    assert rid_a not in after, "le crop en quarantaine ne doit plus être servi"
    assert rid_b in after, "les autres ne bougent pas"


def test_une_decision_arbitree_rend_le_crop_a_la_file(rig):
    """Un arbitrage qui REJETTE la décision sort la ligne de `pending` : le crop
    redevient disponible tout seul, sans réécriture."""
    from serving.review_queue import repository

    conn, make_client = rig
    _, _, [rid] = _seed_listing(conn, item_id="F3")
    make_client(_REVIEWER_SCOPES).post(f"/review-queue/{rid}/decide", json=_DECISION)
    assert rid not in {i.id for i in _open_ids_call(repository, conn)}

    conn.execute(
        "UPDATE peer_review_decisions SET arbitration_status = 'rejected' "
        " WHERE review_item_id = ?", (rid,))
    conn.commit()
    assert rid in {i.id for i in _open_ids_call(repository, conn)}
