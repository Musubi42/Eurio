"""La moitié ACHETER de `/besoin` — `serving/scrape_plan_routes` (lot 5).

Ce que ces tests protègent, dans l'ordre d'importance :

1. **Aucune écriture, nulle part.** Ni le canonique, ni `eurio.local.db` : la
   lecture d'un budget ne doit pas créer de table. C'est pour ça qu'on ne passe
   pas par `QuotaTracker` (son `__init__` fait `CREATE TABLE IF NOT EXISTS`).
2. **Deux populations qu'on ne confond pas** : « jamais visée par une annonce
   eBay » et « visée, sans résultat ». La première se répare en scrapant, la
   seconde en cherchant pourquoi le scrape n'a rien donné. Les additionner
   ferait relancer un scrape qui a déjà échoué.
3. **Le rendement se remesure et porte ses requêtes** — au grain LISTING, pas
   au grain photo : une annonce porte 3 à 4 photos, et compter les photos
   gonflerait le rendement d'autant.
4. **Un budget illisible vaut ZÉRO, jamais « plein »** — c'est le bug B1 (le
   widget affichait 5000/5000 pendant qu'on brûlait 4 733 appels).
5. **Les deux réserves de FLOW-ADMIN §Station 1 sont dans la réponse**, pas
   dans un commentaire de code que l'écran ne lit pas.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest
from fastapi import HTTPException

from serving import scrape_plan_routes as sp
from store import Store

KIND = "2eur_all"
ENC = "dinov2-vitl14"


# ── Fixtures : un référentiel minuscule mais au VRAI schéma ──────────────────


def _coin(conn, eid, country, year, *, commemo, dgid=None):
    conn.execute(
        "INSERT INTO coins (eurio_id, country, country_name, year, face_value,"
        " is_commemorative, design_group_id, theme) VALUES (?,?,?,?,2.0,?,?,?)",
        (eid, country, country, year, int(commemo), dgid, "thème"),
    )


def _asset(conn, ref):
    """Un crop réel : `source_images` puis `image_assets` (la FK l'exige)."""
    conn.execute(
        "INSERT OR IGNORE INTO source_images (id, source, source_ref, storage_path)"
        " VALUES (?,'ebay',?,'x.jpg')",
        (f"si-{ref}", f"A-{ref}_img0"),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, storage_status)"
        " VALUES (?,?,'c.jpg','present')",
        (f"a-{ref}", f"si-{ref}"),
    )
    return f"a-{ref}"


def _bank(conn, class_id, n_fps):
    """Le canonique de la classe + `n_fps` exemplaires."""
    conn.execute(
        "INSERT INTO dino_class_references (anchors_kind, encoder_version, class_id,"
        " eurio_id, method) VALUES (?,?,?,?,'canonical')",
        (KIND, ENC, class_id, class_id),
    )
    for i in range(n_fps):
        aid = _asset(conn, f"{class_id}-{i}")
        conn.execute(
            "INSERT INTO dino_class_references (anchors_kind, encoder_version, class_id,"
            " eurio_id, asset_id, method, rank) VALUES (?,?,?,?,?,'fps',?)",
            (KIND, ENC, class_id, class_id, aid, i),
        )


def _listing(conn, listing_id, n_photos, *, target=None, source="ebay"):
    """Une annonce eBay et ses `n_photos` images.

    Le `source_ref` suit la convention réelle `<listing>_img<N>` : c'est elle
    que `substr(…, instr(…, '_img') - 1)` replie sur l'annonce.
    """
    for i in range(n_photos):
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref, storage_path,"
            " target_eurio_id) VALUES (?,?,?,?,?)",
            (f"si-{listing_id}-{i}", source, f"{listing_id}_img{i}", "x.jpg", target),
        )


