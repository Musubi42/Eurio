"""`GET /class-need` — la façade HTTP du besoin (lot 2 de `/besoin`).

Ce qui est verrouillé ici, et pourquoi chaque point a coûté quelque chose :

1. **Le compte à l'écran = le compte en base.** `totals` doit égaler ce que
   `all_needs` rend, sans réagrégation côté route. Un même fait porte partout le
   même nombre — c'est la règle qui a coûté le plus cher à réapprendre dans ce
   dépôt.
2. **Une banque introuvable rend 409, jamais 671 classes en `scrape`.** Le
   couple `(anchors_kind, encoder_version)` est indissociable ; le deviner
   donnerait un JOIN à zéro ligne qui se lit « tout est à scraper » —
   parfaitement plausible, et faux.
3. **Les classes pleines ne sont pas masquées** (refus n°3 de `class_need`) :
   c'est l'information la plus utile de l'outil.
4. **`country_disarmed` traverse jusqu'au JSON.** Sans lui, l'écran annonce des
   candidats au-dessus d'un lien qui sert zéro.
5. **`parked` distingue ses deux causes.** `full_class` se répare par du tri,
   `no_prediction` par un backfill : les additionner perdrait la seule
   information actionnable.
6. **Rien n'est écrit.** C'est une lecture, servie par l'image lean.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from serving.class_need_routes import router as class_need_router
from store import Store

KIND = "2eur_all"
ENC = "dinov2-vitl14"
BUILD = "b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0"

FULL = "fr-2015-2eur-paix"        # à la cible → `pleine`, ses crops parqués
NEEDY = "de-2016-2eur-sachsen"    # en besoin, candidats du bon pays → `review`
EXILE = "lu-2016-2eur-pont"       # candidats TOUS étrangers → pays désarmé
DRY = "va-2016-2eur-jubile"       # aucun candidat → `scrape`


def _coin(conn, eid, country, year):
    conn.execute(
        "INSERT INTO coins (eurio_id, country, country_name, year, face_value,"
        " is_commemorative, theme) VALUES (?,?,?,?,2.0,1,'thème')",
        (eid, country, country, year),
    )


def _asset(conn, ref, *, country=None, eligible=0):
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, listing_country,"
        " storage_path) VALUES (?,'ebay',?,?,'x.jpg')",
        (f"si-{ref}", f"r-{ref}", country),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path,"
        " storage_status, training_eligible) VALUES (?,?,'c.jpg','present',?)",
        (f"a-{ref}", f"si-{ref}", eligible),
    )
    return f"a-{ref}"


def _predict(conn, aid, top1):
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version,"
        " anchors_kind, anchors_count, top_k_json, top1_eurio_id, top1_sim,"
        " spread) VALUES (?,?,?,10,?,?,0.8,0.2)",
        (aid, ENC, KIND, json.dumps([{"eurio_id": top1, "sim": 0.8}]), top1),
    )


def _bank(conn, class_id, n_fps):
    conn.execute(
        "INSERT INTO dino_class_references (anchors_kind, encoder_version,"
        " class_id, eurio_id, method, build_id, built_at)"
        " VALUES (?,?,?,?,'canonical',?, '2026-08-22 18:06:22')",
        (KIND, ENC, class_id, class_id, BUILD),
    )
    for i in range(n_fps):
        aid = _asset(conn, f"ref-{class_id}-{i}")
        conn.execute(
            "INSERT INTO dino_class_references (anchors_kind, encoder_version,"
            " class_id, eurio_id, asset_id, method, rank, build_id, built_at)"
            " VALUES (?,?,?,?,?,'fps',?,?, '2026-08-22 18:06:22')",
            (KIND, ENC, class_id, class_id, aid, i, BUILD),
        )


def _open(conn, ref, top1, *, country):
    aid = _asset(conn, ref, country=country)
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status)"
        " VALUES (?,?,'open')",
        (f"rq-{ref}", aid),
    )
    _predict(conn, aid, top1)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = Store(db)._connection()  # noqa: SLF001
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    for eid, cc in ((FULL, "FR"), (NEEDY, "DE"), (EXILE, "LU"), (DRY, "VA")):
        _coin(conn, eid, cc, 2016)
    _bank(conn, FULL, 8)     # à la cible (8)
    _bank(conn, NEEDY, 2)
    _bank(conn, EXILE, 0)
    _bank(conn, DRY, 0)

    _open(conn, "full1", FULL, country="FR")     # parqué : classe pleine
    _open(conn, "full2", FULL, country="DE")     # parqué aussi
    _open(conn, "needy1", NEEDY, country="DE")   # servi, du bon pays
    _open(conn, "needy2", NEEDY, country="FR")   # masqué par le filtre pays
    _open(conn, "exile1", EXILE, country="DE")   # LU : QUE des annonces DE
    _open(conn, "exile2", EXILE, country="FR")
    # Un crop ouvert SANS prédiction dans cette banque → parqué `no_prediction`
    aid = _asset(conn, "muet", country="DE")
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status)"
        " VALUES ('rq-muet', ?, 'open')", (aid,),
    )
    # Un ACQUIS (D8) sur NEEDY : validé, pas encore bâti
    acq = _asset(conn, "acquis", country="DE", eligible=1)
    _predict(conn, acq, NEEDY)
    conn.commit()
    return conn, db


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(class_need_router)
    app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="t", email="t@test.local", roles=["admin"],
        scopes={"lab:read"}, auth_method="api_token",
    )
    return TestClient(app)


def _rows(payload) -> dict:
    return {r["class_id"]: r for r in payload["classes"]}


# ─── Le contrat ─────────────────────────────────────────────────────────────


def test_la_route_nomme_la_banque_qu_elle_a_lue(env):
    """Sans ce bloc, deux lectures d'un même chiffre à deux builds différents
    se lisent comme un désaccord. La banque a été rebâtie DEUX fois pendant la
    seule session de design du 2026-08-22."""
    r = _client().get("/class-need")
    assert r.status_code == 200, r.text
    build = r.json()["build"]
    assert build["build_id"] == BUILD
    assert build["built_at"] == "2026-08-22 18:06:22"
    assert build["anchors_kind"] == KIND and build["encoder_version"] == ENC
    assert build["n_anchors"] == 4 + 8 + 2  # canoniques + fps


def test_une_banque_introuvable_rend_409_pas_un_catalogue_a_scraper(env):
    """Le refus n°2 de `class_need` porté en HTTP. Un JOIN à zéro ligne se
    lirait « 671 classes à scraper » — plausible, et faux."""
    r = _client().get("/class-need?anchors_kind=2eur_commemo")
    assert r.status_code == 409, r.text
    assert "indissociable" in r.json()["detail"]

    r = _client().get(f"/class-need?anchors_kind={KIND}&encoder_version=vits14")
    assert r.status_code == 409


def test_les_totaux_egalent_ce_que_class_need_rend(env):
    """Le compte à l'écran = le compte en base, sans réagrégation côté route."""
    conn, _ = env
    from shared.class_need import all_needs
    needs = all_needs(conn, anchors_kind=KIND, encoder_version=ENC)

    t = _client().get("/class-need").json()["totals"]
    assert t["n_classes"] == len(needs) == 4
    assert t["sum_need"] == sum(n.need for n in needs)
    assert t["sum_reachable"] == sum(min(n.need, n.pending_scoped) for n in needs)
    assert t["coverage"] == sum(1 for n in needs if n.have >= 1) == 2
    assert t["accepted_pending"] == sum(n.accepted_pending for n in needs) == 1
    assert t["by_bottleneck"] == {"pleine": 1, "review": 2, "scrape": 1}


