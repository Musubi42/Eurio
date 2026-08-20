"""Le plancher d'exemplaires de la banque `2eur_all`.

⚠️ **Le défaut est 1, donc le plancher est INACTIF.** Il a valu 2 le
2026-08-20, sur la foi du creux agrégé de la courbe (N=0 53,1 %, N=1 50,1 %) ;
la mesure à la maille manquante l'a renversé le même jour — donner à 57 classes
exactement un exemplaire AMÉLIORE leurs propres crops (vitl14 67,6 → 69,1 %,
McNemar p = 0,048, 1073 crops), et le creux agrégé vient de l'ORDRE du FPS, pas
du compte (à nombre d'ancres égal, garder le rang le moins diversifiant donne
77,8 % au lieu de 73,8 %). Raisonnement, réserves et commandes :
`shared/dino_threshold_defaults.py`, couple `("2eur_all", "dinov2-vitl14")`.

Ces tests protègent donc DEUX choses distinctes, et il faut les garder
distinctes — c'est exactement ce qui permettra de reposer un plancher le jour
où une mesure le demandera, sans réécrire le mécanisme :

1. **Le défaut ne ramène AUCUNE classe au canonique seul.** C'est la décision
   du 2026-08-20 soir, et le test qui la garde est celui qui rougira si
   quelqu'un remet 2 sans mesure.
2. **Le MÉCANISME marche quand on le pose.** Un plancher explicite (argument ou
   ligne en base) ramène bien la classe sous le seuil à son canonique seul.
3. **La valeur vient de la BASE**, pas du code (D5). Un plancher figé dans le
   code ne peut pas être éprouvé ; un plancher qui ignorerait la ligne posée
   en base mentirait à l'écran de réglage sans lever d'erreur.
4. **Le défaut, quand la ligne manque, est EXPLICITE.** Pas un silence : la
   valeur retenue et sa provenance sont journalisées et écrites dans la note
   du build (`dino_anchor_builds.note`).
5. **Le cas limite tranché** : une classe sans canonique garde son unique
   exemplaire même sous un plancher — la rejeter la ferait disparaître de la
   banque.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store  # noqa: E402
from store import dino_thresholds as dt  # noqa: E402
from training.foundation import anchors as A  # noqa: E402

COUPLE = {"anchors_kind": "2eur_all", "encoder_version": "dinov2-vitl14"}

# Vecteurs déterministes par marqueur de chemin (aucun torch).
_VEC = {
    "obverse.jpg": [1.0, 0.0, 0.0],
    "c1": [0.90, 0.44, 0.0],
    "c2": [0.60, 0.80, 0.0],
}


def _fake_encode(paths, **_kw):
    kept, rows = [], []
    for p in paths:
        s = str(p)
        vec = next((v for k, v in _VEC.items() if k in s), [1.0, 0.0, 0.0])
        arr = np.array(vec, dtype=np.float32)
        arr /= np.linalg.norm(arr)
        kept.append(Path(p))
        rows.append(arr)
    return kept, np.stack(rows)


def _patch_encoder(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(A, "load_encoder", lambda **kw: (None, None))
    monkeypatch.setattr(A, "build_transform", lambda: None)
    monkeypatch.setattr(A, "encode_paths", _fake_encode)
    monkeypatch.setattr(
        "shared.storage.local_cache.local_path",
        lambda bucket, key: Path("/fake") / bucket / key,
    )


def _seed(conn, datasets_dir: Path, *, crops: list[str], avec_canonique: bool = True):
    """Une classe commémo `fr-2015-a` et ses crops validés."""
    conn.execute(
        "INSERT OR REPLACE INTO coins (eurio_id, country, country_name, year, "
        "face_value, is_commemorative, numista_id, raw_payload_json) "
        "VALUES ('fr-2015-a', 'FR', 'France', 2015, 2.0, 1, 5001, '{}')",
    )
    if avec_canonique:
        obv = datasets_dir / "5001"
        obv.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 32), (128, 128, 128)).save(obv / "obverse.jpg")
    for aid in crops:
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref) VALUES (?, 'ebay', ?)",
            (f"SI_{aid}", f"ref_{aid}"),
        )
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, eurio_id, "
            "resolution_status, face, denom, training_eligible, storage_path) "
            "VALUES (?, ?, 0, 'fr-2015-a', 'manual', 'obverse', '2eur', 1, ?)",
            (aid, f"SI_{aid}", f"{aid}.png"),
        )


def _build(store, datasets, **kw):
    with store._writing() as conn:  # noqa: SLF001
        return A.build_anchors_2eur_all(
            conn=conn, datasets_dir=datasets, force_recompute=True,
            floor_sim=0.0, encoder_version="dinov2-vitl14", **kw,
        )


def _exemplaires(bank) -> list[str]:
    return [a for a in bank.asset_ids if a]


# ── 1. Le plancher est appliqué ───────────────────────────────────────────────

def test_par_defaut_aucune_classe_nest_ramenee_au_canonique_seul(
    tmp_path, monkeypatch,
):
    """LE test de la décision du 2026-08-20 soir : plancher par défaut = 1,
    donc une classe à un seul exemplaire le GARDE. Ce test rougit si quelqu'un
    remet 2 dans les défauts — ce qui est permis, mais pas sans mesure : la
    mesure qui a fait retirer le plancher est citée dans le module de défauts."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets, crops=["c1"])
    bank = _build(store, datasets, exemplars_per_class=10)

    assert _exemplaires(bank) == ["c1"]
    assert bank.count == 2                      # canonique + son exemplaire
    assert "0 classes ramenées au canonique seul" in bank.build.note


