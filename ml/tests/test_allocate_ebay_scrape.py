"""Tests de l'allocateur de scrape eBay.

Ce que ces tests protègent, dans l'ordre d'importance :

1. **aucun appel eBay** hors du geste explicite `--execute --yes` — le quota est
   du vrai argent ;
2. le script **n'écrit jamais** dans la base qu'il lit ;
3. les trois règles que les mesures imposent : plafonner à la cible, ne jamais
   viser 1, soustraire ce qui attend déjà en review ;
4. le grain d'allocation (un groupe = une recherche = un représentant), sans
   lequel on paie deux fois la même moisson.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from scripts import allocate_ebay_scrape as alloc  # noqa: E402

_DDL = """
CREATE TABLE coins (
  eurio_id TEXT PRIMARY KEY, country TEXT, country_name TEXT, year INTEGER,
  face_value REAL, is_commemorative INTEGER DEFAULT 0, numista_id INTEGER,
  theme TEXT,
  design_group_id TEXT, canonical_eurio_id TEXT
);
CREATE TABLE dino_class_references (
  anchors_kind TEXT, class_id TEXT, eurio_id TEXT, asset_id TEXT, method TEXT
);
CREATE TABLE review_queue (
  id TEXT PRIMARY KEY, image_asset_id TEXT, status TEXT
);
CREATE TABLE image_asset_dino_predictions (
  asset_id TEXT, anchors_kind TEXT, top1_eurio_id TEXT,
  country_spread REAL, spread REAL
);
CREATE TABLE discovery_searches (query_q TEXT, created_at TEXT);
CREATE TABLE coin_source_status (eurio_id TEXT, source TEXT, state TEXT);
"""


def _db(tmp_path: Path) -> Path:
    """Un référentiel minimal mais réaliste.

    * FR 2020 : 2 commémos à zéro exemplaire → le groupe le plus déficitaire ;
    * FR 2021 : 1 commémo à 1 exemplaire → la régression mesurée (N=1 < N=0) ;
    * DE 2020 : 1 commémo à zéro MAIS 8 candidats en file → review, pas scrape ;
    * IT 2020 : 1 commémo déjà pleine (8) → besoin nul ;
    * ES standard : 2 pièces d'un même design group → 1 seule classe, groupe std.
    """
    db = tmp_path / "fake.db"
    conn = sqlite3.connect(db)
    conn.executescript(_DDL)
    coins = [
        ("fr-2020-a", "FR", 2020, 1, 1, None),
        ("fr-2020-b", "FR", 2020, 1, 2, None),
        ("fr-2021-a", "FR", 2021, 1, 3, None),
        ("de-2020-a", "DE", 2020, 1, 4, None),
        ("it-2020-a", "IT", 2020, 1, 5, None),
        ("es-1999-std", "ES", 1999, 0, 6, "es-2euro-std"),
        ("es-2010-std", "ES", 2010, 0, 7, "es-2euro-std"),
    ]
    for eid, country, year, commemo, nid, dg in coins:
        conn.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, "
            "is_commemorative, numista_id, design_group_id) VALUES (?,?,?,2.0,?,?,?)",
            (eid, country, year, commemo, nid, dg),
        )
    # Canoniques (méthode 'canonical' — ne comptent PAS comme exemplaires).
    for cid in ("fr-2020-a", "fr-2020-b", "fr-2021-a", "de-2020-a",
                "it-2020-a", "es-1999-std"):
        conn.execute(
            "INSERT INTO dino_class_references VALUES ('2eur_all',?,?,NULL,'canonical')",
            (cid, cid),
        )
    # Exemplaires : fr-2021-a en a 1 (le cas régressif), it-2020-a en a 8.
    for i in range(1):
        conn.execute(
            "INSERT INTO dino_class_references VALUES "
            "('2eur_all','fr-2021-a','fr-2021-a',?,'fps')", (f"a{i}",))
    for i in range(8):
        conn.execute(
            "INSERT INTO dino_class_references VALUES "
            "('2eur_all','it-2020-a','it-2020-a',?,'fps')", (f"b{i}",))
    # File : 8 candidats au-dessus de la marge pour de-2020-a, 1 sous la marge.
    for i in range(8):
        aid = f"q{i}"
        conn.execute("INSERT INTO review_queue VALUES (?,?, 'open')", (f"r{i}", aid))
        conn.execute(
            "INSERT INTO image_asset_dino_predictions VALUES (?, '2eur_all',"
            " 'de-2020-a', 0.30, 0.30)", (aid,))
    conn.execute("INSERT INTO review_queue VALUES ('rx','qx','open')")
    conn.execute(
        "INSERT INTO image_asset_dino_predictions VALUES "
        "('qx','2eur_all','fr-2020-a', 0.01, 0.01)")
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return _db(tmp_path)


def _alloc(db: Path, tmp_path: Path, **kw):
    conn = alloc.connect_ro(db)
    try:
        params = dict(
            target=8, spread_min=0.05, regression_weight=2.0, min_need=2,
            budget=10_000, today="2026-08-20", cooldown_days=30, max_groups=None,
            datasets_dir=tmp_path / "no-datasets",
        )
        params.update(kw)
        return alloc.build_allocation(conn, **params)
    finally:
        conn.close()


# ── 1. Le quota est du vrai argent ───────────────────────────────────────────


def test_dry_run_par_defaut_nappelle_rien(db, tmp_path, capsys, monkeypatch):
    """Sans --execute, aucune commande n'est lancée : seulement imprimée."""
    def _boom(cmd):  # pragma: no cover - doit ne jamais être appelé
        raise AssertionError(f"un run eBay a été lancé en dry-run : {cmd}")

    monkeypatch.setattr(alloc, "_subprocess_runner", _boom)
    rc = alloc.main([
        "--db", str(db), "--budget", "10000", "--today", "2026-08-20",
    ])
    assert rc == 0
    assert "PLAN D'ALLOCATION" in capsys.readouterr().out


