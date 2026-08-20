"""Tests du générateur de plan de capture (P5).

Ce que ces tests protègent — dans l'ordre d'importance :

1. le script **n'écrit jamais** dans la base qu'il lit (piège n°1 du repo) ;
2. les invariants anti-corrélation du plan (une classe vue dans plusieurs
   sessions, sur plusieurs fonds ; toutes les strates dans chaque session) ;
3. la classification en strates, qui décide de tout le reste.
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from scripts import build_scan_prescription as bsp  # noqa: E402

_DDL = """
CREATE TABLE coins (
  eurio_id TEXT PRIMARY KEY, country TEXT, country_name TEXT, year INTEGER,
  face_value REAL, theme TEXT, is_commemorative INTEGER DEFAULT 0,
  numista_id INTEGER, design_group_id TEXT, personal_owned INTEGER DEFAULT 0
);
CREATE TABLE dino_class_references (
  anchors_kind TEXT, class_id TEXT, eurio_id TEXT, asset_id TEXT, method TEXT
);
CREATE TABLE image_assets (
  id TEXT PRIMARY KEY, eurio_id TEXT, training_eligible INTEGER DEFAULT 0
);
"""


def _fixture_db(tmp_path: Path) -> Path:
    """4 classes possédées, une par strate."""
    db = tmp_path / "fake.db"
    conn = sqlite3.connect(db)
    conn.executescript(_DDL)
    coins = [
        ("fr-riche", "FR", 2010, 1, "dg-a"),
        ("de-moyenne", "DE", 2011, 2, "dg-b"),
        ("it-canonique", "IT", 2012, 3, "dg-c"),
        ("be-horsbanque", "BE", 2013, 4, "dg-d"),
        ("be-frere", "BE", 2014, 5, "dg-d"),  # pas possédée, mais en banque
        # Ni en banque, ni de frère en banque : RIEN ne peut la reconnaître.
        ("nl-orpheline", "NL", 2015, 6, "dg-e"),
    ]
    for eid, country, year, nid, dg in coins:
        conn.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, numista_id,"
            " design_group_id, personal_owned, theme) VALUES (?,?,?,2.0,?,?,?,?)",
            (eid, country, year, nid, dg, 0 if eid == "be-frere" else 1, "x"),
        )
    refs = [("fr-riche", 12), ("de-moyenne", 3), ("it-canonique", 0),
            ("be-frere", 1)]
    for class_id, n_fps in refs:
        conn.execute(
            "INSERT INTO dino_class_references VALUES ('2eur_all',?,?,NULL,"
            "'canonical')", (class_id, class_id),
        )
        for k in range(n_fps):
            conn.execute(
                "INSERT INTO dino_class_references VALUES ('2eur_all',?,?,?,'fps')",
                (class_id, class_id, f"{class_id}-a{k}"),
            )
    conn.commit()
    conn.close()
    return db


def _load(tmp_path: Path) -> list[bsp.Classe]:
    conn = bsp._open_readonly(_fixture_db(tmp_path))
    try:
        return bsp.load_classes(conn, "2eur_all")
    finally:
        conn.close()


def test_strates(tmp_path):
    """``hors_banque`` = absente de la banque MAIS avec un frère dedans.

    Sans frère, la classe n'est reconnaissable par rien : c'est ``orpheline``.
    Avant correctif, ``_strate_of`` ne lisait pas ``n_siblings_in_bank`` et
    rangeait ``nl-orpheline`` dans ``hors_banque`` — la strate censée mesurer
    la maille eq se retrouvait chargée d'échecs structurels.
    """
    by_id = {c.eurio_id: c.strate for c in _load(tmp_path)}
    assert by_id == {
        "fr-riche": "riche",
        "de-moyenne": "moyenne",
        "it-canonique": "canonique",
        "be-horsbanque": "hors_banque",
        "nl-orpheline": "orpheline",
    }


def test_orpheline_est_hors_du_plan_par_defaut(tmp_path):
    """Photographier une pièce que rien ne peut reconnaître ne mesure rien."""
    db = _fixture_db(tmp_path)
    out = tmp_path / "plan.csv"
    bsp.main(["--db", str(db), "--out", str(out)])
    rows = list(csv.DictReader(out.open(encoding="utf-8"), delimiter=";"))
    assert "nl-orpheline" not in {r["eurio_id"] for r in rows}
    assert "orpheline" not in {r["strate"] for r in rows}
    # …et elle n'est pas non plus dans la cohorte à faire résoudre.
    cohorte = out.with_suffix(".cohorte.csv").read_text(encoding="utf-8")
    assert "nl-orpheline" not in cohorte


def test_orpheline_entre_au_plan_si_on_la_nomme(tmp_path):
    """L'exclusion est un défaut, pas une interdiction : elle se lève à la main."""
    db = _fixture_db(tmp_path)
    out = tmp_path / "plan.csv"
    bsp.main(["--db", str(db), "--out", str(out),
              "--classes-par-strate", "orpheline=all"])
    rows = list(csv.DictReader(out.open(encoding="utf-8"), delimiter=";"))
    assert {r["strate"] for r in rows if r["eurio_id"] == "nl-orpheline"} == {
        "orpheline"
    }


