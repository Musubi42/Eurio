"""Le hold-out d'évaluation — marqué en base, honoré par les DEUX collectes.

Chantier `juge-et-banc`, étape 2 (migration 0014, colonne
``image_assets.eval_corpus``).

Ce que ces tests verrouillent, et pourquoi chacun existe :

1. **la colonne naît partout** — dans `schema.sql` (base neuve) ET via
   `_ensure_column` (base antérieure). Le contrat de miroir a trois branches et
   se tromper de branche est muet jusqu'au premier `no such column` ;
2. **les DEUX collectes l'honorent.** Il n'y a pas de point unique en amont :
   `_ebay_training_sources` (ArcFace, et par ricochet le seed du préflight) et
   `_candidate_crops_for_class` (ancres DINO) écrivent chacune leur prédicat.
   Un test par voie, sinon un correctif d'une seule passe au vert ;
3. **le marquage ne s'écrase pas en silence** — changer un crop de corpus
   invaliderait rétroactivement une mesure publiée ;
4. **la sélection est déterministe** — sans quoi « rejouable » est un mot.

Run: `.venv/bin/python -m pytest ml/tests/test_eval_holdout.py -q`
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest  # noqa: E402

from scripts.select_eval_holdout import (  # noqa: E402
    quantiles_moitie_haute,
    selectionner,
)
from store import Store  # noqa: E402
from store.eval_corpus import apply_ingest_eval_corpus  # noqa: E402


# ─── 1. La colonne existe, des deux côtés du contrat de miroir ───────────────


def test_une_base_neuve_nait_avec_eval_corpus(tmp_path):
    """`schema.sql` (rejoué à chaque ouverture) déclare la colonne ET son index."""
    store = Store(tmp_path / "neuve.db")
    conn = store._connection()  # noqa: SLF001
    cols = {r[1] for r in conn.execute("PRAGMA table_info(image_assets)")}
    assert "eval_corpus" in cols
    idx = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_image_assets_eval_corpus" in idx


def test_une_base_anterieure_rattrape_eval_corpus(tmp_path):
    """`_ensure_column` : une base créée AVANT 0014 gagne la colonne à
    l'ouverture. Sans ça l'index partiel de `schema.sql` échouerait en
    « no such column » avant que quoi que ce soit d'autre tourne."""
    # Une VRAIE base d'avant 0014 : le schéma courant amputé de la colonne et de
    # son index. Fabriquer un `image_assets` de fantaisie ne prouverait rien —
    # ce qu'on veut exercer, c'est l'ordre pre-bootstrap → executescript.
    schema = (ML_DIR / "state" / "schema.sql").read_text(encoding="utf-8")
    lignes = [
        ligne for ligne in schema.splitlines()
        if "eval_corpus" not in ligne
    ]
    db = tmp_path / "ancienne.db"
    brut = sqlite3.connect(db)
    brut.executescript("\n".join(lignes).replace(
        "CREATE INDEX IF NOT EXISTS idx_image_assets_eval_corpus\n", ""))
    brut.commit()
    brut.close()
    assert "eval_corpus" not in {
        r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(image_assets)")
    }

    conn = Store(db)._connection()  # noqa: SLF001
    cols = {r[1] for r in conn.execute("PRAGMA table_info(image_assets)")}
    assert "eval_corpus" in cols, (
        "une base antérieure à 0014 doit gagner la colonne par _ensure_column")


def test_la_migration_0014_est_bien_un_alter_et_un_index():
    """Garde nommée : le test paramétré du miroir passerait aussi si 0014 ne
    déclarait plus rien du tout (elle est dans `exclues`)."""
    sql = (ML_DIR / "serving" / "migrations"
           / "0014_eval_corpus_holdout.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE image_assets ADD COLUMN eval_corpus TEXT" in sql
    assert "idx_image_assets_eval_corpus" in sql
    schema = (ML_DIR / "state" / "schema.sql").read_text(encoding="utf-8")
    assert "eval_corpus" in schema
    assert "idx_image_assets_eval_corpus" in schema


# ─── 2. Les DEUX collectes d'entraînement honorent le marquage ───────────────


def _monte_crops(conn, *, eurio_id="c", n=4, source="ebay"):
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref) VALUES ('si1', ?, 'r1')",
        (source,),
    )
    for i in range(n):
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, eurio_id, "
            "resolution_status, face, denom, training_eligible, storage_status, "
            "storage_path) VALUES (?, 'si1', ?, ?, 'manual', 'obverse', '2eur', 1, "
            "'present', ?)",
            (f"a{i}", i, eurio_id, f"ebay/si1/a{i}.png"),
        )
    conn.commit()