def test_execute_sans_yes_refuse(db, tmp_path, monkeypatch):
    def _boom(cmd):  # pragma: no cover
        raise AssertionError(f"lancé sans --yes : {cmd}")

    monkeypatch.setattr(alloc, "_subprocess_runner", _boom)
    with pytest.raises(SystemExit) as e:
        alloc.main(["--db", str(db), "--budget", "10000",
                    "--today", "2026-08-20", "--execute"])
    assert "--yes" in str(e.value)


def test_execute_passe_par_go_task_et_un_seul_id_par_groupe(db, tmp_path):
    """Le mode réel invoque go-task (EURIO_CENSUS_RECOVER=1) et déduplique."""
    a = _alloc(db, tmp_path)
    calls: list[list[str]] = []
    rc = alloc.execute(a, groups_per_run=8, runner=lambda c: calls.append(c) or 0,
                       quota_reader=lambda: 10_000)
    assert rc == 0
    assert calls and calls[0][:2] == ["go-task", "ml:src:ebay:run"]
    assert "--push" in calls[0]
    ids = calls[0][calls[0].index("--target-eurio-ids") + 1].split(",")
    assert len(ids) == len(set(ids)) == len(a.planned)


def test_execute_sarrete_a_la_premiere_vague_en_echec(db, tmp_path):
    """Un échec ne doit pas brûler le quota des vagues suivantes."""
    a = _alloc(db, tmp_path)
    a.planned = a.planned[:1] * 3  # trois vagues d'un groupe
    calls: list[list[str]] = []

    def runner(cmd):
        calls.append(cmd)
        return 2

    assert alloc.execute(a, groups_per_run=1, runner=runner) == 2
    assert len(calls) == 1


# ── 2. Aucune écriture dans la base lue ──────────────────────────────────────


def test_connexion_read_only(db):
    conn = alloc.connect_ro(db)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("INSERT INTO coins (eurio_id) VALUES ('x')")
    conn.close()


def test_le_plan_ne_modifie_pas_la_base(db, tmp_path):
    before = db.read_bytes()
    _alloc(db, tmp_path)
    assert db.read_bytes() == before


# ── 3. Les trois règles imposées par les mesures ─────────────────────────────


def test_regle_darret_une_classe_pleine_na_aucun_besoin(db, tmp_path):
    states = {c.class_id: c for c in _all_states(db, tmp_path)}
    assert states["it-2020-a"].have == 8
    assert states["it-2020-a"].need == 0