def test_le_mecanisme_marche_quand_on_POSE_un_plancher(tmp_path, monkeypatch):
    """Le plancher est retiré, pas démonté : posé à 2, il ramène bien la classe
    à un exemplaire sur son canonique seul."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets, crops=["c1"])
    bank = _build(store, datasets, exemplars_per_class=10, min_exemplars=2)

    assert _exemplaires(bank) == []
    assert bank.count == 1                      # le canonique, seul
    with store._writing() as conn:
        methodes = [r["method"] for r in conn.execute(
            "SELECT method FROM dino_class_references WHERE class_id='fr-2015-a'")]
    assert methodes == ["canonical"]


def test_deux_exemplaires_passent_le_plancher(tmp_path, monkeypatch):
    """Le pendant : deux exemplaires passent, quel que soit le plancher posé
    jusqu'à 2 — le défaut inactif ne coupe rien non plus."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets, crops=["c1", "c2"])
    bank = _build(store, datasets, exemplars_per_class=10)

    assert sorted(_exemplaires(bank)) == ["c1", "c2"]


# ── 2. La valeur vient de la base ─────────────────────────────────────────────

def test_le_plancher_pose_en_base_est_celui_qui_sapplique(tmp_path, monkeypatch):
    """D5 : le seuil vit en base. Poser 2 doit RETIRER l'exemplaire unique,
    alors que le défaut du code (1) le garderait — c'est la base qui gagne, et
    c'est ce qui rend le plancher reposable en une ligne."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets, crops=["c1"])
        dt.set_threshold(conn, "min_exemplars", 2, **COUPLE)
    bank = _build(store, datasets, exemplars_per_class=10)

    assert _exemplaires(bank) == []
    assert "source=db" in bank.build.note


def test_le_plancher_est_scope_par_couple_banque_encodeur(tmp_path, monkeypatch):
    """Un plancher posé sur vits14 ne doit pas s'appliquer à vitl14 : la
    courbe a la même forme mais pas le même niveau."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets, crops=["c1"])
        dt.set_threshold(conn, "min_exemplars", 2,
                         anchors_kind="2eur_all", encoder_version="dinov2-vits14")
    bank = _build(store, datasets, exemplars_per_class=10)

    assert _exemplaires(bank) == ["c1"]         # vitl14 garde son défaut de 1
    assert "source=code" in bank.build.note