def test_les_classes_pleines_ne_sont_pas_masquees(env):
    """Refus n°3 de `class_need` : c'est l'info la plus utile de l'outil."""
    rows = _rows(_client().get("/class-need").json())
    assert set(rows) == {FULL, NEEDY, EXILE, DRY}
    assert rows[FULL]["bottleneck"] == "pleine"
    assert rows[FULL]["pending"] == 2, "ses parqués restent comptés et visibles"
    assert rows[FULL]["cap"] == 10, "le plafond du builder reste exposé"


def test_le_desarmement_pays_traverse_jusqu_au_json(env):
    """O4c. Sans ce drapeau l'écran annonce des candidats au-dessus d'un lien
    qui sert zéro — le « badge qui dit 4 sur une file qui en sert 3 »."""
    rows = _rows(_client().get("/class-need").json())

    # LU : deux candidats, aucun d'une annonce LU → le filtre se retire.
    assert rows[EXILE]["country"] == "LU"
    assert rows[EXILE]["country_disarmed"] is True
    assert rows[EXILE]["n_hidden_by_country"] == 0
    assert rows[EXILE]["bottleneck"] == "review"

    # DE : un candidat du pays, un étranger → le filtre mord, et il le dit.
    assert rows[NEEDY]["country_disarmed"] is False
    assert rows[NEEDY]["n_hidden_by_country"] == 1