@pytest.fixture()
def conn(tmp_path):
    """Cinq classes, trois pays, et les deux populations qu'on ne confond pas.

    * LU 2019 + LU 2020 : commémos à zéro, JAMAIS visées → `scrape`
    * LU 2021          : commémo à zéro, VISÉE sans résultat → `scrape`
    * MT 2018          : commémo à zéro, jamais visée → `scrape`
    * FR 2016          : commémo pleine (8 exemplaires) → jamais `scrape`
    """
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    _coin(c, "lu-2019", "LU", 2019, commemo=True)
    _coin(c, "lu-2020", "LU", 2020, commemo=True)
    _coin(c, "lu-2021", "LU", 2021, commemo=True)
    _coin(c, "mt-2018", "MT", 2018, commemo=True)
    _coin(c, "fr-2016", "FR", 2016, commemo=True)
    for cid in ("lu-2019", "lu-2020", "lu-2021", "mt-2018"):
        _bank(c, cid, 0)
    _bank(c, "fr-2016", 8)
    # 10 annonces × 3 photos : au grain listing elles pèsent 10, pas 30.
    # (les 8 exemplaires de `fr-2016` apportent 8 annonces d'une photo chacune)
    for i in range(10):
        _listing(c, f"L{i}", 3, target="fr-2016" if i == 0 else None)
    # lu-2021 a DÉJÀ été visée — et n'a toujours rien.
    _listing(c, "L-lu2021", 2, target="lu-2021")
    c.commit()
    return c