def test_cible_au_dessus_du_plafond_de_la_banque_refusee(db, tmp_path):
    conn = alloc.connect_ro(db)
    try:
        with pytest.raises(SystemExit, match="plafond"):
            alloc.build_class_states(
                conn, target=alloc.HARD_CAP + 1,
                datasets_dir=tmp_path / "no-datasets")
    finally:
        conn.close()


def test_la_file_de_review_est_soustraite_du_besoin(db, tmp_path):
    """de-2020-a a 8 candidats au-dessus de la marge : le geste est la review."""
    states = {c.class_id: c for c in _all_states(db, tmp_path)}
    assert states["de-2020-a"].pending == 8
    assert states["de-2020-a"].need == 0
    a = _alloc(db, tmp_path)
    assert "DE/2020" not in [g.key.label() for g in a.planned]
    assert "de-2020-a" in [c.class_id for c in a.review_covered]


def test_la_marge_faible_ne_compte_pas_comme_candidat(db, tmp_path):
    """Le crop à spread 0,01 sur fr-2020-a n'allège en rien son déficit."""
    states = {c.class_id: c for c in _all_states(db, tmp_path)}
    assert states["fr-2020-a"].pending == 0
    assert states["fr-2020-a"].need == 8


def test_une_classe_a_un_exemplaire_est_prioritaire(db, tmp_path):
    """N=1 est MESURÉ pire que N=0 → poids doublé, à besoin égal."""
    states = {c.class_id: c for c in _all_states(db, tmp_path)}
    un = states["fr-2021-a"]
    assert un.have == 1 and un.need == 7
    assert un.weight == pytest.approx(14.0)      # 7 × 2,0
    assert states["fr-2020-a"].weight == pytest.approx(8.0)   # 8 × 1,0


def test_min_need_empeche_de_viser_un_seul_exemplaire(db, tmp_path):
    """Un groupe dont toutes les classes ne manquent que de 1 n'est pas financé."""
    conn = sqlite3.connect(db)
    for i in range(7):  # fr-2020-a passe à 7 exemplaires → need = 1
        conn.execute("INSERT INTO dino_class_references VALUES "
                     "('2eur_all','fr-2020-a','fr-2020-a',?,'fps')", (f"c{i}",))
    for i in range(8):  # fr-2020-b devient pleine
        conn.execute("INSERT INTO dino_class_references VALUES "
                     "('2eur_all','fr-2020-b','fr-2020-b',?,'fps')", (f"d{i}",))
    conn.commit()
    conn.close()
    a = _alloc(db, tmp_path)
    assert "FR/2020" not in [g.key.label() for g in a.planned]
    # ... et avec --min-need 1, le même groupe redevient éligible.
    a1 = _alloc(db, tmp_path, min_need=1)
    assert "FR/2020" in [g.key.label() for g in a1.planned]


# ── 4. Le grain d'allocation ─────────────────────────────────────────────────


def _all_states(db: Path, tmp_path: Path):
    conn = alloc.connect_ro(db)
    try:
        return alloc.build_class_states(
            conn, datasets_dir=tmp_path / "no-datasets")
    finally:
        conn.close()


def test_grain_banque_un_design_group_standard_est_une_seule_classe(db, tmp_path):
    ids = {c.class_id for c in _all_states(db, tmp_path)}
    assert "es-1999-std" in ids          # le représentant du groupe
    assert "es-2010-std" not in ids      # son frère n'est PAS une classe
    assert len(ids) == 6


def test_un_standard_va_dans_le_groupe_pays_sans_annee(db, tmp_path):
    states = {c.class_id: c for c in _all_states(db, tmp_path)}
    assert alloc.group_key_for(states["es-1999-std"]) == \
        alloc.DiscoveryGroupKey("ES", None)
    assert alloc.group_key_for(states["fr-2020-a"]) == \
        alloc.DiscoveryGroupKey("FR", 2020)


def test_les_deux_commemos_dun_pays_annee_partagent_un_groupe(db, tmp_path):
    a = _alloc(db, tmp_path)
    fr2020 = [g for g in a.planned if g.key.label() == "FR/2020"]
    assert len(fr2020) == 1
    assert fr2020[0].n_classes_needing == 2
    assert fr2020[0].need == 16          # deux classes à zéro, cible 8