# ── 3. Le défaut est explicite, pas silencieux ───────────────────────────────

def test_ligne_absente_le_defaut_est_un_et_il_est_dit_INACTIF(
    tmp_path, monkeypatch, caplog,
):
    """Le défaut doit se LIRE dans le journal et dans la note du build. Un
    plancher inactif qui ne le dirait pas laisserait croire, six mois plus tard,
    que la banque a été bâtie sous un plancher."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets, crops=["c1"])
        assert dt.resolve(conn, **COUPLE).source["min_exemplars"] == "code"
    with caplog.at_level(logging.INFO, logger=A.logger.name):
        bank = _build(store, datasets, exemplars_per_class=10)

    assert "min_exemplars=1 (source=code" in caplog.text
    assert "INACTIF" in caplog.text
    assert bank.build.note.startswith("min_exemplars=1 (source=code)")
    assert "0 classes ramenées au canonique seul" in bank.build.note


def test_table_absente_le_build_ne_casse_pas(tmp_path, monkeypatch):
    """Réplique en retard / canonique pas redéployé : le filet du code, pas
    une erreur — c'est une précondition du build."""
    bare = sqlite3.connect(":memory:")
    assert dt.resolve(bare, **COUPLE).values["min_exemplars"] == 1
    assert dt.resolve(bare, **COUPLE).source["min_exemplars"] == "code"


# ── 4. Le cas limite : classe sans canonique ─────────────────────────────────

def test_classe_sans_canonique_garde_son_unique_exemplaire(tmp_path, monkeypatch):
    """La rejeter la rendrait INVISIBLE (recall 0 garanti) ; la garder la
    dégrade seulement. Combien de classes dans ce cas : ZÉRO au dernier build
    (`n_no_canonical`=0 pour 23c637d93b43). La règle est écrite pour le cas
    qui ne se présente pas."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets, crops=["c1"], avec_canonique=False)
    bank = _build(store, datasets, exemplars_per_class=10, min_exemplars=2)

    assert _exemplaires(bank) == ["c1"]
    assert bank.count == 1                      # l'exemplaire, sans canonique
    assert "1 sans canonique gardées" in bank.build.note


# ── 5. Le plancher ne peut pas vider la banque ───────────────────────────────

def test_plancher_au_dessus_du_plafond_est_clampe(tmp_path, monkeypatch, caplog):
    """min_exemplars > exemplars_per_class : aucune classe ne pourrait
    l'atteindre, la banque perdrait TOUS ses exemplaires."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets, crops=["c1", "c2"])
        dt.set_threshold(conn, "min_exemplars", 5, **COUPLE)
    with caplog.at_level(logging.WARNING, logger=A.logger.name):
        bank = _build(store, datasets, exemplars_per_class=1)

    assert len(_exemplaires(bank)) == 1
    assert "plancher ramené à 1" in caplog.text


# ── 6. Le seuil, côté table ──────────────────────────────────────────────────

def test_min_exemplars_est_une_cle_acceptee_et_bornee(tmp_path):
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        dt.set_threshold(conn, "min_exemplars", 3, **COUPLE)
        assert dt.resolve(conn, **COUPLE).values["min_exemplars"] == 3
        with pytest.raises(dt.DinoThresholdError) as exc:
            dt.set_threshold(conn, "min_exemplars", 999, **COUPLE)
        assert exc.value.status_code == 400