def test_le_zero_qui_s_explique_n_est_pas_un_desarmement(env):
    """« rien scrapé » et « le filtre m'en empêche » sont deux gestes
    différents : scrape d'un côté, review de l'autre (O2 §3)."""
    rows = _rows(_client().get("/class-need").json())
    assert rows[DRY]["pending"] == 0
    assert rows[DRY]["bottleneck"] == "scrape"
    assert rows[DRY]["country_disarmed"] is False


def test_les_parques_distinguent_leurs_deux_causes(env):
    """`full_class` se répare par du tri, `no_prediction` par un backfill.
    Les additionner perdrait la seule information actionnable."""
    p = _client().get("/class-need").json()["parked"]
    assert p["full_class"] == 2, "les deux crops de la classe pleine"
    assert p["no_prediction"] == 1, "le crop sans top-1 dans cette banque"

    t = _client().get("/class-need").json()["totals"]
    assert t["n_open"] == 7


def test_les_acquis_et_ce_qu_un_rebuild_poserait(env):
    """D8. `rebuild_would_place` n'est pas Σ accepted_pending : un acquis dans
    une classe déjà pleine ne pose rien, et c'est la mesure de la sur-review."""
    payload = _client().get("/class-need").json()
    assert _rows(payload)[NEEDY]["accepted_pending"] == 1
    assert payload["totals"]["rebuild_would_place"] == 1
    assert _rows(payload)[NEEDY]["have"] == 2, "la banque n'a pas bougé"


def test_la_route_n_ecrit_rien(env):
    """Une lecture. Le module ne doit contenir aucun ordre d'écriture — même
    garde que `shared/class_need.py`."""
    src = (ML_DIR / "serving" / "class_need_routes.py").read_text()
    code = "\n".join(
        l for l in src.splitlines()
        if not l.strip().startswith("#")
    ).lower()
    for verb in ("insert into", "update ", "delete from", "commit()"):
        assert verb not in code, f"ordre d'écriture trouvé : {verb!r}"


def test_l_effet_de_l_ere_traverse_jusqu_au_json(env):
    """O4a/b — la ligne doit dire ce que chaque filtre lui retire.

    Un crop marqué `de-2016-…sachsen` dans une annonce dont le titre ne parle
    que de 2026 ne peut pas être cette pièce. La ligne le sert donc en moins, et
    l'écrit : sans ce nombre, `pending` et `pending_scoped` diffèrent sans que
    rien n'explique l'écart — la dette exacte que le lot 6 ferme.
    """
    conn, _ = env
    conn.execute(
        "INSERT INTO listing_text_signals (source_image_id, years_json, coverage)"
        " VALUES ('si-needy1','[2026]','rich')",
    )
    conn.commit()

    rows = _rows(_client().get("/class-need").json())
    assert rows[NEEDY]["pending"] == 2
    assert rows[NEEDY]["n_hidden_by_era"] == 1
    assert rows[NEEDY]["n_hidden_by_denom"] == 0, "la porte n'est pas armée"
    assert (rows[NEEDY]["pending"]
            - rows[NEEDY]["n_hidden_by_era"]
            - rows[NEEDY]["n_hidden_by_country"]
            - rows[NEEDY]["n_hidden_by_denom"]) == rows[NEEDY]["pending_scoped"]


