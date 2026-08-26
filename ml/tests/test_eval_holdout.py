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
    selectionner,
    tirage,
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


def test_le_tirage_est_rejouable_et_ne_rend_jamais_de_doublon():
    """Un doublon serait une image comptée deux fois dans le dénominateur."""
    cands = [{"asset_id": f"a{i:02d}"} for i in range(20)]
    une = tirage(cands, 5, seed=42, class_id="c0")
    deux = tirage(cands, 5, seed=42, class_id="c0")
    assert [c["asset_id"] for c in une] == [c["asset_id"] for c in deux]
    assert len({c["asset_id"] for c in une}) == 5
    # Pool plus court que le quota : on rend ce qu'on a, jamais un doublon.
    assert len(tirage(cands[:3], 5, seed=42, class_id="c0")) == 3


def test_la_graine_est_par_CLASSE_pour_quune_classe_ne_bouge_pas_les_autres():
    """LE point de la graine composée.

    Avec une graine globale, un seul crop scrapé en plus ferait re-tirer les 60
    classes, et deux prélèvements à deux semaines d'écart n'auraient plus rien
    en commun sans que personne ne l'ait décidé.
    """
    cands = [{"asset_id": f"a{i:02d}"} for i in range(20)]
    c0 = [c["asset_id"] for c in tirage(cands, 5, seed=42, class_id="c0")]
    c1 = [c["asset_id"] for c in tirage(cands, 5, seed=42, class_id="c1")]
    assert c0 != c1, "deux classes ne doivent pas tirer la même chose"
    # Et le pool de c1 peut grossir sans toucher c0.
    gros = cands + [{"asset_id": f"a{i:02d}"} for i in range(20, 40)]
    assert [c["asset_id"] for c in tirage(cands, 5, seed=42, class_id="c0")] == c0
    assert [c["asset_id"] for c in tirage(gros, 5, seed=42, class_id="c1")] != c1


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


def test_le_tirage_ne_trie_plus_sur_le_tilt(tmp_path):
    """La v1 prenait la moitié la plus inclinée. Mesuré le 2026-08-26, ce jeu
    était 3,7 points plus FACILE que ce qu'il écartait, et le quartile le plus
    incliné était le meilleur. Une règle qui trie sur un signal qui ne trie
    rien n'est pas neutre : elle introduit un biais qu'on ne sait pas nommer.

    Ce test échoue si quelqu'un remet un tri par tilt : sur un pool 0..19, les
    5 tirés ne doivent PAS être les 5 plus inclinés.
    """
    conn = _base_de_selection(tmp_path, n_par_classe=20, n_classes=1)
    ids = {p["asset_id"] for p in selectionner(conn, quota=5, min_real=10)["picks"]}
    plus_inclines = {f"c0-a{i:02d}" for i in range(15, 20)}
    assert ids != plus_inclines


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


# ─── 5. Le RANGEMENT suit le rôle — décision D9 ──────────────────────────────
#
# D9 avait d'abord été fermée sur « la clé S3 est immuable, c'est la ligne qui
# porte le rôle ». Le PO l'a rouverte, et il avait raison : un crop passé en
# évaluation n'est plus le même objet fonctionnellement. Tant que le stockage
# l'ignore, la séparation ne tient que par un `WHERE` — et un prédicat oublié
# la fait fuir en silence. Ces tests verrouillent les deux marques (bucket +
# préfixe de clé) et, surtout, le GARDE qui rend une fuite bruyante.


def test_la_cle_deval_porte_le_corpus_et_la_derivation_est_idempotente():
    from shared.storage import corpus_of_eval_key, eval_storage_key, is_eval_key

    k = eval_storage_key("ebay/run-1/a.png", "matrice-2026-08")
    assert k == "eval/matrice-2026-08/ebay/run-1/a.png"
    assert is_eval_key(k) and not is_eval_key("ebay/run-1/a.png")
    assert corpus_of_eval_key(k) == "matrice-2026-08"
    assert corpus_of_eval_key("ebay/run-1/a.png") is None
    # Idempotence : une migration relancée ne fabrique pas `eval/c/eval/c/…`.
    assert eval_storage_key(k, "matrice-2026-08") == k


