"""Le défaut de face du 2026-08-27 — provenance, dérive du seuil, garde humain.

Ouvert après le banc à l'aveugle : le PO signale « pas mal de revers » parmi
60 crops que la base déclarait tous `obverse`. Trois causes cumulées, un test
par cause, et pour chacune la mutation qui la rend rouge (dans le docstring).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest  # noqa: E402

from store import Store  # noqa: E402
from store.faces import apply_ingest_faces  # noqa: E402


class _Verdict:
    """Duck-type minimal de ce que `apply_ingest_faces` consomme."""

    def __init__(self, asset_id: str, face: str) -> None:
        self.asset_id = asset_id
        self.face = face


def _monte(conn, assets):
    """`assets` = [(id, face, face_source, decided_face|None)]."""
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref) "
        "VALUES ('si1', 'ebay', 'r1')"
    )
    for i, (aid, face, src, decided) in enumerate(assets):
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, "
            " resolution_status, face, face_source, storage_status, "
            " storage_path) "
            "VALUES (?, 'si1', ?, 'manual', ?, ?, 'present', ?)",
            (aid, i, face, src, f"ebay/si1/{aid}.png"),
        )
        if decided is not None:
            conn.execute(
                "INSERT INTO review_queue (id, image_asset_id, status, "
                " decided_face) VALUES (?, ?, 'done', ?)",
                (f"rq{i}", aid, decided),
            )
    conn.commit()


# ─── 1. La colonne naît des deux côtés du contrat de miroir ─────────────────


def test_une_base_neuve_nait_avec_face_source(tmp_path):
    """Mutation : retirer `face_source` de `schema.sql` → rouge."""
    conn = Store(tmp_path / "neuve.db")._connection()  # noqa: SLF001
    cols = {r[1] for r in conn.execute("PRAGMA table_info(image_assets)")}
    assert "face_source" in cols
    idx = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_image_assets_face_source" in idx


def test_la_migration_0017_est_un_alter_un_backfill_et_un_index():
    """Mutation : vider le fichier de migration → rouge.

    Garde nommée : le miroir seul passerait aussi si 0017 ne déclarait rien.
    Le BACKFILL compte autant que l'ALTER — sans lui la colonne naîtrait à
    NULL partout, donc tous les verdicts humains deviendraient écrasables.
    """
    sql = (ML_DIR / "serving" / "migrations"
           / "0017_image_assets_face_source.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE image_assets" in sql and "face_source" in sql
    assert "SET face_source = 'human'" in sql
    assert "decided_face IN ('obverse', 'reverse')" in sql
    assert "SET face_source = 'pipeline'" in sql
    schema = (ML_DIR / "state" / "schema.sql").read_text(encoding="utf-8")
    assert "face_source" in schema and "idx_image_assets_face_source" in schema


def test_une_base_anterieure_rattrape_la_colonne_ET_son_backfill(tmp_path):
    """Mutation : retirer le backfill du bloc pre-bootstrap (garder l'ALTER
    seul) → rouge.

    C'est LE piège de cette migration. Poser la colonne sans la remplir sur une
    base antérieure laisserait tous les `face_source` à NULL — et NULL veut
    dire « écrasable ». Un verdict humain d'avant 0017 serait alors clobbé par
    la première passe de face, silencieusement.
    """
    schema = (ML_DIR / "state" / "schema.sql").read_text(encoding="utf-8")
    ampute = schema.replace(
        "  face_source              TEXT\n"
        "                           CHECK (face_source IS NULL\n"
        "                                  OR face_source IN ('pipeline', 'human')),\n",
        "")
    ampute = ampute.replace(
        "CREATE INDEX IF NOT EXISTS idx_image_assets_face_source\n"
        "  ON image_assets(face_source) WHERE face_source = 'pipeline';\n", "")
    assert ampute != schema and "image_assets(face_source)" not in ampute

    db = tmp_path / "ancienne.db"
    brut = sqlite3.connect(db)
    brut.executescript(ampute)
    # Un humain a tranché la face de a_humain AVANT la migration.
    brut.execute("PRAGMA foreign_keys=OFF")
    brut.execute("INSERT INTO source_images (id, source, source_ref) "
                 "VALUES ('si1','ebay','r1')")
    brut.execute("INSERT INTO image_assets (id, source_image_id, crop_index, "
                 " resolution_status, face, storage_status, storage_path) "
                 "VALUES ('a_humain','si1',0,'manual','obverse','present',"
                 "        'ebay/si1/a_humain.png')")
    brut.execute("INSERT INTO image_assets (id, source_image_id, crop_index, "
                 " resolution_status, face, storage_status, storage_path) "
                 "VALUES ('a_machine','si1',1,'manual','obverse','present',"
                 "        'ebay/si1/a_machine.png')")
    brut.execute("INSERT INTO review_queue (id, image_asset_id, status, "
                 " decided_face) VALUES ('rq1','a_humain','done','obverse')")
    brut.commit()
    brut.close()

    conn = Store(db)._connection()  # noqa: SLF001
    got = dict(conn.execute(
        "SELECT id, face_source FROM image_assets").fetchall())
    assert got["a_humain"] == "human", (
        "un verdict humain d'avant 0017 doit être reconnu comme tel, sinon la "
        "prochaine passe de face l'écrase sans un mot")
    assert got["a_machine"] == "pipeline"


# ─── 2. Le garde protège l'humain, et LUI SEUL ──────────────────────────────


@pytest.mark.parametrize(
    ("source_initiale", "attendu"),
    [
        (None, "reverse"),        # jamais étiquetée → la machine écrit
        ("pipeline", "reverse"),  # étiquetée par la machine → RECALCULABLE
    ],
)
def test_une_face_machine_se_recalcule(tmp_path, source_initiale, attendu):
    """Mutation : remettre `WHERE ... AND (face IS NULL OR face='unknown')`
    dans `store/faces.py` → rouge.

    C'est le cœur du défaut : l'ancienne règle gelait la machine en même temps
    que l'humain, donc une étiquette posée sous un τ périmé le restait à
    jamais.
    """
    store = Store(tmp_path / "db.sqlite")
    conn = store._connection()  # noqa: SLF001
    _monte(conn, [("a1", "obverse", source_initiale, None)])

    res = apply_ingest_faces(conn, [_Verdict("a1", "reverse")])
    conn.commit()

    assert res["updated"] == 1 and res["skipped"] == 0
    row = conn.execute(
        "SELECT face, face_source FROM image_assets WHERE id='a1'").fetchone()
    assert row["face"] == attendu
    assert row["face_source"] == "pipeline"


def test_un_verdict_humain_ne_bouge_pour_personne(tmp_path):
    """Mutation : retirer `AND (face_source IS NULL OR face_source='pipeline')`
    de `store/faces.py` → rouge.

    L'assouplissement ne doit PAS aller jusque-là. Une décision humaine est la
    seule donnée du projet qu'aucun calcul ne régénère.
    """
    store = Store(tmp_path / "db.sqlite")
    conn = store._connection()  # noqa: SLF001
    _monte(conn, [("a1", "obverse", "human", "obverse")])

    res = apply_ingest_faces(conn, [_Verdict("a1", "reverse")])
    conn.commit()

    assert res["updated"] == 0 and res["skipped"] == 1
    row = conn.execute(
        "SELECT face, face_source FROM image_assets WHERE id='a1'").fetchone()
    assert row["face"] == "obverse"
    assert row["face_source"] == "human"


# ─── 3. Le seuil, et la dérive qui l'a rendu aveugle ────────────────────────


def test_le_seuil_de_face_est_la_frontiere_naturelle():
    """Mutation : remettre `FACE_REVERSE_TAU = 0.065` → rouge.

    Re-mesuré le 2026-08-27 sur le gold de juin, banque des avers à 2 062
    ancres (`python -m scripts.bench_face_recall --taus=-0.055:0.02:0.005`) :
    la marge MAXIMALE des 514 avers confirmés est −0,0507, donc aucun n'atteint
    zéro. À τ = 0,065 le rappel des revers durs valait 40,0 % contre 53,3 % à
    zéro, et celui des revers faciles 80,0 % contre 100 % — pour exactement le
    même nombre de faux positifs : aucun.
    """
    from shared.face_rule import FACE_REVERSE_TAU

    assert FACE_REVERSE_TAU == 0.0


def test_la_decision_de_face_suit_le_seuil():
    """Mutation : inverser la comparaison dans `_decide_face` → rouge."""
    from shared.face_rule import decide_face

    # marge = reverse − obverse. Strictement au-dessus du seuil → revers.
    assert decide_face(0.80, 0.70) == "reverse"
    assert decide_face(0.70, 0.80) == "obverse"
    # Pile sur le seuil : la comparaison est un `>=`, donc revers.
    assert decide_face(0.75, 0.75) == "reverse"


def test_le_rebuild_de_la_banque_previent_de_la_derive():
    """Mutation : retirer le `logger.warning` de `build_anchors_2eur_all` → rouge.

    L'alarme est posée à la CAUSE. Le détecteur de face se dégrade quand la
    banque des AVERS grossit — 73,3 % → 40,0 % de rappel dur entre juin et août
    sans qu'une ligne de code change. Sans ce cri au bon endroit, la prochaine
    dérive sera aussi muette que celle-là.
    """
    src = (ML_DIR / "training" / "foundation" / "anchors.py").read_text(
        encoding="utf-8")
    tete, _, queue = src.partition("def build_anchors_2eur_all(")
    corps = queue.partition("\ndef build_anchors_reverse_2eur(")[0]
    assert "logger.warning(" in corps, (
        "le rebuild de la banque des avers doit crier : c'est lui qui décale "
        "le seuil de face")
    assert "bench_face_recall" in corps


def test_la_regle_de_face_est_importable_sans_cv2_ni_torch():
    """Mutation : replacer `FACE_REVERSE_TAU`/`decide_face` dans
    `steps/auto_validate` et faire importer le script depuis là → rouge.

    L'image lean du VPS n'a ni `cv2` ni `torch`, et ne copie pas `ml/scripts/`.
    Une règle qui n'y est pas importable oblige toute passe corrective jouée au
    CANONIQUE — le seul writer — à la réécrire, donc à en créer une seconde
    copie libre de diverger. Ce test verrouille l'unicité de la définition.
    """
    import ast

    src = (ML_DIR / "shared" / "face_rule.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    importes = {
        n.module.split(".")[0]
        for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module
    } | {
        a.name.split(".")[0]
        for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names
    }
    interdits = importes & {"cv2", "torch", "numpy", "PIL", "sources", "training"}
    assert not interdits, (
        f"shared/face_rule.py doit rester stdlib-pur, or il importe {interdits}")

    # Et la définition est UNIQUE : auto_validate délègue, il ne recopie pas.
    av = (ML_DIR / "sources" / "_base" / "steps" / "auto_validate.py").read_text(
        encoding="utf-8")
    assert "from shared.face_rule import" in av
    assert "FACE_REVERSE_TAU = " not in av, (
        "le seuil est redéfini dans auto_validate — il y en a donc deux")
