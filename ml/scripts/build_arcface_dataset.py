"""Matérialise le dataset ArcFace vits14 depuis eurio.db (chantier
dino-suggestions, fine-tune du student retenu).

Espace de classes = EXACTEMENT la composition de la banque d'ancres
``2eur_all`` : 1 classe par 2€ commémo (eurio_id) + 1 classe par design
group de 2€ courante (eurio_id du représentant). Cohérent avec la review
(décision = représentant) et l'audit.

Sources d'images :
  - **canonique** : l'avers Numista de chaque classe (1 image, toujours
    en train — c'est aussi l'ancre de référence au matching) ;
  - **wild** : les crops eBay résolus à la main en review
    (``image_assets.resolution_status='manual'``, face ≠ reverse),
    labellisés via coins → canonical_eurio_id → représentant de groupe.

Split DÉTERMINISTE par listing parent (``source_image_id`` hashé) pour
éviter la fuite intra-listing (24 crops d'un même lot se ressemblent) :
80 % train / 10 % val / 10 % test. Le test n'est PAS matérialisé en
dossiers : il sort en manifest JSON consommé par
``scripts/eval_arcface_vits14.py`` (recall vs banque d'ancres, comparé au
zero-shot).

Usage:
    .venv/bin/python -m scripts.build_arcface_dataset
    .venv/bin/python -m scripts.build_arcface_dataset --root datasets/arcface_vits14_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from training.foundation.anchors import (  # noqa: E402
    DATASETS_DIR,
    _commemo_paths_with_eid,  # noqa: PLC2701 — même repo, même chantier
    _standard_paths_with_eid,  # noqa: PLC2701
)
from scripts.audit_dino_suggestions import _standard_rep_map  # noqa: E402

DB_PATH = ML_DIR / "state" / "eurio.db"
DEFAULT_ROOT = ML_DIR / "datasets" / "arcface_vits14_v1"


# Le stack d'augmentation runtime opère « on the already-normalized 224×224
# tight coin crop » (contrat get_legacy_train_transforms). Matérialiser en
# pleine résolution multiplie le coût des transforms géométriques par ~25
# (epoch passée de ~3 min à ~1 h sur MPS, mesuré le 2026-06-11).
TRAIN_PX = 224


def _materialize(src: Path, dst: Path) -> None:
    """Copie ``src`` resizée à TRAIN_PX×TRAIN_PX (bicubique, JPEG q92)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        img = img.convert("RGB")
        if img.size != (TRAIN_PX, TRAIN_PX):
            img = img.resize((TRAIN_PX, TRAIN_PX), Image.Resampling.BICUBIC)
        img.save(dst, "JPEG", quality=92)


def _split_of(source_image_id: str) -> str:
    """Split stable par listing : md5 → 0-7 train, 8 val, 9 test."""
    h = int(hashlib.md5(source_image_id.encode()).hexdigest()[:8], 16) % 10
    return "train" if h < 8 else ("val" if h == 8 else "test")


def _class_of(
    eurio_id: str,
    canonical_map: dict[str, str],
    rep_map: dict[str, str],
) -> str:
    """eurio_id décidé → classe (canonical d'abord, puis représentant)."""
    eid = canonical_map.get(eurio_id, eurio_id)
    return rep_map.get(eid, eid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    args = parser.parse_args()
    root = Path(args.root)
    if root.exists():
        shutil.rmtree(root)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # ---- Espace de classes + image canonique par classe ------------------
    commemo = _commemo_paths_with_eid(conn, DATASETS_DIR)
    standard = _standard_paths_with_eid(conn, DATASETS_DIR)
    canonical_by_class: dict[str, Path] = dict(commemo) | dict(standard)
    classes = sorted(canonical_by_class)
    print(f"Classes : {len(classes)} (commémo {len(commemo)} + groupes "
          f"standards {len(standard)})", file=sys.stderr)

    rep_map = _standard_rep_map(conn)
    canonical_map = {
        r["eurio_id"]: r["canonical_eurio_id"]
        for r in conn.execute(
            "SELECT eurio_id, canonical_eurio_id FROM coins "
            "WHERE canonical_eurio_id IS NOT NULL"
        )
    }

    # ---- Crops wild résolus à la main ------------------------------------
    rows = conn.execute(
        """
        SELECT a.id AS asset_id, a.eurio_id, a.storage_path,
               a.source_image_id, s.target_eurio_id
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
          JOIN coins c ON c.eurio_id = a.eurio_id
         WHERE a.resolution_status = 'manual'
           AND a.eurio_id IS NOT NULL
           AND a.storage_path IS NOT NULL
           AND (a.face IS NULL OR a.face != 'reverse')
           AND c.face_value = 2.0
        """
    ).fetchall()
    conn.close()

    from shared.storage.local_cache import local_path

    counts: Counter[str] = Counter()
    skipped = {"no_class": 0, "no_file": 0}
    test_manifest: list[dict] = []
    n_copied = {"train": 0, "val": 0}

    for r in rows:
        cls = _class_of(r["eurio_id"], canonical_map, rep_map)
        if cls not in canonical_by_class:
            skipped["no_class"] += 1
            continue
        try:
            src = local_path("enrichment-crops", r["storage_path"])
        except FileNotFoundError:
            skipped["no_file"] += 1
            continue
        if not src.is_file():
            skipped["no_file"] += 1
            continue
        split = _split_of(r["source_image_id"])
        counts[split] += 1
        if split == "test":
            target_eid = r["target_eurio_id"]
            test_manifest.append({
                "asset_id": r["asset_id"],
                "path": str(src),
                "class": cls,
                "target_country": (
                    target_eid[:2].lower()
                    if target_eid and len(target_eid) >= 2 else None
                ),
            })
            continue
        dst = root / split / cls / f"{r['asset_id']}.jpg"
        _materialize(src, dst)
        n_copied[split] += 1

    # ---- Canoniques : 1 image par classe, toujours en train --------------
    for cls, src in canonical_by_class.items():
        _materialize(src, root / "train" / cls / "canonical.jpg")

    manifest_path = root / "test_manifest.json"
    manifest_path.write_text(
        json.dumps(test_manifest, indent=1), encoding="utf-8"
    )

    print(f"train : {n_copied['train']} crops wild + {len(classes)} canoniques",
          file=sys.stderr)
    print(f"val   : {n_copied['val']} crops wild", file=sys.stderr)
    print(f"test  : {len(test_manifest)} crops (manifest, non matérialisé)",
          file=sys.stderr)
    print(f"skips : {skipped}", file=sys.stderr)
    print(f"→ {root}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
