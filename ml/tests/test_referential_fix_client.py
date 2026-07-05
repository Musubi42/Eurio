"""C4b (client) — calcul du diff référentiel + apply local (Model A).

Couvre la partie SANS réseau/PIL du refactor ``serving.referential_fix_apply`` :
``_compute_coins_diff`` (pur, lit la réplique) et ``_apply_diff`` en mode local
(sync off) qui applique via ``store.referential_fix.apply_referential_fix``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from serving import referential_fix_apply as rfa
from store import Store

EXISTING = "be-2014-2eur-x"
NEW = "be-2014-2eur-new"


def _case():
    return {
        "shape": "B",
        "swap": {"eurio_id": EXISTING, "current_numista_id": 100, "new_numista_id": 150},
        "new_row": {
            "eurio_id": NEW, "country": "BE", "year": 2015, "face_value": 2.0,
            "numista_id": 200, "theme": "Expo", "design_description": "d",
        },
        "source_attributions": [],
    }


def _seed(conn):
    conn.execute(
        "INSERT INTO coins (eurio_id, country, country_name, year, face_value, "
        "is_commemorative, numista_id, raw_payload_json) "
        "VALUES (?, 'BE', 'Belgium', 2014, 2.0, 0, 100, ?)",
        (EXISTING, json.dumps({"cross_refs": {"numista_id": 100}})),
    )


def test_compute_coins_diff_shapes(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _seed(conn)
    ci, cu, moved = rfa._compute_coins_diff(conn, _case())
    assert ci["eurio_id"] == NEW and ci["numista_id"] == 200
    assert ci["country_name"] == "Belgium" and ci["ref_native_id"] == "200"
    assert cu["eurio_id"] == EXISTING and cu["numista_id"] == 150
    # le payload existant re-pointe le numista_id post-swap
    assert json.loads(cu["raw_payload_json"])["cross_refs"]["numista_id"] == 150
    assert moved == []


def test_apply_diff_local_mode(tmp_path, monkeypatch):
    monkeypatch.setattr("client.http.sync_enabled", lambda: False)
    store = Store(tmp_path / "t.db")
    conn = store._connection()  # noqa: SLF001
    _seed(conn)
    ci, cu, _ = rfa._compute_coins_diff(conn, _case())
    diff = {
        "case_id": "c1", "preflight": rfa._preflight_dict(_case()),
        "coins_insert": ci, "coins_update": cu, "canonical_images": [],
    }
    step = rfa._apply_diff(diff, tmp_path / "t.db")
    assert step["status"] == "ok" and step["diagnostic"]["mode"] == "local"
    # relit sur une nouvelle connexion : la mutation est bien committée
    conn2 = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    assert conn2.execute("SELECT numista_id FROM coins WHERE eurio_id=?", (NEW,)).fetchone()[0] == 200
    assert conn2.execute("SELECT numista_id FROM coins WHERE eurio_id=?", (EXISTING,)).fetchone()[0] == 150