def _quota_db(path: Path, rows: list[tuple]) -> Path:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE api_call_log (source TEXT, key_hash TEXT, window TEXT,"
        " period TEXT, calls INTEGER, exhausted INTEGER, last_call_at TEXT,"
        " PRIMARY KEY (source, key_hash, window, period))"
    )
    conn.executemany("INSERT INTO api_call_log VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return path


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _summary(conn, quota_db: Path):
    return sp.summarize(conn, quota_db, anchors_kind=KIND, encoder_version=ENC, now=NOW)


# ── 1. Aucune écriture, nulle part ───────────────────────────────────────────


def test_le_module_ne_contient_aucun_ordre_decriture(tmp_path):
    """Une relecture ne doit rien écrire — la garantie se lit dans le source.

    Même contrat que `shared/class_need.py`. Un INSERT glissé ici partirait vers
    le canonique en réplique read-only et lèverait un 503 opaque, ou pire :
    écrirait dans `eurio.local.db` un compteur que personne n'a consommé.
    """
    import ast

    arbre = ast.parse(Path(sp.__file__).read_text(encoding="utf-8"))
    # Les docstrings PARLENT d'écriture (« on ne fait pas de CREATE TABLE ») :
    # les garder rendrait ce test vert-menteur dans l'autre sens.
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            if ast.get_docstring(noeud) is not None:
                noeud.body = noeud.body[1:]
    # On inspecte les LITTÉRAUX de chaîne, pas le code : c'est là que vit le
    # SQL. Chercher les verbes dans le source entier attraperait `model_copy(
    # update=…)` et rendrait le test inutilisable — donc, tôt ou tard, retiré.
    sql = [
        n.value for n in ast.walk(arbre)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    ecritures = [
        t for t in sql
        if re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE\s+INTO|CREATE\s+TABLE"
                     r"|DROP\s+TABLE|ALTER\s+TABLE)\b", t, re.IGNORECASE)
    ]
    assert ecritures == [], ecritures
    # Contre-épreuve : la sonde VOIT bien un ordre d'écriture quand il y en a un.
    assert re.search(r"\b(INSERT|UPDATE)\b", "INSERT INTO t VALUES (1)", re.IGNORECASE)


def test_lire_le_quota_ne_touche_pas_le_fichier(tmp_path):
    """`QuotaTracker.__init__` ferait un `CREATE TABLE IF NOT EXISTS`. Pas nous.

    On compare l'empreinte du fichier avant/après : un `CREATE TABLE IF NOT
    EXISTS` sur une table existante est un no-op logique, mais il OUVRE la base
    en écriture — ce que la contrainte du lot interdit.
    """
    db = _quota_db(tmp_path / "local.db",
                   [("ebay", "", "daily", "2026-08-23", 1200, 0, None)])
    avant = hashlib.sha256(db.read_bytes()).hexdigest()
    q = sp.read_quota(db, now=NOW)
    apres = hashlib.sha256(db.read_bytes()).hexdigest()
    assert q.readable and q.calls == 1200
    assert avant == apres
    assert not (tmp_path / "local.db-wal").exists()


# ── 2. Le quota, lu là où il est vrai ────────────────────────────────────────


def test_le_quota_du_jour_est_lu_dans_la_db_locale(tmp_path):
    db = _quota_db(tmp_path / "local.db", [
        ("ebay", "", "daily", "2026-08-23", 1200, 0, None),
        ("ebay", "", "daily", "2026-08-22", 4900, 0, None),   # hier, hors période
        ("numista", "k1", "monthly", "2026-08", 900, 0, None),  # autre source
    ])
    q = sp.read_quota(db, now=NOW)
    assert (q.calls, q.remaining) == (1200, 3800)
    # 3800 / 1,3 = 2923 — la marge du préflight CLI, pas une invention locale.
    assert q.safe_budget == int(3800 / sp.QUOTA_SAFETY_FACTOR) == 2923
    assert q.period == "2026-08-23"
    # Le chemin lu est dans la réponse : un chiffre sans son fichier n'est pas
    # vérifiable, et c'est exactement la réserve n°2 de FLOW-ADMIN.
    assert q.db_path == str(db)


def test_un_budget_illisible_vaut_zero_jamais_plein(tmp_path):
    """Bug B1 : planifier sur un quota supposé plein a brûlé 4 733 appels."""
    absente = sp.read_quota(tmp_path / "nulle-part.db", now=NOW)
    assert absente.readable is False
    assert (absente.remaining, absente.safe_budget) == (0, 0)
    assert "introuvable" in (absente.error or "")

    vide = sqlite3.connect(tmp_path / "sans-table.db")
    vide.execute("CREATE TABLE autre (x)")
    vide.commit()
    vide.close()
    sans = sp.read_quota(tmp_path / "sans-table.db", now=NOW)
    assert sans.readable is False and sans.remaining == 0
    assert "api_call_log" in (sans.error or "")


def test_le_jour_sans_appel_rend_le_quota_entier(tmp_path):
    db = _quota_db(tmp_path / "local.db",
                   [("ebay", "", "daily", "2026-08-01", 4000, 0, None)])
    q = sp.read_quota(db, now=NOW)
    assert (q.calls, q.remaining, q.readable) == (0, sp.EBAY_DAILY_QUOTA, True)


# ── 3. Les deux populations, jamais confondues ───────────────────────────────


def test_jamais_visee_et_visee_sans_resultat_sont_comptees_a_part(conn, tmp_path):
    """`lu-2021` a été visée par une annonce et n'a rien donné : la rescraper
    ne réglera rien. La compter avec les jamais-visées ferait financer un
    groupe qui a déjà échoué."""
    s = _summary(conn, tmp_path / "absent.db")
    lu = next(c for c in s.countries if c.country == "LU")
    assert lu.n_classes == 3
    assert lu.n_never_targeted == 2       # lu-2019, lu-2020
    assert lu.n_targeted_no_result == 1   # lu-2021
    assert lu.n_never_targeted + lu.n_targeted_no_result == lu.n_classes
    assert s.totals.n_never_targeted == 3          # + mt-2018
    assert s.totals.n_targeted_no_result == 1


def test_une_classe_pleine_nest_jamais_dans_la_moitie_acheter(conn, tmp_path):
    """`fr-2016` a 8 exemplaires : elle est `pleine`, pas `scrape`. Le verdict
    vient de `shared.class_need` et de nulle part ailleurs."""
    s = _summary(conn, tmp_path / "absent.db")
    assert "FR" not in {c.country for c in s.countries}
    assert s.totals.n_classes == 4


# ── 4. Le rendement : remesuré, au grain listing, avec ses requêtes ──────────


def test_le_rendement_compte_les_annonces_pas_les_photos(conn, tmp_path):
    """40 lignes `source_images` pour 19 annonces distinctes.

    10 annonces × 3 photos + 1 × 2 photos + les 8 annonces d'une photo qui
    portent les exemplaires de `fr-2016`. Compter les photos gonflerait le
    rendement d'un facteur 2 — et le coût affiché à l'écran avec lui.
    """
    y = sp.measure_yield(conn, KIND)
    n_lignes = conn.execute(
        "SELECT COUNT(*) FROM source_images WHERE source='ebay'"
    ).fetchone()[0]
    assert n_lignes == 40
    assert y.n_listings == 19
    assert y.n_exemplars == 8                       # les 8 fps de fr-2016
    assert y.listings_per_exemplar == round(19 / 8, 2) == 2.38


def test_le_rendement_porte_ses_deux_requetes(conn, tmp_path):
    """Un chiffre dont on ne peut pas rejouer la requête n'est pas vérifiable.

    Les requêtes renvoyées sont exécutées telles quelles ici : si l'une d'elles
    dérive du calcul, ce test tombe.
    """
    y = sp.measure_yield(conn, KIND)
    assert conn.execute(y.query_listings).fetchone()[0] == y.n_listings
    assert conn.execute(
        y.query_exemplars, y.query_exemplars_params
    ).fetchone()[0] == y.n_exemplars
    # La mesure de référence du design est transportée à côté, jamais à la place.
    assert (y.reference, y.reference_listings, y.reference_exemplars) == (6.6, 7662, 1160)


def test_une_banque_sans_exemplaire_ne_rend_pas_un_rendement_infini(tmp_path):
    c = Store(tmp_path / "vide.db")._connection()  # noqa: SLF001
    _coin(c, "lu-2019", "LU", 2019, commemo=True)
    _bank(c, "lu-2019", 0)
    _listing(c, "L0", 2)
    c.commit()
    y = sp.measure_yield(c, KIND)
    assert y.n_exemplars == 0
    assert y.listings_per_exemplar is None


def test_le_cout_en_annonces_se_base_sur_les_jamais_visees(conn, tmp_path):
    """Le chiffre du design : `n_never_targeted × rendement` (274 × 6,6 ≈ 1808).

    Pas `n_zero × rendement` : une classe visée sans résultat ne se répare pas
    en repayant la même recherche.
    """
    s = _summary(conn, tmp_path / "absent.db")
    ratio = s.measured_yield.listings_per_exemplar
    assert ratio is not None
    assert s.totals.estimated_listings_palier1 == round(s.totals.n_never_targeted * ratio)
    lu = next(c for c in s.countries if c.country == "LU")
    assert lu.estimated_listings_palier1 == round(lu.n_never_targeted * ratio)


# ── 5. La maille : le groupe de découverte, pas la classe ───────────────────


def test_deux_commemos_dune_meme_annee_ne_coutent_quun_groupe(tmp_path):
    """Une recherche eBay ramène le groupe entier (pays · dénomination · année).

    Compter par classe facturerait deux fois la même moisson.
    """
    c = Store(tmp_path / "g.db")._connection()  # noqa: SLF001
    _coin(c, "lu-2019-a", "LU", 2019, commemo=True)
    _coin(c, "lu-2019-b", "LU", 2019, commemo=True)
    _bank(c, "lu-2019-a", 0)
    _bank(c, "lu-2019-b", 0)
    c.commit()
    s = _summary(c, tmp_path / "absent.db")
    lu = next(x for x in s.countries if x.country == "LU")
    assert (lu.n_classes, lu.n_groups) == (2, 1)
    assert lu.estimated_calls == sp.COST_PER_COMMEMO_GROUP


def test_un_standard_coute_le_tarif_standard(tmp_path):
    """Le standard ratisse `limit=200` au lieu de 75 : 240 appels, pas 130."""
    c = Store(tmp_path / "s.db")._connection()  # noqa: SLF001
    c.execute("INSERT INTO design_groups (id, designation) VALUES ('lu-std','LU std')")
    _coin(c, "lu-2002-std", "LU", 2002, commemo=False, dgid="lu-std")
    _bank(c, "lu-2002-std", 0)
    c.commit()
    s = _summary(c, tmp_path / "absent.db")
    lu = next(x for x in s.countries if x.country == "LU")
    assert (lu.n_groups, lu.n_groups_standard) == (1, 1)
    assert lu.estimated_calls == sp.COST_PER_STANDARD_GROUP == 240


def test_les_pays_sortent_par_besoin_decroissant(conn, tmp_path):
    """L'ordre est celui du geste, pas l'alphabet : LU (3 classes) avant MT (1)."""
    s = _summary(conn, tmp_path / "absent.db")
    assert [c.country for c in s.countries] == ["LU", "MT"]


# ── 6. Les réserves sont portées à l'écran ──────────────────────────────────


def test_les_deux_reserves_sont_dans_la_reponse(conn, tmp_path):
    """FLOW-ADMIN §Station 1 : « sinon la station ment ». Une réserve rangée
    dans un commentaire de code n'atteint jamais l'écran."""
    s = _summary(conn, tmp_path / "absent.db")
    texte = " ".join(s.reserves)
    assert "sources/cli.py" in texte and "130" in texte
    assert "source_runs.n_calls" in texte
    assert "eurio.local.db" in texte and "api_call_log" in texte
    assert "pas au canonique" in texte


def test_la_commande_de_plan_est_un_dry_run(conn, tmp_path):
    """« Le lien ouvre un plan ; le plan a son propre bouton. » La commande
    affichée ne porte NI `--execute` NI `--yes`."""
    db = _quota_db(tmp_path / "local.db",
                   [("ebay", "", "daily", "2026-08-23", 1200, 0, None)])
    s = _summary(conn, db)
    assert s.plan_command == ["go-task", "ml:ebay:allocate", "--", "--budget", "2923"]
    assert "--execute" not in s.plan_command and "--yes" not in s.plan_command


# ── 7. Le refus : une banque introuvable n'est pas « tout est à acheter » ────


def test_une_banque_introuvable_est_un_409(conn, tmp_path):
    with pytest.raises(HTTPException) as e:
        sp.summarize(conn, tmp_path / "absent.db",
                     anchors_kind="pas_une_banque", encoder_version=ENC, now=NOW)
    assert e.value.status_code == 409
    assert "indissociable" in e.value.detail


def test_le_bloc_build_nomme_la_banque_lue(conn, tmp_path):
    """Deux lectures à deux builds différents ne sont pas un désaccord — encore
    faut-il que l'écran puisse le prouver."""
    s = _summary(conn, tmp_path / "absent.db")
    assert (s.build.anchors_kind, s.build.encoder_version) == (KIND, ENC)
    assert s.build.n_anchors == conn.execute(
        "SELECT COUNT(*) FROM dino_class_references WHERE anchors_kind=? AND encoder_version=?",
        (KIND, ENC),
    ).fetchone()[0]


# ── 8. Le contrat de montage : lourd ici, jamais sur l'image lean ───────────


def test_la_route_nest_pas_montee_sur_limage_lean():
    """Elle lit `eurio.local.db`, qui n'existe pas sur le VPS. La monter là-bas
    rendrait un quota inventé — et la page `/besoin`, elle, DOIT rester
    non-`heavy` : c'est ce bloc-ci qui se grise, pas la page."""
    lean = (ML_DIR / "serving" / "server_serve.py").read_text(encoding="utf-8")
    assert "scrape_plan_routes" not in lean
    full = (ML_DIR / "serving" / "server.py").read_text(encoding="utf-8")
    assert "scrape_plan_routes" in full


def test_le_front_ne_marque_pas_la_page_besoin_comme_heavy():
    """Garde-fou de la contrainte du lot : `/besoin` s'affiche entièrement en
    hébergé. Seul le bloc ACHETER se grise, via `heavyLocked`."""
    router = (ML_DIR.parent / "admin/packages/studio-local/src/app/router.ts").read_text(
        encoding="utf-8"
    )
    depuis = router.index("path: 'besoin'")
    # Jusqu'à la route SUIVANTE : `meta: heavy` appartient à `/review`, pas à
    # `/besoin`, et une fenêtre trop large le compterait à tort.
    fin = router.index("path:", depuis + 20)
    assert "heavy" not in router[depuis:fin]


# ── 9. Le contrat HTTP, joué pour de vrai ───────────────────────────────────


@pytest.fixture()
def client(conn, tmp_path, monkeypatch):
    """Un app minimal portant le routeur — le contrat HTTP, pas le serveur entier."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    canon = tmp_path / "canon.db"
    # `conn` a écrit dans tmp_path/"t.db" : on sert CE fichier en lecture seule.
    monkeypatch.setattr(sp, "_canonical_db", lambda: tmp_path / "t.db")
    # ⚠️ La période doit être CELLE DU JOUR : la route lit l'horloge réelle (elle
    # ne prend pas de `now=`, contrairement à `read_quota` dans les tests
    # ci-dessus). Figée à « 2026-08-23 », cette ligne rendait le test vert le
    # jour où elle a été écrite et rouge tous les suivants — constaté le
    # 2026-08-24 au matin, `assert 0 == 1200`. Un test daté n'est pas un test.
    aujourdhui = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    monkeypatch.setattr(sp, "_quota_db", lambda: _quota_db(
        tmp_path / "local.db", [("ebay", "", "daily", aujourdhui, 1200, 0, None)]
    ))
    assert not canon.exists()  # aucune base fabriquée au passage
    app = FastAPI()
    app.include_router(sp.router)
    return TestClient(app)


def test_le_resume_se_sert_en_http(client):
    r = client.get("/scrape-plan/summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {c["country"] for c in body["countries"]} == {"LU", "MT"}
    assert body["totals"]["n_never_targeted"] == 3
    assert body["quota"]["calls"] == 1200
    assert len(body["reserves"]) == 2
    # Le champ porte bien son nom côté HTTP : le front lit `measured_yield`.
    assert body["measured_yield"]["n_listings"] == 19


def test_un_couple_banque_encodeur_inexistant_rend_409_en_http(client):
    r = client.get("/scrape-plan/summary", params={"anchors_kind": "nawak"})
    assert r.status_code == 409
    assert "indissociable" in r.json()["detail"]
