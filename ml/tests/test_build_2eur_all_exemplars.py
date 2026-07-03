"""Builder 2eur_all multi-exemplaires (B) — assemblage + FPS + références.

Encodeur monkeypatché (vecteurs déterministes) pour tester TOUT le câblage sans
torch : sélection canonique + FPS diversifiant + honneur des pins, écriture de
``dino_class_references`` et des ``asset_ids`` du bank.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store  # noqa: E402
from store.dino_references import set_reference_override  # noqa: E402
from training.foundation import anchors as A  # noqa: E402

# Vecteurs par marqueur de chemin (3-D, normalisés à la volée).
_VEC = {
    "obverse.jpg": [1.0, 0.0, 0.0],     # canonique
    "dupA": [0.99, 0.14, 0.0],          # quasi-doublon du canonique
    "dupB": [0.98, 0.19, 0.0],          # quasi-doublon
    "div": [0.40, 0.90, 0.0],           # diversifiant (loin du canonique)
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


def _seed(conn, datasets_dir: Path):
    # Commémo avec numista_id → canonique attendu à <datasets>/<n>/obverse.jpg.
    conn.execute(
        "INSERT OR REPLACE INTO coins (eurio_id, country, country_name, year, "
        "face_value, is_commemorative, numista_id, raw_payload_json) "
        "VALUES ('fr-2015-a', 'FR', 'France', 2015, 2.0, 1, 5001, '{}')",
    )
    obv_dir = datasets_dir / "5001"
    obv_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (128, 128, 128)).save(obv_dir / "obverse.jpg")

    for aid, sp in [("dupA", "dupA.png"), ("dupB", "dupB.png"), ("div", "div.png")]:
        sid = f"SI_{aid}"
        conn.execute(
            "INSERT INTO source_images (id, source, source_ref) VALUES (?, 'ebay', ?)",
            (sid, f"ref_{aid}"),
        )
        conn.execute(
            "INSERT INTO image_assets (id, source_image_id, crop_index, eurio_id, "
            "resolution_status, face, denom, training_eligible, storage_path) "
            "VALUES (?, ?, 0, 'fr-2015-a', 'manual', 'obverse', '2eur', 1, ?)",
            (aid, sid, sp),
        )


def _patch_encoder(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(A, "load_encoder", lambda **kw: (None, None))
    monkeypatch.setattr(A, "build_transform", lambda: None)
    monkeypatch.setattr(A, "encode_paths", _fake_encode)
    # Le builder résout les crops via local_path (→ MinIO si absent du cache).
    # On le court-circuite : chemin factice qui porte le storage_key (le fake
    # encoder mappe le vecteur sur ce marqueur).
    monkeypatch.setattr(
        "shared.storage.local_cache.local_path",
        lambda bucket, key: Path("/fake") / bucket / key,
    )


def test_build_selects_canonical_plus_diverse_exemplar(tmp_path, monkeypatch):
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets)
        bank = A.build_anchors_2eur_all(
            conn=conn, datasets_dir=datasets, encoder_version="dinov2-vitl14",
            force_recompute=True, exemplars_per_class=1, floor_sim=0.0,
        )
    # Bank : toutes les lignes keyées sur la classe (rep eurio_id).
    assert bank.eurio_ids[0] == "fr-2015-a"
    assert None in bank.asset_ids  # la ligne canonique
    exemplar_assets = [a for a in bank.asset_ids if a]
    # 1 exemplaire demandé → FPS choisit le DIVERSIFIANT, pas un quasi-doublon.
    assert exemplar_assets == ["div"]

    with store._writing() as conn:
        rows = conn.execute(
            "SELECT method, asset_id FROM dino_class_references "
            "WHERE class_id='fr-2015-a' ORDER BY rank",
        ).fetchall()
    assert rows[0]["method"] == "canonical" and rows[0]["asset_id"] is None
    assert any(r["method"] == "fps" and r["asset_id"] == "div" for r in rows)


def test_build_honors_pin_and_exclude(tmp_path, monkeypatch):
    datasets = tmp_path / "datasets"
    _patch_encoder(monkeypatch, tmp_path)
    store = Store(tmp_path / "t.db")
    with store._writing() as conn:
        _seed(conn, datasets)
        # Épingle dupB (que FPS ne choisirait pas en 1er) ; bannit div.
        set_reference_override(conn, class_id="fr-2015-a", eurio_id="fr-2015-a",
                               asset_id="dupB", method="manual_pin")
        set_reference_override(conn, class_id="fr-2015-a", eurio_id="fr-2015-a",
                               asset_id="div", method="manual_exclude")
        bank = A.build_anchors_2eur_all(
            conn=conn, datasets_dir=datasets, encoder_version="dinov2-vitl14",
            force_recompute=True, exemplars_per_class=2, floor_sim=0.0,
        )
    assets = set(a for a in bank.asset_ids if a)
    assert "dupB" in assets       # pin honoré
    assert "div" not in assets    # exclude honoré (jamais dans le bank)
