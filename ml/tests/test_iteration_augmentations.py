"""Unit tests for C-1 — cible training >100 + réfs BCE/EUR-Lex dans le seed pool.

Couvre la rupture A (docs/cohort-pipeline) : la cible d'augmentation est
calculée dynamiquement (×10/source, plancher 100) et les réfs canoniques
officielles (BCE / EUR-Lex JO) alimentent le bake en filet pour les classes
pauvres en crops eBay.

Run: `.venv/bin/python -m pytest ml/tests/test_iteration_augmentations.py -q`
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from state import Store  # noqa: E402
from training.iteration_augmentations import (  # noqa: E402
    AUG_PER_SOURCE,
    FLOOR_REAL_EBAY,
    TARGET_MIN_PER_COIN,
    _canonical_ref_images,
    _target_per_coin,
)


def test_target_per_coin_floor_and_scaling():
    # Classe pauvre (réfs seules) → plancher 100.
    assert _target_per_coin(2, None) == TARGET_MIN_PER_COIN
    assert _target_per_coin(0, None) == TARGET_MIN_PER_COIN
    assert _target_per_coin(9, 100) == TARGET_MIN_PER_COIN  # 9×10=90 < 100
    # Classe riche en sources réelles → ×10 domine (l'exemple du PO : 11 → 110).
    assert _target_per_coin(11, None) == 110
    assert _target_per_coin(17, 100) == 170  # at-2005 : 15 eBay + obverse + BCE
    # variant_count agit comme plancher optionnel quand > cible dynamique.
    assert _target_per_coin(3, 150) == 150
    # Constantes alignées sur la spec.
    assert AUG_PER_SOURCE == 10
    assert FLOOR_REAL_EBAY == 10


def test_canonical_ref_images_filters_source_role_and_existence(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    conn.execute("PRAGMA foreign_keys=OFF")  # pas de coins parent dans ce test isolé
    present = tmp_path / "obverse_bce.webp"
    present.write_bytes(b"webp")
    rows = [
        ("c", "bce_official", "obverse", str(present)),                 # gardé
        ("c", "eurlex_jo", "obverse", str(tmp_path / "gone.webp")),     # fichier absent → ignoré
        ("c", "numista_api", "obverse", str(present)),                  # source exclue
        ("c", "bce_official", "reverse", str(present)),                 # revers → exclu
    ]
    conn.executemany(
        "INSERT INTO coin_canonical_images (eurio_id, source, role, local_path) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    # Seule la ligne BCE obverse dont le fichier existe est retenue.
    assert _canonical_ref_images("c", store) == [present]
    # eurio_id inconnu → liste vide.
    assert _canonical_ref_images("does-not-exist", store) == []


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