def test_un_nom_de_corpus_avec_un_slash_est_refuse():
    """Sinon il fabriquerait un niveau de préfixe fantôme, et
    `corpus_of_eval_key` ne saurait plus lire son propre rangement."""
    from shared.storage import eval_storage_key

    with pytest.raises(ValueError):
        eval_storage_key("ebay/a.png", "matrice/2026")
    with pytest.raises(ValueError):
        eval_storage_key("ebay/a.png", "")


def test_le_bucket_se_derive_de_la_cle_seule():
    """C'est ce qui permet aux couches d'AFFICHAGE de continuer à montrer les
    crops d'éval sans faire descendre `eval_corpus` dans chaque requête — un
    oubli y donnerait une vignette cassée sans un mot (D8 : le rôle n'est pas
    une exclusion de la review)."""
    from shared.storage import bucket_for_asset, bucket_for_key

    assert bucket_for_key("ebay/run-1/a.png") == "enrichment-crops"
    assert bucket_for_key("eval/c/ebay/run-1/a.png") == "eval-corpus"
    assert bucket_for_asset("ebay") == "enrichment-crops"
    assert bucket_for_asset("numista") == "numista-canonical"
    assert bucket_for_asset("ebay", "eval/c/ebay/a.png") == "eval-corpus"
    # Le rôle l'emporte sur la source.
    assert bucket_for_asset("numista", "eval/c/x.png") == "eval-corpus"


def test_le_garde_refuse_un_couple_bucket_role_incoherent():
    from shared.storage import assert_role_matches_bucket

    assert_role_matches_bucket("enrichment-crops", "ebay/a.png")
    assert_role_matches_bucket("eval-corpus", "eval/c/ebay/a.png")
    with pytest.raises(ValueError, match="mauvais bucket"):
        assert_role_matches_bucket("enrichment-crops", "eval/c/ebay/a.png")
    with pytest.raises(ValueError, match="sans rôle d'éval"):
        assert_role_matches_bucket("eval-corpus", "ebay/a.png")


def test_local_path_echoue_avant_le_reseau_et_avant_la_cascade(tmp_path, monkeypatch):
    """LE test de ce lot.

    Sans ce garde, une collecte d'entraînement qui aurait perdu son prédicat
    `eval_corpus IS NULL` demanderait `enrichment-crops/eval/…`, prendrait un
    404, et `local_path` déclencherait `cascade.mark_missing_in_storage()` : le
    crop d'éval serait marqué `missing_in_storage` alors qu'il est parfaitement
    là. La fuite « réparerait » donc la base à l'envers, en silence.

    On vérifie les deux moitiés : ça lève, et ni MinIO ni la cascade n'ont été
    touchés.
    """
    import shared.storage.cascade as cascade
    import shared.storage.local_cache as lc

    monkeypatch.setenv("EURIO_CACHE_ROOT", str(tmp_path))
    appels: list = []
    monkeypatch.setattr(lc, "_client", lambda: appels.append("minio"))
    monkeypatch.setattr(cascade, "mark_missing_in_storage",
                        lambda *a, **k: appels.append("cascade"))

    with pytest.raises(ValueError, match="mauvais bucket"):
        lc.local_path("enrichment-crops", "eval/c/ebay/a.png")
    assert appels == [], "le garde doit lever AVANT le réseau et AVANT la cascade"

    # Et le chemin de cache, qui est celui qu'`upload_through` écrirait : sans
    # ce second garde on rangerait un crop d'éval sous `enrichment-crops/` en
    # local, et le prochain `local_path` y verrait un HIT.
    with pytest.raises(ValueError, match="mauvais bucket"):
        lc.cache_path_for("enrichment-crops", "eval/c/ebay/a.png")