def test_le_standard_coute_plus_cher_que_le_commemo(db, tmp_path):
    assert alloc.DiscoveryGroupKey("ES", None).cost == alloc.COST_PER_STANDARD_GROUP
    assert alloc.DiscoveryGroupKey("FR", 2020).cost == alloc.COST_PER_COMMEMO_GROUP
    assert alloc.COST_PER_STANDARD_GROUP > alloc.COST_PER_COMMEMO_GROUP


def test_le_score_classe_par_deficit_par_appel(db, tmp_path):
    a = _alloc(db, tmp_path)
    scores = [g.score for g in a.planned]
    assert scores == sorted(scores, reverse=True)
    assert a.planned[0].key.label() == "FR/2020"   # 16 besoins pour 130 appels


# ── 5. Budget et cooldown ────────────────────────────────────────────────────


def test_le_budget_borne_le_plan(db, tmp_path):
    a = _alloc(db, tmp_path, budget=130)
    assert len(a.planned) == 1
    assert a.cost <= 130
    assert a.deferred_budget


def test_max_groups_borne_le_plan(db, tmp_path):
    a = _alloc(db, tmp_path, max_groups=1)
    assert len(a.planned) == 1


def test_marge_de_securite_alignee_sur_le_preflight_cli(db):
    assert alloc.safe_budget(5000) == int(5000 / 1.3)
    assert alloc.QUOTA_SAFETY_FACTOR == 1.3


def test_un_groupe_cherche_recemment_est_ecarte(db, tmp_path):
    """Cooldown = expected_cadence_days du registre eBay (30 j)."""
    from sources.ebay.marketplaces import DISCOVERY_MARKETPLACES
    from sources.ebay.queries import build_group_query

    q = build_group_query(2.0, "FR", 2020,
                          query_lang=DISCOVERY_MARKETPLACES[0].query_lang).q
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO discovery_searches VALUES (?, '2026-08-15 10:00:00')",
                 (q,))
    conn.commit()
    conn.close()
    a = _alloc(db, tmp_path)
    assert "FR/2020" in [g.key.label() for g in a.skipped_cooldown]
    assert "FR/2020" not in [g.key.label() for g in a.planned]
    # Hors cooldown, il revient.
    a2 = _alloc(db, tmp_path, cooldown_days=1)
    assert "FR/2020" in [g.key.label() for g in a2.planned]


def test_un_groupe_empty_upstream_est_ecarte(db, tmp_path):
    conn = sqlite3.connect(db)
    for eid in ("fr-2020-a", "fr-2020-b"):
        conn.execute(
            "INSERT INTO coin_source_status VALUES (?, 'ebay_browse', 'empty_upstream')",
            (eid,))
    conn.commit()
    conn.close()
    a = _alloc(db, tmp_path)
    assert "FR/2020" in [g.key.label() for g in a.skipped_empty_upstream]


# ── 6. Câblage réel du chemin de base ────────────────────────────────────────


def test_la_base_par_defaut_nest_pas_la_base_perimee(monkeypatch, tmp_path):
    """`state/eurio.db` est PÉRIMÉE : le défaut doit être la réplique."""
    monkeypatch.delenv("EURIO_DB_PATH", raising=False)
    assert alloc.default_db().name == "eurio.replica.db"
    monkeypatch.setenv("EURIO_DB_PATH", str(tmp_path / "ailleurs.db"))
    assert alloc.default_db() == tmp_path / "ailleurs.db"


# ── 6. Les gardes du brûlage, deuxième couche (défauts S2 et S4) ─────────────


def test_dry_run_et_execute_ensemble_sont_refuses(db, tmp_path, monkeypatch):
    """S2 : `--dry-run` n'était lu NULLE PART (`action='store_true',
    default=True`, jamais consulté) — `--dry-run --execute --yes` brûlait le
    quota en affichant qu'on ne le brûlait pas. Les deux modes sont désormais
    exclusifs : argparse sort en 2 avant toute lecture de base."""
    def _boom(cmd):  # pragma: no cover - doit ne jamais être appelé
        raise AssertionError(f"lancé sous --dry-run : {cmd}")

    monkeypatch.setattr(alloc, "_subprocess_runner", _boom)
    with pytest.raises(SystemExit) as e:
        alloc.main(["--db", str(db), "--budget", "10000", "--today", "2026-08-20",
                    "--dry-run", "--execute", "--yes"])
    assert e.value.code == 2


