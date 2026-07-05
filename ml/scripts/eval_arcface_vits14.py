"""Éval held-out du fine-tune ArcFace vits14 vs zero-shot (offline).

Protocole = celui du bench encodeurs : banque d'ancres = avers canonique
de chaque classe (composition 2eur_all), queries = crops du split TEST du
dataset ArcFace (jamais vus à l'entraînement, split par listing). Recall
@1/@5 global + bande pays. Chaque candidat encode ancres ET queries avec
son propre modèle/préprocessing.

Candidats :
  - zero-shot dinov2_vits14 (baseline — ce que le bench students a mesuré)
  - checkpoint fine-tuné (``--ckpt``, défaut checkpoints/arcface_vits14_v1)
  - optionnel ``--with-vitl14`` : zero-shot vitl14 (référence haute serveur)

Usage:
    .venv/bin/python -m scripts.eval_arcface_vits14
    .venv/bin/python -m scripts.eval_arcface_vits14 --ckpt checkpoints/arcface_vits14_v1/best_model.pth --out eval.md
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from training.foundation import (  # noqa: E402
    build_transform,
    encode_paths,
    load_encoder,
    pick_device,
)
from training.foundation.anchors import (  # noqa: E402
    DATASETS_DIR,
    _commemo_paths_with_eid,  # noqa: PLC2701
    _standard_paths_with_eid,  # noqa: PLC2701
)

from store import resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")
DATASET_ROOT = ML_DIR / "datasets" / "arcface_vits14_v1"
DEFAULT_CKPT = ML_DIR / "checkpoints" / "arcface_vits14_v1" / "best_model.pth"
TOP_K = 5


def _load_candidates(args) -> list[tuple[str, torch.nn.Module, object]]:
    """[(label, model, transform)] — chaque candidat a SON préprocessing."""
    device = pick_device()
    out: list[tuple[str, torch.nn.Module, object]] = []

    encoder, _ = load_encoder(device=device)
    out.append(("zero-shot dinov2_vits14", encoder, build_transform()))

    if args.with_vitl14:
        enc_l, _ = load_encoder(device=device, encoder_version="dinov2-vitl14")
        out.append(("zero-shot dinov2_vitl14 (réf. serveur)", enc_l, build_transform()))

    ckpt_path = Path(args.ckpt)
    if ckpt_path.is_file():
        from training.train_embedder import build_embedder, get_val_transforms

        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        model = build_embedder(
            ckpt.get("backbone", "dinov2_vits14"), ckpt["embedding_dim"]
        )
        model.load_state_dict(ckpt["model_state_dict"])
        model.eval()
        model.to(device)
        label = (
            f"ArcFace fine-tuné (epoch {ckpt.get('epoch')}, "
            f"{ckpt.get('model_version') or ckpt_path.name})"
        )
        out.append((label, model, get_val_transforms()))
    else:
        print(f"!! checkpoint absent : {ckpt_path} — éval zero-shot seulement",
              file=sys.stderr)
    return out


def _recalls(
    anchor_classes: list[str],
    anchor_embs: np.ndarray,
    crops: list[dict],
    crop_embs: np.ndarray,
) -> dict:
    g1 = g5 = 0
    c_total = c1 = c5 = 0
    cls_arr = np.array(anchor_classes)
    sims_all = crop_embs @ anchor_embs.T  # (N, C)
    for i, crop in enumerate(crops):
        sims = sims_all[i]
        order = np.argsort(-sims)[:TOP_K]
        ranked = [anchor_classes[int(j)] for j in order]
        if ranked[0] == crop["class"]:
            g1 += 1
        if crop["class"] in ranked:
            g5 += 1
        tc = crop.get("target_country")
        if tc:
            mask = np.array([c[:2] == tc for c in cls_arr])
            if mask.any():
                c_total += 1
                masked = np.where(mask, sims, -np.inf)
                corder = np.argsort(-masked)[:TOP_K]
                cranked = [anchor_classes[int(j)] for j in corder]
                if cranked[0] == crop["class"]:
                    c1 += 1
                if crop["class"] in cranked:
                    c5 += 1
    n = len(crops)
    return {"n": n, "g1": g1, "g5": g5, "c_total": c_total, "c1": c1, "c5": c5}


def _pct(a: int, b: int) -> str:
    return f"{100.0 * a / b:.1f}%" if b else "—"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ckpt", default=str(DEFAULT_CKPT))
    parser.add_argument("--manifest", default=str(DATASET_ROOT / "test_manifest.json"))
    parser.add_argument("--with-vitl14", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    crops = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    crops = [c for c in crops if Path(c["path"]).is_file()]
    print(f"Test held-out : {len(crops)} crops", file=sys.stderr)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    anchors = dict(_commemo_paths_with_eid(conn, DATASETS_DIR)) | dict(
        _standard_paths_with_eid(conn, DATASETS_DIR)
    )
    conn.close()
    anchor_classes = sorted(anchors)
    anchor_paths = [anchors[c] for c in anchor_classes]

    device = pick_device()
    lines = [
        "# Éval held-out — ArcFace vits14 vs zero-shot",
        "",
        f"- {len(crops)} crops test (split par listing, jamais vus au "
        f"fine-tune) · {len(anchor_classes)} ancres canoniques",
        "- Même protocole que le bench encodeurs (recall vs avers canonique, "
        "bande pays = pays cible du listing).",
        "",
        "| Candidat | global@1 | global@5 | pays@1 | pays@5 |",
        "|---|---|---|---|---|",
    ]

    for label, model, transform in _load_candidates(args):
        print(f"=== {label} ===", file=sys.stderr)
        kept_a, a_embs = encode_paths(
            anchor_paths, encoder=model, device=device, transform=transform
        )
        kept_set = {str(p) for p in kept_a}
        classes = [c for c, p in zip(anchor_classes, anchor_paths) if str(p) in kept_set]
        kept_c, c_embs = encode_paths(
            [Path(c["path"]) for c in crops],
            encoder=model, device=device, transform=transform,
        )
        kept_crop_set = {str(p): i for i, p in enumerate(kept_c)}
        crops_kept = [c for c in crops if str(Path(c["path"])) in kept_crop_set]
        embs = np.vstack([
            c_embs[kept_crop_set[str(Path(c["path"]))]] for c in crops_kept
        ])
        r = _recalls(classes, a_embs, crops_kept, embs)
        lines.append(
            f"| {label} | {_pct(r['g1'], r['n'])} | {_pct(r['g5'], r['n'])} "
            f"| {_pct(r['c1'], r['c_total'])} | {_pct(r['c5'], r['c_total'])} |"
        )
        print(f"  g@1={_pct(r['g1'], r['n'])} pays@1={_pct(r['c1'], r['c_total'])}",
              file=sys.stderr)

    lines.append("")
    text = "\n".join(lines)
    print()
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"\n→ écrit dans {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