def test_arcface_ne_collecte_pas_un_crop_deval(tmp_path, monkeypatch):
    """Voie ArcFace (`_ebay_training_sources`) — et donc aussi le seed que le
    préflight contrôle, les deux partageant `real_training_sources`."""
    import shared.storage.local_cache as lc
    from training.iteration_augmentations import _ebay_training_sources

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _monte_crops(conn)
    conn.execute(
        "UPDATE image_assets SET eval_corpus = 'corpus-X' WHERE id = 'a2'")
    conn.commit()

    fichiers = {}
    for i in range(4):
        p = tmp_path / f"a{i}.png"
        p.write_bytes(b"png")
        fichiers[f"ebay/si1/a{i}.png"] = p
    monkeypatch.setattr(lc, "local_path", lambda bucket, key: fichiers[key])

    noms = {p.stem for p in _ebay_training_sources("c", store)}
    assert noms == {"a0", "a1", "a3"}, "a2 est réservé à l'éval — il ne doit pas entrer"


def test_les_ancres_dino_ne_prennent_pas_un_crop_deval(tmp_path):
    """Voie DINO (`_candidate_crops_for_class`). Une ancre bâtie sur un crop
    d'éval le reconnaîtrait ensuite à similarité 1,0 avec lui-même."""
    from training.foundation.anchors import _candidate_crops_for_class

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _monte_crops(conn)
    conn.execute(
        "UPDATE image_assets SET eval_corpus = 'corpus-X' WHERE id = 'a2'")
    conn.commit()
    conn.row_factory = sqlite3.Row

    ids = {c["id"] for c in _candidate_crops_for_class(conn, ["c"])}
    assert ids == {"a0", "a1", "a3"}, "a2 est réservé à l'éval — pas d'ancre dessus"


# ─── 3. Le marquage ne s'écrase jamais en silence ────────────────────────────