def test_le_rangement_voyage_avec_le_role_dans_la_meme_transaction(tmp_path):
    """Un état qui dirait le corpus sans la clé (ou l'inverse) ne serait
    rattrapé par rien — ils partent ensemble."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _monte_crops(conn, n=3)

    r = apply_ingest_eval_corpus(conn, [{
        "asset_id": "a0", "eval_corpus": "X",
        "storage_path": "eval/X/ebay/si1/a0.png",
    }])
    assert r["updated"] == 1
    ligne = conn.execute(
        "SELECT eval_corpus, storage_path FROM image_assets WHERE id='a0'"
    ).fetchone()
    assert tuple(ligne) == ("X", "eval/X/ebay/si1/a0.png")


def test_un_deplacement_apres_marquage_nest_pas_compte_skipped(tmp_path):
    """La migration se joue en DEUX temps : marquer, puis déplacer les octets
    et dire où ils sont. Si le second temps était `skipped` parce que le corpus
    est déjà posé, un déplacement passerait pour un no-op — et la base
    continuerait de pointer une clé qui n'existe plus."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _monte_crops(conn, n=2)

    apply_ingest_eval_corpus(conn, [{"asset_id": "a0", "eval_corpus": "X"}])
    r = apply_ingest_eval_corpus(conn, [{
        "asset_id": "a0", "eval_corpus": "X",
        "storage_path": "eval/X/ebay/si1/a0.png",
    }])
    assert (r["updated"], r["skipped"]) == (1, 0)
    assert conn.execute(
        "SELECT storage_path FROM image_assets WHERE id='a0'"
    ).fetchone()[0] == "eval/X/ebay/si1/a0.png"

    # Rejouer à l'identique redevient un no-op.
    r2 = apply_ingest_eval_corpus(conn, [{
        "asset_id": "a0", "eval_corpus": "X",
        "storage_path": "eval/X/ebay/si1/a0.png",
    }])
    assert (r2["updated"], r2["skipped"]) == (0, 1)


def test_la_liberation_ramene_le_role_ET_la_cle_ensemble(tmp_path):
    """L'opération SYMÉTRIQUE du prélèvement, et sans elle le corpus d'éval est
    une porte à sens unique : un crop qui y entre ne revient jamais au train.

    Retirer le rôle en ramenant une clé NORMALE est donc autorisé — c'est la
    libération. Ce qui reste refusé, c'est retirer le rôle en POSANT une clé
    d'éval (test suivant)."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _monte_crops(conn, n=1)
    apply_ingest_eval_corpus(conn, [{
        "asset_id": "a0", "eval_corpus": "X",
        "storage_path": "eval/X/ebay/si1/a0.png"}])

    r = apply_ingest_eval_corpus(conn, [{
        "asset_id": "a0", "eval_corpus": None, "expect": "X",
        "storage_path": "ebay/si1/a0.png"}])
    assert r["updated"] == 1 and r["conflict"] == []
    ligne = conn.execute(
        "SELECT eval_corpus, storage_path FROM image_assets WHERE id='a0'"
    ).fetchone()
    assert tuple(ligne) == (None, "ebay/si1/a0.png")


def test_une_cle_deval_sur_une_ligne_quon_retire_est_refusee(tmp_path):
    """Elle laisserait un crop d'entraînement pointant un bucket qu'aucune
    collecte de train ne regarde — invisible, et impossible à distinguer d'une
    perte."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _monte_crops(conn, n=1)
    apply_ingest_eval_corpus(conn, [{"asset_id": "a0", "eval_corpus": "X"}])

    r = apply_ingest_eval_corpus(conn, [{
        "asset_id": "a0", "eval_corpus": None, "expect": "X",
        "storage_path": "eval/X/ebay/si1/a0.png",
    }])
    assert r["conflict"] == ["a0"] and r["updated"] == 0
    assert conn.execute(
        "SELECT eval_corpus FROM image_assets WHERE id='a0'").fetchone()[0] == "X"


