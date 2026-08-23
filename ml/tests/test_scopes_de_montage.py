"""Scopes de montage du serve-role (review-collaborative-v2, lot 4b).

Les routers de `_CANDIDATES` étaient montés avec `require_principal` — *tout
principal authentifié*, sans scope. Le filtrage de nav du lot 4 cachait les pages
à un ami en rôle `reviewer` ; il pouvait encore les appeler à la main.

Le trou le plus grave était ouvert par la quarantaine elle-même : `reviewer` a
`review:write`, et `peer_arbitration` exigeait `review:write` — un ami pouvait
donc approuver SA PROPRE décision en quarantaine et la pousser dans le canonique.
Vérifié en conditions réelles le 2026-08-23 avant correctif (200, puis
`arbitration_status: approved`).

Ces tests portent sur la DÉPENDANCE DE MONTAGE, pas sur les routes une à une :
c'est elle qui décide, et c'est elle qu'un ajout de router pourrait contourner.
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import (
    ROLE_SCOPES,
    Principal,
    require_principal,
    require_scope_by_method,
)


def _principal(role: str) -> Principal:
    return Principal(
        user_id="u", email="u@test.local", roles=[role],
        scopes=set(ROLE_SCOPES[role]), auth_method="api_token",
    )


def _client(read_scope: str, write_scope: str, role: str) -> TestClient:
    app = FastAPI()
    dep = require_scope_by_method(read_scope, write_scope)

    @app.get("/x", dependencies=[Depends(dep)])
    def _get() -> dict:
        return {"ok": True}

    @app.post("/x", dependencies=[Depends(dep)])
    def _post() -> dict:
        return {"ok": True}

    @app.patch("/x", dependencies=[Depends(dep)])
    def _patch() -> dict:
        return {"ok": True}

    @app.delete("/x", dependencies=[Depends(dep)])
    def _delete() -> dict:
        return {"ok": True}

    app.dependency_overrides[require_principal] = lambda: _principal(role)
    return TestClient(app)


# ─── La dépendance elle-même ────────────────────────────────────────────────


def test_le_verbe_choisit_le_scope():
    c = _client("coins:read", "coins:write", "reviewer")   # a read, pas write
    assert c.get("/x").status_code == 200
    for appel in (c.post, c.patch, c.delete):
        r = appel("/x")
        assert r.status_code == 403, f"{appel.__name__} devrait exiger l'écriture"
        assert r.json()["detail"] == "missing scope: coins:write"


def test_l_arbitre_passe_partout_sur_ce_couple():
    c = _client("coins:read", "coins:write", "owner")
    assert c.get("/x").status_code == 200
    assert c.post("/x").status_code == 200


def test_sans_le_scope_de_lecture_meme_le_get_est_refuse():
    c = _client("training:run", "training:run", "reviewer")
    assert c.get("/x").status_code == 403


# ─── La table de montage ────────────────────────────────────────────────────


def _router_scopes() -> dict[str, tuple[str, str]]:
    from serving.router_scopes import ROUTER_SCOPES

    return ROUTER_SCOPES


def test_un_reviewer_ne_peut_pas_arbitrer():
    """LE trou du lot 3. `reviewer` a `review:write` : tant que l'arbitrage
    l'exigeait, un ami approuvait sa propre décision et la quarantaine ne servait
    à rien."""
    read_scope, write_scope = _router_scopes()["peer_arbitration"]
    reviewer = ROLE_SCOPES["reviewer"]

    assert write_scope == "review:arbitrate"
    assert write_scope not in reviewer, "un ami ne doit PAS pouvoir arbitrer"
    assert read_scope in reviewer, "mais il peut voir où en sont ses décisions"
    for role in ("owner", "admin"):
        assert write_scope in ROLE_SCOPES[role], f"{role} doit pouvoir arbitrer"


def test_un_reviewer_ne_peut_ecrire_dans_aucun_router_monte():
    """Le filtrage de nav est du confort ; ceci est la garde."""
    reviewer = ROLE_SCOPES["reviewer"]
    ecrivables = {
        name: w for name, (_r, w) in _router_scopes().items() if w in reviewer
    }
    assert ecrivables == {"review_queue": "review:write"}, (
        "seule la file de review est écrivable par un ami — et ses écritures "
        f"partent en quarantaine (lot 3). Trouvé : {ecrivables}"
    )


def test_un_reviewer_garde_les_lectures_dont_son_travail_depend():
    """Trancher un crop suppose de CHERCHER la bonne pièce : couper `coins:read`
    casserait la recherche libre, c'est-à-dire le geste qui suit « DINO s'est
    trompé »."""
    reviewer = ROLE_SCOPES["reviewer"]
    scopes = _router_scopes()
    for router in ("coins", "coin_assets", "referential", "review_queue"):
        assert scopes[router][0] in reviewer, f"{router} doit rester lisible"
    assert scopes["operations"][0] not in reviewer, (
        "Operations est caché dans la nav : le serveur doit dire la même chose"
    )


def test_tout_router_monte_declare_ses_scopes():
    """Pas de défaut permissif : un router ajouté sans couple fait échouer le
    boot, au lieu de rouvrir le trou en silence."""
    import ast

    src = (ML_DIR / "serving/server_serve.py").read_text()
    tree = ast.parse(src)
    candidates: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(tgt, "id", None) == "_CANDIDATES" for tgt in node.targets
        ):
            candidates = [elt.elts[0].value for elt in node.value.elts]
    assert candidates, "_CANDIDATES introuvable dans server_serve.py"

    scopes = _router_scopes()
    manquants = [name for name in candidates if name not in scopes]
    assert not manquants, f"routers sans scopes déclarés : {manquants}"


def test_aucun_scope_declare_n_est_inventé():
    """Un scope mal orthographié ne refuserait pas : il n'appartiendrait à aucun
    rôle, donc la route deviendrait inatteignable — panne muette à l'envers."""
    connus = set().union(*ROLE_SCOPES.values())
    for name, (r, w) in _router_scopes().items():
        assert r in connus, f"{name} : scope de lecture inconnu '{r}'"
        assert w in connus, f"{name} : scope d'écriture inconnu '{w}'"
