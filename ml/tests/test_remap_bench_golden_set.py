"""Tests du remapping du golden set de bench (`scripts/remap_bench_golden_set`).

Ce qui doit être prouvé ici, parce que ça se casse en silence :

* la **fusion** d'un dossier mort dans une cible déjà présente n'a lieu QUE si
  les captures sont octet-pour-octet identiques ;
* dès qu'un octet diverge, le script **refuse tout le run** (aucun renommage
  partiel, pas de « best effort ») ;
* le run est **idempotent** : rejoué, il ne fait plus rien et ne duplique pas
  le journal ;
* le **cas belge** (photo 2011, aucune pièce belge 2010-2013 au référentiel)
  est rattaché au représentant du groupe et marqué `needs_rematch` — jamais
  silencieusement `deterministic` ;
* le journal ne peut pas atteindre le canonique aujourd'hui : l'écriture est
  refusée, pas déviée vers une base locale.
"""

from __future__ import annotations

import sqlite3

import pytest

from scripts import remap_bench_golden_set as R

# ── helpers ───────────────────────────────────────────────────────────────

SHOTS = ("bright_plain.jpg", "close_plain.jpg", "daylight_plain.jpg")


def _make_dir(root, name, payload=b"CAPTURE"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    for shot in SHOTS:
        (d / shot).write_bytes(payload + shot.encode())
    return d


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "eval_real_norm"


# ── la table elle-même ────────────────────────────────────────────────────


def test_mapping_covers_14_dead_slugs_and_11_targets():
    assert len(R.MAPPING) == 14
    assert len({m.new_eurio_id for m in R.MAPPING}) == 11
    assert len({m.old_eurio_id for m in R.MAPPING}) == 14


def test_two_rows_contradict_their_folder_name():
    """Les deux 🔴 du doc : le nom de dossier ment sur le millésime."""
    fr = R.by_old("fr-2eur-standard-2007")
    assert fr.new_eurio_id == "fr-1999-2eur-standard-1st-map"
    assert "2000" in fr.reason
    be = R.by_old("be-2008-2eur-standard")
    assert "2011" in be.reason


# ── le cas belge ──────────────────────────────────────────────────────────


def test_belgian_case_attached_to_group_representative_and_flagged():
    be = R.by_old("be-2008-2eur-standard")
    # rattaché au représentant 2e portrait du groupe be-2euro-albert-ii-t2
    assert be.new_eurio_id == (
        "be-2008-2eur-standard-albert-ii-2nd-map-2nd-type-2nd-portrait"
    )
    assert be.design_group == "be-2euro-albert-ii-t2"
    # ⚠️ pas de silence : la pièce exacte n'existe pas → à re-juger
    assert be.resolution == "needs_rematch"
    assert be.class_level_only is True
    # et tous les autres sont bien déterministes
    others = [m for m in R.MAPPING if m.old_eurio_id != "be-2008-2eur-standard"]
    assert {m.resolution for m in others} == {"deterministic"}
    assert not any(m.class_level_only for m in others)


def test_belgian_case_is_visible_in_the_report(root, capsys):
    _make_dir(root, "be-2008-2eur-standard")
    R.run(root=root, apply=False, journal_conn=None)
    out = capsys.readouterr().out
    assert "CAS BELGE" in out
    assert "needs_rematch" in out


# ── réconciliation des dossiers ───────────────────────────────────────────


def test_rename_when_target_absent(root):
    _make_dir(root, "mt-2008-2eur-standard")
    actions = R.plan_filesystem(root)
    a = next(a for a in actions if a.old == "mt-2008-2eur-standard")
    assert a.kind == "rename"
    R.apply_filesystem(root, actions)
    assert (root / "mt-2008-2eur-standard-2nd-map").is_dir()
    assert not (root / "mt-2008-2eur-standard").exists()


def test_merge_when_target_present_and_identical(root):
    _make_dir(root, "it-2016-2eur-550-years-since-the-death-of-donatello")
    _make_dir(root, "it-2016-2eur-550th-anniversary-of-the-death-of-donatello")
    actions = R.plan_filesystem(root)
    a = next(
        a
        for a in actions
        if a.old == "it-2016-2eur-550-years-since-the-death-of-donatello"
    )
    assert a.kind == "merge"
    R.apply_filesystem(root, actions)
    assert not (root / "it-2016-2eur-550-years-since-the-death-of-donatello").exists()
    assert (root / "it-2016-2eur-550th-anniversary-of-the-death-of-donatello").is_dir()


def test_three_duplicate_pairs_collapse_into_one_target(root):
    for name in ("at-2002-2eur-standard", "at-2eur-standard-2002"):
        _make_dir(root, name)
    actions = R.plan_filesystem(root)
    R.apply_filesystem(root, actions)
    assert (root / "at-2002-2eur-standard-1st-map").is_dir()
    assert not (root / "at-2002-2eur-standard").exists()
    assert not (root / "at-2eur-standard-2002").exists()
    assert sorted(p.name for p in (root / "at-2002-2eur-standard-1st-map").iterdir()) == list(SHOTS)


def test_refuses_when_sha256_diverge(root):
    _make_dir(root, "it-2016-2eur-550-years-since-the-death-of-donatello", b"A")
    _make_dir(root, "it-2016-2eur-550th-anniversary-of-the-death-of-donatello", b"B")
    with pytest.raises(R.RemapRefused) as exc:
        R.plan_filesystem(root)
    assert "sha256" in str(exc.value)


def test_refuses_when_file_sets_differ(root):
    _make_dir(root, "it-2016-2eur-550-years-since-the-death-of-donatello")
    tgt = _make_dir(root, "it-2016-2eur-550th-anniversary-of-the-death-of-donatello")
    (tgt / "extra_shot.jpg").write_bytes(b"x")
    with pytest.raises(R.RemapRefused):
        R.plan_filesystem(root)


def test_refusal_leaves_the_filesystem_untouched(root):
    _make_dir(root, "mt-2008-2eur-standard")
    _make_dir(root, "it-2016-2eur-550-years-since-the-death-of-donatello", b"A")
    _make_dir(root, "it-2016-2eur-550th-anniversary-of-the-death-of-donatello", b"B")
    with pytest.raises(R.RemapRefused):
        R.run(root=root, apply=True, journal_conn=None)
    # aucun renommage partiel : le dossier sain n'a pas bougé
    assert (root / "mt-2008-2eur-standard").is_dir()
    assert not (root / "mt-2008-2eur-standard-2nd-map").exists()


def test_dry_run_writes_nothing(root):
    _make_dir(root, "mt-2008-2eur-standard")
    R.run(root=root, apply=False, journal_conn=None)
    assert (root / "mt-2008-2eur-standard").is_dir()
    assert not (root / "mt-2008-2eur-standard-2nd-map").exists()


def test_filesystem_is_idempotent(root):
    _make_dir(root, "mt-2008-2eur-standard")
    _make_dir(root, "at-2002-2eur-standard")
    _make_dir(root, "at-2eur-standard-2002")
    R.apply_filesystem(root, R.plan_filesystem(root))
    before = sorted(p.name for p in root.iterdir())
    actions = R.plan_filesystem(root)
    assert not [a for a in actions if a.kind in ("rename", "merge")]
    R.apply_filesystem(root, actions)
    assert sorted(p.name for p in root.iterdir()) == before


# ── journal `eurio_id_migrations` ─────────────────────────────────────────


@pytest.fixture()
def journal_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE eurio_id_migrations (
             id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL, kind TEXT NOT NULL,
             old_eurio_id TEXT NOT NULL, new_eurio_id TEXT,
             resolution TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
             reason TEXT, decided_by TEXT,
             created_at TEXT NOT NULL DEFAULT (datetime('now')))"""
    )
    return conn


def test_journal_rows_match_the_schema_contract(journal_conn):
    R.apply_journal(journal_conn, R.plan_journal(journal_conn))
    rows = journal_conn.execute(
        "SELECT * FROM eurio_id_migrations ORDER BY id"
    ).fetchall()
    assert len(rows) == 14
    assert {r["kind"] for r in rows} == {"rename"}
    assert {r["status"] for r in rows} == {"pending"}
    assert {r["decided_by"] for r in rows} == {R.DECIDED_BY}
    assert {r["batch_id"] for r in rows} == {R.BATCH_ID}
    assert all(r["reason"] for r in rows)


def test_journal_is_idempotent(journal_conn):
    R.apply_journal(journal_conn, R.plan_journal(journal_conn))
    pending = R.plan_journal(journal_conn)
    assert pending == []
    R.apply_journal(journal_conn, pending)
    (n,) = journal_conn.execute("SELECT count(*) FROM eurio_id_migrations").fetchone()
    assert n == 14


def test_journal_does_not_touch_the_belgian_2017_split(journal_conn):
    journal_conn.execute(
        "INSERT INTO eurio_id_migrations "
        "(batch_id, kind, old_eurio_id, new_eurio_id, resolution, status) "
        "VALUES ('be-2017-split-9281d080','retire',"
        "'be-2017-2eur-200-years-ghent-university',NULL,'needs_rematch','pending')"
    )
    R.apply_journal(journal_conn, R.plan_journal(journal_conn))
    (n,) = journal_conn.execute(
        "SELECT count(*) FROM eurio_id_migrations WHERE batch_id='be-2017-split-9281d080'"
    ).fetchone()
    assert n == 1


def test_batch_id_is_stable_not_random():
    """Un uuid4 casserait l'idempotence : le rejeu doit reconnaître son batch."""
    assert R.BATCH_ID == R.BATCH_ID
    assert "2026-08-17" in R.BATCH_ID


def test_emitted_sql_is_replayable(journal_conn):
    sql = R.emit_sql(R.plan_journal(journal_conn))
    journal_conn.executescript(sql)
    (n,) = journal_conn.execute(
        "SELECT count(*) FROM eurio_id_migrations WHERE batch_id=?", (R.BATCH_ID,)
    ).fetchone()
    assert n == 14


# ── destination de l'écriture (Direction A) ───────────────────────────────


def test_journal_write_refuses_without_a_canonical_route(monkeypatch, root):
    """Aucune route /ingest n'expose eurio_id_migrations : sous flip, l'écriture
    du journal doit refuser, JAMAIS retomber sur une base locale."""
    monkeypatch.setenv("EURIO_DB_READONLY", "1")
    _make_dir(root, "mt-2008-2eur-standard")
    with pytest.raises(R.CanonicalUnreachable) as exc:
        R.run(root=root, apply=True, scope="journal")
    assert "/ingest" in str(exc.value)
