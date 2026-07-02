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

from training.foundation.enrichment import MIN_REAL, TRAINING_TARGET  # noqa: E402
from store import Store  # noqa: E402
from training.iteration_augmentations import (  # noqa: E402
    _canonical_ref_images,
    _ebay_training_sources,
    _target_per_coin,
)


def test_target_per_coin_dynamic_factor():
    # Facteur dynamique ceil(100/seed) appliqué uniformément → projeté ≥ 100,
    # SANS gonflement ×10 (l'exemple du PO : 15 réels → ×7 → 105).
    assert _target_per_coin(15, None) == 105
    assert _target_per_coin(21, None) == 105   # ×5
    # Classe pauvre (peu de sources) → facteur élevé, projeté juste au-dessus de 100.
    assert _target_per_coin(2, None) == 100     # ×50
    assert _target_per_coin(3, None) == 102     # ×34
    assert _target_per_coin(9, None) == 108     # ×12
    # Classe riche : 11 → ×10 → 110 ; at-2005 (17 sources) → ×6 → 102 (plus de 170).
    assert _target_per_coin(11, None) == 110
    assert _target_per_coin(17, 100) == 102
    # Tout projeté est ≥ la cible dès qu'il y a au moins une source.
    for n in (1, 2, 3, 11, 15, 17, 21, 50):
        assert _target_per_coin(n, None) >= TRAINING_TARGET
    # variant_count agit comme plancher optionnel quand > cible dynamique.
    assert _target_per_coin(3, 150) == 150
    # Plancher qualité « sources réelles » inchangé.
    assert MIN_REAL == 10


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


def test_ebay_training_sources_excludes_confirmed_reverse(tmp_path, monkeypatch):
    """Gate bake P3 (improvement-loop) : un crop ``face='reverse'`` éligible
    n'entre PAS au train ; NULL / 'unknown' / 'obverse' passent."""
    import shared.storage.local_cache as lc

    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    conn.execute("PRAGMA foreign_keys=OFF")  # pas de coins parent, test isolé
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref) "
        "VALUES ('si1', 'ebay', 'ref1')"
    )
    crops = [
        ("a-obv", "obverse"),
        ("a-null", None),
        ("a-unk", "unknown"),
        ("a-rev", "reverse"),  # seul exclu
    ]
    for idx, (aid, face) in enumerate(crops):
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, "
            "eurio_id, resolution_status, face, training_eligible, "
            "storage_path) VALUES (?, 'si1', ?, 'c', 'manual', ?, 1, ?)",
            (aid, idx, face, f"ebay/si1/{aid}.png"),
        )
    conn.commit()
    # local_path read-through → fichiers locaux du test (pas de MinIO ici).
    files = {}
    for aid, _ in crops:
        p = tmp_path / f"{aid}.png"
        p.write_bytes(b"png")
        files[f"ebay/si1/{aid}.png"] = p
    monkeypatch.setattr(lc, "local_path", lambda bucket, key: files[key])

    paths = _ebay_training_sources("c", store)
    names = {p.stem for p in paths}
    assert names == {"a-obv", "a-null", "a-unk"}


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
