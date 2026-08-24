"""`GET /referential/canonical-thumbs` — l'ADRESSE des vignettes, pas l'image.

POURQUOI CETTE ROUTE EXISTE, ET CE QUE CES TESTS GARDENT
---------------------------------------------------------
La route qui sert l'image (`/referential/canonical/{id}/{role}/thumb`) est gardée
par `coins:read`, et une balise `<img>` **n'envoie pas d'en-tête
`Authorization`**. En cookie (front hébergé, même site) le navigateur joint la
session tout seul ; en PAT — le mode de tout poste de dev — elle répond 401 et
l'image ne s'affiche pas, sans une ligne en console. Mesuré le 2026-08-24 : 401
sans en-tête, 302 avec.

Celle-ci rend des URLs **chargeables sans auth** (CDN public, ou référentiel
externe). Ce que les tests verrouillent :

1. **Le même ordre de priorité que `_serve_canonical`.** Deux écrans qui
   choisissent l'image d'une même pièce par deux règles montreraient deux images
   différentes, chacune « correcte » selon la sienne.
2. **La vignette d'abord, le plein format ensuite.** Servir le plein format sur
   une liste de 253 lignes, c'est des mégaoctets pour des disques de 40 px.
3. **L'URL externe est le dernier recours, pas un oubli.** 166 pièces sur 658
   n'ont QUE ça : rendre `null` afficherait un vide au-dessus d'une image qui se
   charge parfaitement.
4. **Une pièce inconnue rend `null`, jamais une erreur.** Une vignette manquante
   ne doit pas emporter la liste : c'est de l'illustration.
5. **Le lot est borné.** Sans plafond, un appelant distrait fabrique une query
   string de plusieurs kilo-octets et récolte un 414 en production seulement.
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

from serving import referential_routes as rr
from serving.auth_principal import Principal, require_principal

PAIX = "fr-2015-2eur-paix"
SACHSEN = "de-2016-2eur-sachsen"
NUE = "va-2016-2eur-jubile"        # connue du référentiel par une URL externe seule
INCONNUE = "xx-9999-2eur-neant"
#: Source DB = `unknown`, DERNIER des fallbacks codés en dur (bce_comm, numista,
#: unknown). Et son bucket porte AUSSI la clé `bce_comm`, le PREMIER. C'est la
#: seule forme qui rend le choix observable : avec un coin dont la source DB est
#: déjà `bce_comm`, ignorer `_lookup_source` donne le même résultat, et le test
#: passe au vert sur du code faux (constaté par mutation le 2026-08-24).
PRIO = "it-2018-2eur-sante"


class _FauxStore:
    def __init__(self, conn):
        self._conn = conn

    def _connection(self):
        return self._conn


@pytest.fixture()
def env(monkeypatch):
    import sqlite3
    # `check_same_thread=False` : FastAPI exécute une route SYNCHRONE dans un
    # worker du threadpool, donc pas dans le thread qui a créé la connexion.
    # C'est un fait du harnais, pas du produit — le vrai `Store` ouvre une
    # connexion par thread (`self._local.conn`). Même piège que le lot 1b, une
    # marche plus bas.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE coin_canonical_images "
        "(eurio_id TEXT, role TEXT, source TEXT, url TEXT)"
    )
    conn.executemany(
        "INSERT INTO coin_canonical_images VALUES (?,?,?,?)",
        [
            (PAIX, "obverse", "bce_comm", None),
            (SACHSEN, "obverse", "numista", None),
            (NUE, "obverse", "numista_api", "https://numista.example/nue.jpg"),
            (PRIO, "obverse", "unknown", None),
        ],
    )
    rr.bind(_FauxStore(conn))

    # Le bucket, tel que le voit la route. `PAIX` y a sa VIGNETTE ; `SACHSEN`
    # n'a que le plein format — c'est ce qui distingue les deux passes.
    from referential.canonical_image_local import CANONICAL_DIR, canonical_path
    def key(eid, src, thumb):
        return canonical_path(eid, "obverse", src, thumb=thumb).relative_to(
            CANONICAL_DIR).as_posix()
    bucket = {
        key(PAIX, "bce_comm", True),
        key(SACHSEN, "numista", False),
        # Les DEUX pour PRIO : c'est ce qui rend le choix de source observable.
        key(PRIO, "bce_comm", True), key(PRIO, "unknown", True),
    }
    monkeypatch.setattr(rr, "_bucket_keys", lambda: bucket)
    yield key
    rr.bind(None)  # type: ignore[arg-type]


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(rr.router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="t", email="t@test.local", roles=["reviewer"],
        scopes={"coins:read"}, auth_method="api_token",
    )
    return TestClient(app)


def _urls(ids: list[str]) -> dict:
    r = _client().get(f"/referential/canonical-thumbs?ids={','.join(ids)}")
    assert r.status_code == 200, r.text
    return r.json()["urls"]


def test_les_urls_ne_demandent_aucun_en_tete(env):
    """Le point de toute la route : ce qu'elle rend doit pouvoir tomber dans un
    `src=` — donc jamais une adresse de cette API, qui exige `coins:read`."""
    u = _urls([PAIX, SACHSEN, NUE])
    for eid, url in u.items():
        assert url, eid
        assert "/referential/" not in url, (
            f"{eid} pointe l'API : une <img> n'enverra pas de jeton, et l'image "
            "sera vide en PAT sans une ligne en console"
        )


def test_la_vignette_passe_avant_le_plein_format(env):
    u = _urls([PAIX, SACHSEN])
    assert u[PAIX].endswith("_thumb.webp"), "PAIX a sa vignette dans le bucket"
    assert not u[SACHSEN].endswith("_thumb.webp"), (
        "SACHSEN n'a que le plein format — mieux vaut ça que rien, mais on ne "
        "doit pas le préférer quand la vignette existe"
    )


def test_l_url_externe_est_le_dernier_recours_pas_un_oubli(env):
    """166 pièces sur 658 n'ont QUE ça. Rendre `null` afficherait un vide
    au-dessus d'une image qui se charge parfaitement."""
    assert _urls([NUE])[NUE] == "https://numista.example/nue.jpg"


