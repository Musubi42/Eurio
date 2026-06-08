"""build_coinness_bank.py — banque DINO « coin-ness » pour le verify is-coin du census.

Encode les réfs canoniques (avers + revers) en DINOv2 et écrit la banque dans
`ml/state/foundation_coinness.npz`. Le census-ladder (`scan/census.py`, étage ②)
garde une boîte YOLO comme « pièce » si sa sim DINO max à cette banque ≥ τ.

Doctrine (cf. docs/cohort-pipeline/census-detector-design.md §2) : le signal doit
être AGNOSTIQUE à la dénomination ET à la face → on encode avers ET revers. Réfs
locales dispo = 2€ uniquement (`ml/datasets/<nid>/{obverse,reverse}.jpg`, ~1100
images), bien alignées avec le bench mix-zone-17 (tout 2€). Trou dénom (cents/1€)
assumé pour plus tard.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/build_coinness_bank.py            # build (cache DINO réutilisé)
  .venv/bin/python scripts/build_coinness_bank.py --limit 50 # probe
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parents[1]
DATASETS_DIR = ML_DIR / "datasets"
DB_PATH = ML_DIR / "state" / "eurio.db"
BENCH_PATH = ML_DIR / "state" / "coin_census_bench" / "bench_v0.json"
OUT_PATH = ML_DIR / "state" / "foundation_coinness.npz"

FACE_FILES = ("obverse.jpg", "reverse.jpg")


def collect_ref_paths(limit: int = 0) -> list[tuple[str, str, str]]:
    """(path, nid, face) pour chaque avers/revers présent dans datasets/."""
    out: list[tuple[str, str, str]] = []
    for d in sorted(DATASETS_DIR.iterdir()):
        if not (d.is_dir() and d.name.isdigit()):
            continue
        for fname in FACE_FILES:
            p = d / fname
            if p.exists():
                out.append((str(p), d.name, fname.replace(".jpg", "")))
    if limit:
        out = out[:limit]
    return out


def collect_real_crop_paths() -> list[tuple[str, str, str]]:
    """Crops eBay RÉELS validés humainement, HORS bench (anti-fuite), pour combler
    le trou de domaine (capsule/glare/revers) du gate is-coin.

    Filtre haute-confiance UNIQUEMENT (`manual`/`auto_phash`/`training_eligible`) :
    ces crops sont la sortie de YOLO+Hough → en prendre des non-validés réinjecterait
    le clutter/fragments que le gate doit justement rejeter. On EXCLUT toute image du
    bench (`source_image_id`) — sinon fuite banque→bench = mesure faussée.
    """
    from shared.storage.local_cache import local_path

    bench = json.loads(BENCH_PATH.read_text())
    bench_sids = {x["source_image_id"] for x in bench}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, source_image_id, storage_path, eurio_id
          FROM image_assets
         WHERE storage_path IS NOT NULL AND storage_status = 'present'
           AND (resolution_status IN ('manual', 'auto_phash')
                OR COALESCE(training_eligible, 0) = 1)
        """
    ).fetchall()
    conn.close()

    out: list[tuple[str, str, str]] = []
    for r in rows:
        if r["source_image_id"] in bench_sids:
            continue
        try:
            p = local_path("enrichment-crops", r["storage_path"])
        except FileNotFoundError:
            continue
        if Path(p).exists():
            out.append((str(p), r["eurio_id"] or r["id"], "real_crop"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--include-real", action="store_true",
                    help="ajoute les crops eBay validés hors-bench (domaine capsule/glare/revers)")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    from training.foundation.encoder import (
        DEFAULT_ENCODER_VERSION, build_transform, encode_paths, load_encoder,
    )

    refs = collect_ref_paths(args.limit)
    if not refs:
        print("Aucune réf avers/revers trouvée dans datasets/ — abort.")
        return 1
    if args.include_real:
        real = collect_real_crop_paths()
        print(f"+ {len(real)} crops eBay réels validés hors-bench (domaine)")
        refs = refs + real
    paths = [r[0] for r in refs]
    by_face: dict[str, int] = {}
    for _, _, face in refs:
        by_face[face] = by_face.get(face, 0) + 1
    print(f"Réfs coin-ness : {len(refs)} images ({by_face})")

    enc, dev = load_encoder()
    tf = build_transform()
    kept, matrix = encode_paths(paths, encoder=enc, device=dev, transform=tf, batch_size=32)
    print(f"Encodées : {len(kept)} / {len(paths)} (dim={matrix.shape[1] if matrix.size else 0})")

    # Aligne les labels sur les chemins effectivement encodés (encode_paths peut
    # droper des images illisibles). `kept` est ordonné comme `refs` (encode_paths
    # préserve l'ordre) → on filtre `refs` par appartenance à `kept`, ce qui garde
    # l'ordre et donc l'alignement labels[i] ↔ matrix[i]. Assert de garde.
    kept_set = {str(p) for p in kept}
    labels = [(nid, face) for (p, nid, face) in refs if p in kept_set]
    assert len(labels) == matrix.shape[0], (
        f"désalignement labels({len(labels)})/matrix({matrix.shape[0]})"
    )

    meta = json.dumps({
        "encoder_version": DEFAULT_ENCODER_VERSION,
        "kind": "coinness_2eur_obv_rev",
        "count": len(kept),
        "dim": int(matrix.shape[1]) if matrix.size else 0,
        "by_face": by_face,
    })
    out_p = Path(args.out)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_p,
        matrix=matrix.astype(np.float32),
        nids=np.array([l[0] for l in labels], dtype=np.str_),
        faces=np.array([l[1] for l in labels], dtype=np.str_),
        meta=np.array([meta], dtype=np.str_),
    )
    print(f"→ {out_p}  ({matrix.shape})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
