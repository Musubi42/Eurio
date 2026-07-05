"""F02/C2 — ``confusion_map.fetch_coins`` lit coins + avers depuis eurio.db.

Vérifie : sélection des pièces avec numista_id + avers (URL), meilleure source
par priorité, filtre eurio_ids, limit. Plus aucune dépendance Supabase.
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store
from training.eval.confusion_map import fetch_coins


def _seed(db_path):
    store = Store(db_path)
    conn = store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO design_groups (id, designation) VALUES ('grp-a', 'Groupe A')"
    )
    # a : deux avers (numista_api + bce_official) → bce gagne (priorité 1)
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, numista_id, design_group_id) "
        "VALUES ('a', 'FR', 2002, 2.0, 111, 'grp-a')"
    )
    conn.execute(
        "INSERT INTO coin_canonical_images (eurio_id, source, role, url) "
        "VALUES ('a', 'numista_api', 'obverse', 'http://num/a.jpg')"
    )
    conn.execute(
        "INSERT INTO coin_canonical_images (eurio_id, source, role, url) "
        "VALUES ('a', 'bce_official', 'obverse', 'http://bce/a.webp')"
    )
    # b : un seul avers
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, numista_id) "
        "VALUES ('b', 'DE', 2002, 2.0, 222)"
    )
    conn.execute(
        "INSERT INTO coin_canonical_images (eurio_id, source, role, url) "
        "VALUES ('b', 'numista_api', 'obverse', 'http://num/b.jpg')"
    )
    # c : numista_id mais pas d'avers → exclu
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, numista_id) "
        "VALUES ('c', 'IT', 2002, 2.0, 333)"
    )
    # d : avers mais pas de numista_id → exclu
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value) "
        "VALUES ('d', 'ES', 2002, 2.0)"
    )
    conn.execute(
        "INSERT INTO coin_canonical_images (eurio_id, source, role, url) "
        "VALUES ('d', 'numista_api', 'obverse', 'http://num/d.jpg')"
    )
    conn.execute("COMMIT")


def test_fetch_coins_selects_and_prioritizes(tmp_path):
    db = tmp_path / "eurio.db"
    _seed(db)
    coins = fetch_coins(db_path=db)
    by_id = {c.eurio_id: c for c in coins}
    assert set(by_id) == {"a", "b"}  # c (no obverse) et d (no numista) exclus
    assert by_id["a"].obverse_url == "http://bce/a.webp"  # bce_official prioritaire
    assert by_id["a"].design_group_id == "grp-a"
    assert by_id["b"].numista_id == 222


def test_fetch_coins_filters_and_limits(tmp_path):
    db = tmp_path / "eurio.db"
    _seed(db)
    assert [c.eurio_id for c in fetch_coins(db_path=db, eurio_ids=["b"])] == ["b"]
    assert len(fetch_coins(db_path=db, limit=1)) == 1