def test_une_table_davant_0011_refuse_la_cle_en_nommant_la_migration():
    """Une base locale créée avant 0011 garde la forme de 0008 pour toujours
    (`CREATE TABLE IF NOT EXISTS` ne reconstruit rien). Le message brut de
    SQLite — « CHECK constraint failed » — n'orienterait vers rien."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        (ML_DIR / "serving/migrations/0008_dino_thresholds.sql").read_text()
    )
    with pytest.raises(dt.DinoThresholdError) as exc:
        dt.set_threshold(conn, "min_exemplars", 2, **COUPLE)
    assert exc.value.status_code == 503
    assert "0011" in exc.value.detail


def test_0011_donne_la_meme_forme_que_le_bootstrap_local(tmp_path):
    """Le miroir migration ↔ schema.sql, vérifié sur la FORME réelle : une
    base migrée et une base bootstrapée doivent accepter exactement les mêmes
    écritures."""
    migre = sqlite3.connect(":memory:")
    migre.executescript(
        (ML_DIR / "serving/migrations/0008_dino_thresholds.sql").read_text()
    )
    migre.executescript(
        (ML_DIR / "serving/migrations/0011_dino_thresholds_min_exemplars.sql").read_text()
    )
    dt.set_threshold(migre, "min_exemplars", 2, **COUPLE)
    assert dt.resolve(migre, **COUPLE).source["min_exemplars"] == "db"

    boot = Store(tmp_path / "t.db")
    with boot._writing() as conn:  # noqa: SLF001
        dt.set_threshold(conn, "min_exemplars", 2, **COUPLE)
        ddl_boot = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='dino_thresholds'").fetchone()[0]
    ddl_migre = migre.execute(
        "SELECT sql FROM sqlite_master WHERE name='dino_thresholds'").fetchone()[0]
    # C'est la STRUCTURE qui doit coïncider, pas la mise en page (même
    # normalisation que tests/test_schema_mirror.py).
    norm = lambda sql: " ".join(re.sub(r"--[^\n]*", " ", sql).split())  # noqa: E731
    assert norm(ddl_boot) == norm(ddl_migre)


# ── 7. Le plancher est un COMPTE : 1,9 ne vaut pas 2 (défaut S1) ─────────────

def test_un_plancher_fractionnaire_est_refuse_a_lecriture(tmp_path):
    """`min_exemplars = 1,9` était ACCEPTÉ et rendait `int(1.9) = 1` : une
    valeur qui a l'air réglée, que `source='db'` certifie, et qui ne vaut pas ce
    qu'elle affiche. Mesuré le 2026-08-20 : `pose 1.9 → resolve 1.9 source db →
    int() 1`. Le défaut est revenu à 1 depuis, mais c'est la troncature muette
    qui est le défaut, pas la valeur qu'elle produisait."""
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        for valeur in (1.9, 0.4, 2.5):
            with pytest.raises(dt.DinoThresholdError) as exc:
                dt.set_threshold(conn, "min_exemplars", valeur, **COUPLE)
            assert exc.value.status_code == 400
            assert "entier" in exc.value.detail
        # Les valeurs entières, y compris écrites en flottant, passent.
        dt.set_threshold(conn, "min_exemplars", 2.0, **COUPLE)
        assert dt.resolve(conn, **COUPLE).values["min_exemplars"] == 2


def test_une_ligne_fractionnaire_deja_en_base_ne_passe_pas_en_silence(
    tmp_path, monkeypatch, caplog,
):
    """La porte d'écriture refuse désormais 1,9 — mais une ligne posée avant
    ce garde, ou par un autre écrivain (SQL à la main), reste lisible. Le
    build ne doit pas la tronquer sans le dire."""
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets, crops=["c1"])
        conn.execute(
            "INSERT INTO dino_thresholds (anchors_kind, encoder_version, key, value) "
            "VALUES ('2eur_all', 'dinov2-vitl14', 'min_exemplars', 1.9)"
        )
    with caplog.at_level(logging.WARNING, logger=A.logger.name):
        bank = _build(store, datasets, exemplars_per_class=10)

    assert "1.9" in caplog.text and "plancher effectif : 1" in caplog.text
    assert _exemplaires(bank) == ["c1"]         # tronqué à 1, mais DIT