def test_une_piece_inconnue_rend_null_pas_une_erreur(env):
    u = _urls([INCONNUE, PAIX])
    assert u[INCONNUE] is None
    assert u[PAIX], "une pièce sans image ne doit pas emporter les autres"


def test_la_source_vient_de_la_base_pas_du_premier_fallback_venu(env):
    """⛔ Le point le plus important, et le plus facile à tester pour rien.

    Si les deux chemins divergent, la fiche pièce et l'accueil montrent deux
    images différentes de la même pièce, chacune « correcte » selon sa propre
    règle — et personne ne sait laquelle croire.

    `PRIO` est construite exprès : sa source en base est `unknown`, le DERNIER
    des fallbacks, et son bucket porte aussi `bce_comm`, le PREMIER. Retirer
    `_lookup_source` change donc la réponse. Première version de ce test :
    `PAIX`, dont la source en base était déjà `bce_comm` — la mutation passait au
    vert, le test ne prouvait rien.
    """
    key = env
    assert rr._lookup_source(PRIO, "obverse") == "unknown"
    assert _urls([PRIO])[PRIO].endswith(key(PRIO, "unknown", True)), (
        "la source doit venir de la base ; `bce_comm` ici signifie que le "
        "fallback codé en dur a gagné"
    )


def test_les_deux_chemins_choisissent_la_MEME_image(env):
    """⛔ LE test de ce fichier — trouvé en revue adversariale le 2026-08-24.

    `SACHSEN` n'a que son PLEIN FORMAT en bucket, pas de vignette. Avant le
    correctif, les deux chemins divergeaient :
      - `/canonical/{id}/obverse/thumb` ne testait QUE `thumb=True`, ne trouvait
        rien, et sautait à l'URL externe (ici absente → 404) ;
      - `/canonical-thumbs` descendait jusqu'au plein format et le servait.
    Même pièce, même face, deux réponses. L'écran de review et l'accueil
    montraient alors deux images différentes — chacune « correcte » selon sa
    propre règle, et personne pour dire laquelle croire.

    Les deux descendent maintenant `_cle_bucket`, la même échelle.
    """
    lot = _urls([SACHSEN])[SACHSEN]
    assert lot, "le plein format en bucket doit être servi plutôt que rien"

    r = _client().get(
        f"/referential/canonical/{SACHSEN}/obverse/thumb", follow_redirects=False,
    )
    assert r.status_code == 302, (
        f"la route qui SERT l'image rend {r.status_code} là où celle qui rend "
        "l'ADRESSE trouve une image — c'est exactement la divergence corrigée"
    )
    assert r.headers["location"] == lot, (
        f"deux images pour la même pièce : {r.headers['location']} vs {lot}"
    )


def test_un_lot_demesure_est_refuse_plutot_que_tronque(env):
    """Tronquer en silence rendrait une liste à moitié illustrée sans que rien
    ne le dise — et le trou se lirait « ces pièces n'ont pas d'image »."""
    r = _client().get(
        "/referential/canonical-thumbs?ids=" + ",".join(f"x{i}" for i in range(1001))
    )
    assert r.status_code == 400, r.text
    assert "1000" in r.json()["detail"]


def test_les_doublons_ne_sont_comptes_qu_une_fois(env):
    u = _urls([PAIX, PAIX, PAIX])
    assert list(u) == [PAIX]


def test_la_garde_de_lecture_est_coins_read():
    """La garde n'est PAS dans le router — et c'est ce qu'il faut savoir.

    `referential` est monté via `_CANDIDATES` avec `require_scope_by_method`
    (lot 4b) : son couple lecture/écriture est déclaré dans
    `serving/router_scopes.py`, et un router sans couple fait échouer le boot.
    Monter le router nu dans un test, comme ci-dessus, n'exerce donc AUCUNE
    garde — un test qui attendrait un 403 ici prouverait le contraire de ce
    qu'il croit.

    Ce qu'on vérifie, c'est la POLITIQUE : le GET tombe sous `coins:read`, qu'un
    ami possède (sa recherche libre `F` en dépend). Sans ça, sa liste perdrait
    ses images alors qu'il a le droit de les voir.
    """
    from serving.router_scopes import ROUTER_SCOPES
    lecture, ecriture = ROUTER_SCOPES["referential"]
    assert lecture == "coins:read"
    assert ecriture == "coins:write"
