"""La passe de rejet du backlog de revers, et l'extraction qui la rend possible.

Contexte (2026-08-27) : `recompute_faces` a corrigé 4 298 étiquettes au
canonique, mais la file n'a pas bougé d'une ligne — le routage `face_reverse`
se fait à l'enqueue, jamais rétroactivement. 1 052 revers restaient servis à
l'humain. Cette passe les rejette, en réutilisant STRICTEMENT les helpers.
"""

from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from scripts.reject_reverse_backlog import main as passe  # noqa: E402
from store import Store  # noqa: E402


def _monte(conn, crops):
    """`crops` = [(asset_id, face, resolution_status, review_status, notes)]."""
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("INSERT INTO source_images (id, source, source_ref) "
                 "VALUES ('si1','ebay','r1')")
    for i, (aid, face, statut, rq_statut, notes) in enumerate(crops):
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, "
            " resolution_status, face, face_source, storage_status, storage_path) "
            "VALUES (?, 'si1', ?, ?, ?, 'pipeline', 'present', ?)",
            (aid, i, statut, face, f"ebay/si1/{aid}.png"),
        )
        conn.execute(
            "INSERT INTO review_queue (id, image_asset_id, status, decision_notes) "
            "VALUES (?, ?, ?, ?)",
            (f"rq_{aid}", aid, rq_statut, notes),
        )
    conn.commit()


# ─── 1. L'extraction : une seule définition, atteignable sans `training` ────


def test_les_helpers_de_rejet_sont_atteignables_sans_training():
    """Mutation : replacer les corps dans `steps/enqueue` et les y importer
    depuis là → rouge.

    C'est LA raison d'être de `store/review_routing.py`. Dans l'image lean du
    VPS — le seul writer — `import sources._base.steps.enqueue` lève
    `No module named 'training'`. Sans cette extraction, toute passe corrective
    devait réécrire le rejet en SQL, donc en faire une seconde copie.
    """
    src = (ML_DIR / "store" / "review_routing.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    importes = {
        n.module.split(".")[0]
        for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module
    } | {
        a.name.split(".")[0]
        for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names
    }
    interdits = importes & {"training", "cv2", "torch", "numpy", "PIL", "review",
                            "sources", "serving"}
    assert not interdits, (
        f"store/review_routing.py doit rester atteignable depuis l'image lean, "
        f"or il importe {interdits}")


def test_la_definition_est_unique():
    """Mutation : recopier un corps dans `enqueue` au lieu de l'importer → rouge."""
    from sources._base.steps import enqueue
    from store import review_routing

    assert enqueue._reject_crop_terminal is review_routing.reject_crop_terminal
    assert enqueue._kind_for_source_image is review_routing.kind_for_source_image
    assert (enqueue._route_decision_for_source_image
            is review_routing.route_decision_for_source_image)

    src = (ML_DIR / "sources" / "_base" / "steps" / "enqueue.py").read_text(
        encoding="utf-8")
    assert "def _reject_crop_terminal(" not in src, (
        "le corps est revenu dans enqueue — il y a donc deux définitions")


# ─── 2. La passe rejette, et épargne les deux sticky ───────────────────────


def test_la_passe_rejette_les_revers_ouverts(tmp_path, capsys):
    """Mutation : retirer `AND a.face = 'reverse'` du SELECT → rouge (l'avers
    serait rejeté aussi)."""
    db = tmp_path / "db.sqlite"
    conn = Store(db)._connection()  # noqa: SLF001
    _monte(conn, [
        ("rev1", "reverse", "needs_review", "open", None),
        ("obv1", "obverse", "needs_review", "open", None),
    ])

    assert passe(["--db", str(db), "--apply"]) == 0

    v = sqlite3.connect(db)
    v.row_factory = sqlite3.Row
    rev = v.execute("SELECT resolution_status, training_eligible, quality_reason "
                    "FROM image_assets WHERE id='rev1'").fetchone()
    assert rev["resolution_status"] == "rejected"
    assert rev["training_eligible"] == 0
    assert rev["quality_reason"] == "face_reverse"
    assert v.execute("SELECT status FROM review_queue WHERE id='rq_rev1'"
                     ).fetchone()[0] == "done"

    obv = v.execute("SELECT resolution_status FROM image_assets WHERE id='obv1'"
                    ).fetchone()
    assert obv["resolution_status"] == "needs_review", "l'avers doit être intact"


def test_la_passe_epargne_un_crop_restaure_a_la_main(tmp_path):
    """Mutation : retirer la garde `decision_notes == 'restored'` → rouge.

    Un `/restore` est un geste humain délibéré : le réécraser effacerait la
    seule donnée qu'aucun calcul ne régénère. Mesuré : 8 au canonique.
    """
    db = tmp_path / "db.sqlite"
    conn = Store(db)._connection()  # noqa: SLF001
    _monte(conn, [("rev2", "reverse", "needs_review", "open", "restored")])

    assert passe(["--db", str(db), "--apply"]) == 0

    v = sqlite3.connect(db)
    assert v.execute("SELECT resolution_status FROM image_assets WHERE id='rev2'"
                     ).fetchone()[0] == "needs_review"


def test_la_passe_epargne_un_crop_deja_tranche(tmp_path):
    """Mutation : retirer la garde `resolution_status != 'needs_review'` → rouge."""
    db = tmp_path / "db.sqlite"
    conn = Store(db)._connection()  # noqa: SLF001
    _monte(conn, [("rev3", "reverse", "manual", "open", None)])

    assert passe(["--db", str(db), "--apply"]) == 0

    v = sqlite3.connect(db)
    assert v.execute("SELECT resolution_status FROM image_assets WHERE id='rev3'"
                     ).fetchone()[0] == "manual"


def test_le_dry_run_n_ecrit_rien(tmp_path):
    """Mutation : faire écrire le dry-run → rouge."""
    db = tmp_path / "db.sqlite"
    conn = Store(db)._connection()  # noqa: SLF001
    _monte(conn, [("rev4", "reverse", "needs_review", "open", None)])

    assert passe(["--db", str(db)]) == 0

    v = sqlite3.connect(db)
    assert v.execute("SELECT resolution_status FROM image_assets WHERE id='rev4'"
                     ).fetchone()[0] == "needs_review"


def test_le_listing_est_reroute_en_face_reverse(tmp_path):
    """Mutation : retirer la boucle de reroute → rouge.

    Sans elle le funnel bench ne verrait jamais le bucket « revers commun 2€ » :
    le listing resterait annoncé comme à réviser alors qu'il ne l'est plus.
    """
    db = tmp_path / "db.sqlite"
    conn = Store(db)._connection()  # noqa: SLF001
    _monte(conn, [("rev5", "reverse", "needs_review", "open", None)])

    assert passe(["--db", str(db), "--apply"]) == 0

    v = sqlite3.connect(db)
    v.row_factory = sqlite3.Row
    si = v.execute("SELECT route_decision, route_reason FROM source_images "
                   "WHERE id='si1'").fetchone()
    assert si["route_decision"] == "rejected"
    assert si["route_reason"] == "face_reverse"
