"""Les écritures de l'entonnoir exigent `review:arbitrate`, pas `review:write`.

CE QUE CE TEST GARDE, ET COMMENT LE TROU A ÉTÉ TROUVÉ
-----------------------------------------------------
`serving/funnel_writes.py` écrit le canonique EN DIRECT : `decide_lot` clôt des
items et pose `training_eligible = 1`, `/lab/assets/{id}/training-eligible` le
pose sur n'importe quel asset. Ces routes ont été écrites pour l'entonnoir (C2a,
Direction A) **avant** la quarantaine du lot 3, et personne n'est repassé dessus
quand elle est arrivée : le mot `arbitrate` n'apparaissait pas une fois dans le
fichier, et la garde valait `review:write` — le scope de TOUT ami (D7).

D7 était donc contournable, et pas seulement en théorie : le sélecteur
« unité / lot » de la pêche, l'écran où un ami travaille, n'était gaté par rien.
Mesuré en conditions réelles le 2026-08-24, jeton de reviewer, API lean :

    POST /review-queue/lots/{lot}/decide      → 200 {"done":1}
      review_queue.status         open → done
      image_assets.training_eligible  0 → 1
      decided_by                  = 'admin'   (la traçabilité ment)
      peer_review_decisions       18 → 18     (AUCUNE quarantaine)

    POST /lab/assets/{id}/training-eligible   → 200, 0 → 1, sans quarantaine

⛔ POURQUOI CE TEST PORTE SUR LA POLITIQUE ET NON SUR UN 403 DE BOUT EN BOUT
---------------------------------------------------------------------------
La garde de ce router est un `Depends` de MODULE (`PrincipalDep`), pas une
dépendance de montage. Un test qui monterait le router avec un principal forgé
exercerait bien la garde — mais il passerait aussi au vert si quelqu'un
remplaçait le `Depends` par un autre scope tout en gardant le nom. On vérifie
donc les deux : le scope déclaré, et le refus effectif.

⛔ NE PAS REMETTRE `review:write` sans avoir posé la quarantaine dans
`decide_lot`. Ces routes n'ont pas de jumeau gardé ailleurs : ce `Depends` est
la seule chose qui les sépare du canonique.
"""
from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving import funnel_writes
from serving.auth_principal import Principal, require_principal

#: Les scopes d'un ami, tels que `ROLE_SCOPES['reviewer']` les donne.
AMI = ("coins:read", "review:read", "review:write", "lab:read")
ARBITRE = (*AMI, "review:arbitrate")


def _client(scopes) -> TestClient:
    app = FastAPI()
    app.include_router(funnel_writes.router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="u", email="u@test.local", roles=["reviewer"],
        scopes=set(scopes), auth_method="api_token",
    )
    return TestClient(app)


def test_le_scope_declare_est_bien_arbitrate():
    """Le scope, lu à la source. Un `review:write` qui reviendrait ici rouvrirait
    D7 en grand, et rien d'autre ne l'attraperait."""
    src = (ML_DIR / "serving" / "funnel_writes.py").read_text(encoding="utf-8")
    assert 'require_scope("review:arbitrate")' in src
    assert 'require_scope("review:write")' not in src, (
        "une écriture de l'entonnoir gardée par `review:write` est atteignable "
        "par tout ami — c'est le contournement de D7 mesuré le 2026-08-24"
    )


@pytest.mark.parametrize(
    ("methode", "chemin", "corps"),
    [
        ("post", "/review-queue/lots/ebay_x/decide", {"assignments": []}),
        ("post", "/lab/assets/a1/training-eligible", {"eligible": True}),
        ("post", "/lab/assets/a1/accept-training", {}),
        ("post", "/lab/assets/a1/reopen-review", {}),
        ("post", "/lab/assets/a1/reassign", {"eurio_id": "fr-2015-2eur-paix"}),
    ],
)
def test_un_ami_ne_peut_pas_ecrire_le_canonique_par_l_entonnoir(methode, chemin, corps):
    """Les CINQ routes, une par une. Une seule oubliée suffit à rouvrir le trou —
    c'est exactement comme ça qu'il est resté ouvert : `decide` et `reject`
    avaient leur quarantaine, `decide_lot` n'a jamais été regardé."""
    r = getattr(_client(AMI), methode)(chemin, json=corps)
    assert r.status_code == 403, (
        f"{methode.upper()} {chemin} rend {r.status_code} à un ami — cette route "
        f"écrit le canonique sans passer par la quarantaine.\n{r.text}"
    )


def test_l_arbitre_passe_toujours(tmp_path, monkeypatch):
    """La contrepartie : on ferme pour l'ami, on ne casse rien pour l'arbitre.
    Un 403 ici voudrait dire qu'on a retiré au PO son tri par lot.

    La base est vraie (vide) et non simulée : sans elle, la route s'arrêterait
    sur sa dépendance de connexion et le test dirait « pas 403 » sans avoir
    jamais atteint le corps de la route.
    """
    from store import Store
    db = tmp_path / "t.db"
    Store(db)._connection().close()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))

    r = _client(ARBITRE).post(
        "/review-queue/lots/ebay_inexistant/decide", json={"assignments": []},
    )
    assert r.status_code != 403, (
        "l'arbitre doit garder le tri par lot — c'est son geste le plus efficace "
        "sur une annonce multi-pièces"
    )