def test_les_ecartees_sont_annoncees(tmp_path, capsys):
    """Un quota qui écarte des classes le DIT — sinon « 7 pièces manquantes »
    se découvre en fin de séance photo."""
    db = _fixture_db(tmp_path)
    bsp.main(["--db", str(db), "--out", str(tmp_path / "plan.csv")])
    out = capsys.readouterr().out
    assert "écartées" in out
    assert "1 orpheline" in out


def test_db_par_defaut_honore_eurio_db_path(tmp_path, monkeypatch):
    """Le chemin de base ne peut plus être codé en dur (piège n°1 du repo).

    Avant correctif : ``DEFAULT_DB = ML_DIR/'state'/'eurio.replica.db'``, donc
    ``EURIO_DB_PATH`` ignoré et une AUTRE base lue en silence.
    """
    db = _fixture_db(tmp_path)
    monkeypatch.setenv("EURIO_DB_PATH", str(db))
    assert bsp.default_db() == db
    # …et le point d'entrée l'utilise vraiment, sans --db : le plan produit
    # ne contient QUE les classes de la fixture, pas celles d'une autre base.
    out = tmp_path / "plan.csv"
    assert bsp.main(["--out", str(out)]) == 0
    ids = {r["eurio_id"] for r in csv.DictReader(out.open(encoding="utf-8"),
                                                 delimiter=";")}
    assert ids == {"fr-riche", "de-moyenne", "it-canonique", "be-horsbanque"}


def test_aucun_chemin_de_base_code_en_dur(tmp_path, monkeypatch):
    """Le module ne doit plus exposer de constante de base résolue à l'import."""
    src = Path(bsp.__file__).read_text(encoding="utf-8")
    assert "DEFAULT_DB" not in src
    monkeypatch.setenv("EURIO_DB_PATH", str(tmp_path / "ailleurs.db"))
    assert bsp.default_db() == tmp_path / "ailleurs.db"


def test_hors_banque_voit_son_frere(tmp_path):
    """La pièce hors banque reste scorable en maille eq : son design_group a
    un membre dans la banque. C'est ce qui justifie de l'inclure au plan."""
    c = {x.eurio_id: x for x in _load(tmp_path)}["be-horsbanque"]
    assert c.n_siblings_in_bank == 1


def test_connexion_est_read_only(tmp_path):
    db = _fixture_db(tmp_path)
    conn = bsp._open_readonly(db)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("UPDATE coins SET personal_owned = 0")
    finally:
        conn.close()


def test_le_script_ne_touche_pas_la_base(tmp_path):
    db = _fixture_db(tmp_path)
    before = db.read_bytes()
    out = tmp_path / "plan.csv"
    bsp.main(["--db", str(db), "--out", str(out), "--cells-per-session", "6"])
    assert db.read_bytes() == before
    assert not (tmp_path / "fake.db-wal").exists()


def test_quotas_par_strate(tmp_path):
    classes = _load(tmp_path)
    kept = bsp.select_classes(
        classes, bsp._parse_quotas("riche=1,moyenne=0,canonique=1,hors_banque=0"), 1
    )
    assert sorted(c.strate for c in kept) == ["canonique", "riche"]


def test_quota_inconnu_echoue(tmp_path):
    with pytest.raises(SystemExit):
        bsp._parse_quotas("bidon=3")


def test_invariants_du_plan(tmp_path):
    db = _fixture_db(tmp_path)
    out = tmp_path / "plan.csv"
    bsp.main(["--db", str(db), "--out", str(out), "--cells-per-session", "6"])
    rows = list(csv.DictReader(out.open(encoding="utf-8"), delimiter=";"))

    assert len(rows) == 4 * len(bsp.DEFAULT_CONDITIONS)

    sessions_par_classe: dict[str, set[str]] = {}
    fonds_par_classe: dict[str, set[str]] = {}
    for r in rows:
        sessions_par_classe.setdefault(r["eurio_id"], set()).add(r["session"])
        fonds_par_classe.setdefault(r["eurio_id"], set()).add(r["fond"])

    # Une classe n'est jamais enfermée dans une seule ambiance…
    assert all(len(v) >= 2 for v in sessions_par_classe.values())
    # …ni sur un seul fond (le fond ne doit pas devenir un indice de la classe).
    assert all(len(v) >= 2 for v in fonds_par_classe.values())
    # …et on ne ressort pas une pièce plus de --passes fois.
    assert all(len(v) <= 2 for v in sessions_par_classe.values())

    # Le régime pauvre est plus profond que le régime riche.
    par_strate = {r["strate"]: int(r["n_captures"]) for r in rows}
    assert par_strate["canonique"] > par_strate["riche"]


def test_cohorte_csv_est_relisible_par_le_resolver(tmp_path):
    from store.class_resolver import coin_refs_from_cohort_csv

    db = _fixture_db(tmp_path)
    out = tmp_path / "plan.csv"
    bsp.main(["--db", str(db), "--out", str(out)])
    refs = coin_refs_from_cohort_csv(out.with_suffix(".cohorte.csv"))
    assert len(refs) == 4
    assert {r.eurio_id for r in refs} == {
        "fr-riche", "de-moyenne", "it-canonique", "be-horsbanque"
    }


def test_deterministe(tmp_path):
    db = _fixture_db(tmp_path)
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    bsp.main(["--db", str(db), "--out", str(a)])
    bsp.main(["--db", str(db), "--out", str(b)])
    assert a.read_text() == b.read_text()