# ─── Trous fermés après revue par mutation (2026-08-23) ─────────────────────
#
# Ces trois-là survivaient à leur mutation : le code était juste, mais rien ne
# le tenait. Un test qui ne tue pas sa mutation ne protège rien.


def test_le_rebuild_ne_promet_que_ce_qu_il_peut_poser(env):
    """`rebuild_would_place` est Σ min(need, accepted_pending), pas Σ acquis.

    Un acquis dans une classe déjà pleine ne posera RIEN — le builder s'arrête
    à la cible. Sommer les acquis bruts ferait annoncer « un rebuild poserait
    1 622 exemplaires » là où il en pose 196 : un facteur 8 sur le seul chiffre
    qui décide s'il vaut le coup de rebâtir.
    """
    conn, _ = env
    # FULL est à sa cible (8/8) : ses acquis ne peuvent rien poser.
    for i in range(5):
        acq = _asset(conn, f"surplus{i}", country="FR", eligible=1)
        _predict(conn, acq, FULL)
    conn.commit()

    t = _client().get("/class-need").json()["totals"]
    assert t["accepted_pending"] == 6, "5 sur la classe pleine + 1 sur NEEDY"
    assert t["rebuild_would_place"] == 1, (
        "seul l'acquis de NEEDY peut devenir un exemplaire ; les 5 autres "
        "tombent dans une classe qui a déjà sa cible"
    )


def test_le_besoin_inclut_les_classes_sans_candidat(env):
    """`deficient_class_ids` doit rendre les `scrape`, pas seulement les `review`.

    Une classe sans candidat EST en besoin — elle n'a simplement rien à
    trancher aujourd'hui. L'exclure ferait parquer ses crops dès qu'un scrape
    lui en apporterait : le filtre `need_only` se refermerait sur le travail
    qu'on vient d'aller chercher.
    """
    from serving.review_queue.repository import deficient_class_ids

    conn, _ = env
    ids = set(deficient_class_ids(conn))
    assert DRY in ids, "une classe `scrape` est en besoin, pas hors besoin"
    assert EXILE in ids and NEEDY in ids
    assert FULL not in ids, "la classe à sa cible, elle, sort bien"


def test_have_ne_compte_pas_une_autre_banque(env):
    """Le couple (anchors_kind, encoder_version) est indissociable.

    C'est le refus n°2 que `class_need` s'impose en en-tête. Sans la condition
    sur l'encodeur, `have` additionnerait les exemplaires de deux banques et
    des classes paraîtraient pleines sans l'être — un JOIN trop large ne lève
    rien, il ment.
    """
    from shared.class_need import all_needs

    conn, _ = env
    # Six exemplaires de plus sur NEEDY, mais sous un AUTRE encodeur.
    for i in range(6):
        aid = _asset(conn, f"vits{i}")
        conn.execute(
            "INSERT INTO dino_class_references (anchors_kind, encoder_version,"
            " class_id, eurio_id, asset_id, method, rank)"
            " VALUES (?, 'dinov2-vits14', ?, ?, ?, 'fps', ?)",
            (KIND, NEEDY, NEEDY, aid, 100 + i),
        )
    conn.commit()

    needs = {n.class_id: n for n in all_needs(
        conn, anchors_kind=KIND, encoder_version=ENC)}
    assert needs[NEEDY].have == 2, "les 6 exemplaires vits14 ne comptent pas ici"
    assert needs[NEEDY].bottleneck != "pleine"