def test_le_quota_reel_est_relu_entre_deux_vagues(db, tmp_path, monkeypatch):
    """S4 : le budget n'était calculé qu'UNE fois, avant la première vague, et
    rien ne relisait `api_call_log` ensuite. Le préflight de `sources.cli` ne
    rattrape pas : il estime sur `source_runs.n_calls` (3 pour 740 appels
    réels) et rend `estimate=8` pour une vague budgétée 1040. La seule mesure
    vraie est le compteur, relu à chaque vague."""
    a = _alloc(db, tmp_path)
    assert len(a.planned) >= 2
    restants = iter([10_000, 0])
    monkeypatch.setattr(alloc, "remaining_quota_today", lambda: next(restants))
    calls: list[list[str]] = []
    rc = alloc.execute(a, groups_per_run=1, runner=lambda c: calls.append(c) or 0)

    assert rc == 1                      # arrêt, pas un succès silencieux
    assert len(calls) == 1              # la seconde vague n'est jamais partie


def test_le_quota_relu_ne_bloque_pas_quand_il_reste_de_la_marge(db, tmp_path, monkeypatch):
    """Contre-épreuve : le garde ne doit pas arrêter un plan finançable."""
    a = _alloc(db, tmp_path)
    monkeypatch.setattr(alloc, "remaining_quota_today", lambda: 10_000)
    calls: list[list[str]] = []
    rc = alloc.execute(a, groups_per_run=1, runner=lambda c: calls.append(c) or 0)
    assert rc == 0 and len(calls) == len(a.planned)


# ── 6. Le cadrage par pays (lot 5 — la moitié ACHETER de `/besoin`) ──────────


def test_le_filtre_pays_cadre_le_plan_sans_rien_changer_dautre(db, tmp_path):
    """`countries=` ne garde que les groupes du pays — mêmes coûts, même score.

    La moitié ACHETER propose « le plan LU » : sans ce cadrage, le lien
    ouvrirait le plan COMPLET sous un libellé qui promet un pays. C'est le même
    défaut que le badge qui annonce 4 au-dessus d'une file qui en sert 3.
    """
    complet = _alloc(db, tmp_path)
    fr = _alloc(db, tmp_path, countries=frozenset({"FR"}))

    assert {g.key.country for g in fr.planned} == {"FR"}
    # Les groupes FR du plan complet sont exactement ceux du plan cadré.
    assert [g.key.label() for g in fr.planned] == [
        g.key.label() for g in complet.planned if g.key.country == "FR"
    ]
    # Le coût d'un groupe ne dépend pas du cadrage.
    assert fr.cost == sum(g.cost for g in complet.planned if g.key.country == "FR")
    assert fr.cost < complet.cost


def test_un_pays_inconnu_rend_un_plan_vide_jamais_le_plan_complet(db, tmp_path):
    """Un périmètre qui rate se ferme, il ne s'élargit pas en silence.

    Sans ce refus, une faute de frappe dans le code pays financerait TOUTE
    l'Europe en croyant financer Saint-Marin.
    """
    a = _alloc(db, tmp_path, countries=frozenset({"ZZ"}))
    assert a.planned == [] and a.cost == 0
    assert a.review_covered == []


def test_le_cadrage_pays_passe_par_la_ligne_de_commande(db, tmp_path, capsys):
    """`--country` existe vraiment : c'est la commande affichée par l'écran."""
    rc = alloc.main(["--db", str(db), "--budget", "10000", "--today", "2026-08-20",
                     "--country", "fr", "--format", "json"])
    assert rc == 0
    import json as _json
    payload = _json.loads(capsys.readouterr().out)
    assert payload["groups"], "le plan FR ne doit pas être vide"
    assert {g["country"] for g in payload["groups"]} == {"FR"}
