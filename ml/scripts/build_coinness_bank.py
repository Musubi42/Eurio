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
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parents[1]
DATASETS_DIR = ML_DIR / "datasets"
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    from foundation.encoder import (
        DEFAULT_ENCODER_VERSION, build_transform, encode_paths, load_encoder,
    )

    refs = collect_ref_paths(args.limit)
    if not refs:
        print("Aucune réf avers/revers trouvée dans datasets/ — abort.")
        return 1
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