def test_le_marquage_est_idempotent_et_refuse_de_changer_de_corpus(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _monte_crops(conn, n=2)

    r1 = apply_ingest_eval_corpus(conn, [{"asset_id": "a0", "eval_corpus": "X"}])
    assert (r1["updated"], r1["skipped"], r1["conflict"], r1["missing"]) == (1, 0, [], [])

    # Rejouer le MÊME corpus ne change rien (idempotent).
    r2 = apply_ingest_eval_corpus(conn, [{"asset_id": "a0", "eval_corpus": "X"}])
    assert (r2["updated"], r2["skipped"]) == (0, 1)

    # Un AUTRE corpus est refusé, pas écrit : il invaliderait une mesure publiée.
    r3 = apply_ingest_eval_corpus(conn, [{"asset_id": "a0", "eval_corpus": "Y"}])
    assert r3["conflict"] == ["a0"] and r3["updated"] == 0
    assert conn.execute(
        "SELECT eval_corpus FROM image_assets WHERE id='a0'").fetchone()[0] == "X"

    # Retrait : jamais par omission — il faut nommer le corpus qu'on croit retirer.
    r4 = apply_ingest_eval_corpus(conn, [{"asset_id": "a0", "eval_corpus": None}])
    assert r4["conflict"] == ["a0"]
    r5 = apply_ingest_eval_corpus(
        conn, [{"asset_id": "a0", "eval_corpus": None, "expect": "X"}])
    assert r5["updated"] == 1
    assert conn.execute(
        "SELECT eval_corpus FROM image_assets WHERE id='a0'").fetchone()[0] is None

    # Asset inconnu → `missing`, jamais écrit.
    r6 = apply_ingest_eval_corpus(conn, [{"asset_id": "fantome", "eval_corpus": "X"}])
    assert r6["missing"] == ["fantome"] and r6["updated"] == 0


def test_le_marquage_ne_touche_pas_training_eligible(tmp_path):
    """`training_eligible` porte le verdict de la REVIEW, `eval_corpus` un RÔLE.
    Les confondre ferait disparaître les crops d'éval des compteurs de review."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _monte_crops(conn, n=1)
    apply_ingest_eval_corpus(conn, [{"asset_id": "a0", "eval_corpus": "X"}])
    assert conn.execute(
        "SELECT training_eligible FROM image_assets WHERE id='a0'").fetchone()[0] == 1


# ─── 4. La sélection est déterministe, et elle respecte le plancher ──────────


def test_les_rangs_quantiles_sont_dans_la_moitie_haute_et_distincts():
    for n in range(10, 60):
        rangs = quantiles_moitie_haute(n, 5)
        assert len(rangs) == 5
        assert len(set(rangs)) == 5, f"doublon de rang pour n={n}"
        assert rangs == sorted(rangs)
        # Tous dans la moitié la plus dégradée (ou juste à sa frontière quand
        # le débordement anti-doublon s'est déclenché).
        assert max(rangs) < n
    # Pool trop court : on rend ce qu'on peut, jamais un doublon.
    assert quantiles_moitie_haute(3, 5) == [0, 1, 2]
    assert quantiles_moitie_haute(0, 5) == []


def _base_de_selection(tmp_path, *, n_par_classe=20, n_classes=3):
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    conn.execute("PRAGMA foreign_keys=OFF")
    for c in range(n_classes):
        eid = f"c{c}"
        conn.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, numista_id) "
            "VALUES (?, 'AT', 2002, 2.0, ?)", (eid, 100 + c))
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref) VALUES (?, 'ebay', ?)",
            (f"si{c}", f"r{c}"))
        for i in range(n_par_classe):
            conn.execute(
                "INSERT INTO image_assets (id, source_image_id, crop_index, "
                "eurio_id, resolution_status, face, training_eligible, "
                "storage_status, storage_path, tilt_deg, tilt_trustworthy) "
                "VALUES (?, ?, ?, ?, 'manual', 'obverse', 1, 'present', ?, ?, 1)",
                (f"{eid}-a{i:02d}", f"si{c}", i, eid,
                 f"ebay/si{c}/a{i}.png", float(i)))
    conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


def test_la_selection_est_rejouable_a_lidentique(tmp_path):
    conn = _base_de_selection(tmp_path)
    p1 = selectionner(conn, quota=5, min_real=10)
    p2 = selectionner(conn, quota=5, min_real=10)
    assert [p["asset_id"] for p in p1["picks"]] == [p["asset_id"] for p in p2["picks"]]
    assert len(p1["picks"]) == 15  # 3 classes × 5


def test_la_selection_prend_les_plus_inclines(tmp_path):
    """Le critère est géométrique — `tilt_deg` — jamais un embedding appris."""
    conn = _base_de_selection(tmp_path, n_par_classe=20, n_classes=1)
    plan = selectionner(conn, quota=5, min_real=10)
    tilts = [p["tilt_deg"] for p in plan["picks"]]
    # Pool 0..19 ; moitié haute = les 10 plus inclinés (19..10).
    assert min(tilts) >= 10.0, tilts
    # Rangs quantiles = 1,3,5,7,9 de l'ordre décroissant (0..19) → 18,16,14,12,10.
    assert max(tilts) == 18.0


def test_une_ancre_de_la_banque_servie_nest_jamais_prelevee(tmp_path):
    """Noter une ancre contre sa propre banque mesurerait une similarité de 1,0
    avec elle-même. Le pool candidat les écarte."""
    conn = _base_de_selection(tmp_path, n_par_classe=20, n_classes=1)
    # Les 5 plus inclinés du pool sont déclarés ancres de `2eur_all`.
    for i in range(15, 20):
        conn.execute(
            "INSERT INTO dino_class_references (anchors_kind, class_id, eurio_id, "
            "asset_id, method, encoder_version) "
            "VALUES ('2eur_all', 'c0', 'c0', ?, 'fps', 'dinov2-vitl14')",
            (f"c0-a{i:02d}",))
    conn.commit()
    picks = {p["asset_id"] for p in selectionner(conn, quota=5, min_real=10)["picks"]}
    assert not (picks & {f"c0-a{i:02d}" for i in range(15, 20)})


def test_une_classe_qui_tomberait_sous_le_plancher_nest_pas_prelevee(tmp_path):
    """Le quota se raisonne sur **ce qui reste**, jamais sur ce qu'on prend :
    `real_training_sources` est partagé par le bake ET le préflight."""
    conn = _base_de_selection(tmp_path, n_par_classe=14, n_classes=1)
    plan = selectionner(conn, quota=5, min_real=10)
    assert plan["picks"] == []
    assert plan["rejets"]["plancher"] == ["c0"]
    # 15 suffit tout juste (15 − 5 = 10 = MIN_REAL).
    conn2 = _base_de_selection(tmp_path / "bis", n_par_classe=15, n_classes=1)
    assert len(selectionner(conn2, quota=5, min_real=10)["picks"]) == 5


def test_un_crop_deja_dans_un_corpus_nest_pas_represente(tmp_path):
    """Relancer la sélection après un prélèvement ne re-propose pas les mêmes
    crops : le pool exige `eval_corpus IS NULL`."""
    conn = _base_de_selection(tmp_path, n_par_classe=20, n_classes=1)
    premiers = {p["asset_id"] for p in selectionner(conn, quota=5, min_real=10)["picks"]}
    apply_ingest_eval_corpus(
        conn, [{"asset_id": a, "eval_corpus": "X"} for a in sorted(premiers)])
    conn.commit()
    seconds = {p["asset_id"] for p in selectionner(conn, quota=5, min_real=10)["picks"]}
    assert not (premiers & seconds)


@pytest.mark.parametrize("source", ["numista_api", "bce_official"])
def test_seuls_les_crops_ebay_sont_preleves(tmp_path, source):
    """D1 : le jeu d'évaluation vient des crops eBay — pas des canoniques, qui
    sont justement ce que les deux modèles ont vu comme référence."""
    conn = _base_de_selection(tmp_path, n_par_classe=20, n_classes=1)
    conn.execute("UPDATE source_images SET source = ?", (source,))
    conn.commit()
    assert selectionner(conn, quota=5, min_real=10)["picks"] == []