def test_la_route_ingest_transporte_bien_storage_path():
    """Le champ doit exister sur le MODÈLE de la route, pas seulement dans le
    helper : pydantic ignore silencieusement un champ non déclaré, et la clé
    n'atterrirait jamais — pendant que les octets, eux, auraient bougé."""
    from serving.ingest_routes import EvalCorpusRow

    assert "storage_path" in EvalCorpusRow.model_fields
    r = EvalCorpusRow(asset_id="a", eval_corpus="X", storage_path="eval/X/a.png")
    assert r.model_dump()["storage_path"] == "eval/X/a.png"


def test_le_plan_de_deplacement_est_idempotent(tmp_path):
    """Un crop déjà rangé est compté `deja_range` et n'est pas retouché — une
    relance du script ne re-copie rien."""
    from scripts.move_eval_corpus_objects import plan_deplacement

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _monte_crops(conn, n=3)
    conn.execute("UPDATE image_assets SET eval_corpus='X' WHERE id IN ('a0','a1')")
    conn.commit()
    conn.row_factory = sqlite3.Row

    plan = plan_deplacement(conn)
    assert plan["deja_range"] == 0
    assert {i["asset_id"] for i in plan["a_deplacer"]} == {"a0", "a1"}
    assert plan["a_deplacer"][0]["dst_key"] == "eval/X/ebay/si1/a0.png"

    conn.execute(
        "UPDATE image_assets SET storage_path='eval/X/ebay/si1/a0.png' "
        "WHERE id='a0'")
    conn.commit()
    plan2 = plan_deplacement(conn)
    assert plan2["deja_range"] == 1
    assert {i["asset_id"] for i in plan2["a_deplacer"]} == {"a1"}


def test_laffichage_derive_son_bucket_et_ne_le_hardcode_pas():
    """Les couches d'affichage ne doivent PAS nommer `enrichment-crops` en dur :
    avec une clé d'éval, `signed_url` lèverait — et leurs `except` avalent
    l'exception, donc la vignette casserait sans un mot.

    On lit le SOURCE plutôt que d'appeler : ces helpers ont besoin de creds
    MinIO, et le point à verrouiller est justement l'absence du littéral.
    """
    import inspect

    from review.peer_arbitration_routes import _crop_url as arb
    from review_service.routes_reviewer import _crop_url as friend
    from serving.review_queue.repository import _crop_url as queue
    from serving.review_routes import _crop_url as review

    for fn in (queue, review, friend, arb):
        src = inspect.getsource(fn)
        assert "bucket_for_key" in src, f"{fn.__qualname__} dérive-t-il son bucket ?"
        assert '"enrichment-crops"' not in src, (
            f"{fn.__qualname__} hardcode encore le bucket des crops"
        )


def test_les_collectes_dentrainement_hardcodent_le_bucket_et_cest_voulu():
    """Le pendant du test précédent, et il n'est pas symétrique.

    Les deux collectes de TRAIN gardent `enrichment-crops` en dur : c'est ce
    qui rend un crop d'éval physiquement inatteignable pour elles. Si un jour
    quelqu'un les « corrige » en les faisant dériver leur bucket, la garantie
    de D9 tombe sans qu'aucun test ne rougisse — sauf celui-ci.
    """
    import inspect

    from training.foundation.anchors import _candidate_crops_for_class
    from training.iteration_augmentations import _ebay_training_sources

    src = inspect.getsource(_ebay_training_sources)
    assert '"enrichment-crops"' in src and "bucket_for_key" not in src, (
        "la collecte ArcFace doit rester aveugle au bucket d'éval"
    )
    assert "eval_corpus IS NULL" in inspect.getsource(_candidate_crops_for_class)
