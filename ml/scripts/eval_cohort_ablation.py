"""Évalue un modèle ArcFace sur les captures device cohort, pour l'ablation
format crop (Step 3b du chantier, cf. `docs/roadmap.md`).

Pipeline d'éval :
  1. Lit le pull device (`debug_pull/<ts>/eval_real/`) : raws + manifest.jsonl
  2. Pour chaque capture raw, re-normalise avec le CropConfig MATCHING le modèle
     (sinon train/inference mismatch)
  3. Forward dans le modèle → embedding L2-normalisé
  4. Cosine similarity vs centroids du catalogue → top-K
  5. Compare top1 à la `eurio_id` vraie (depuis manifest) → is_correct
  6. Sortie CSV par capture + agrégats R@1 / R@5

Pré-requis : tu dois avoir entraîné le modèle SUR un dataset cropé avec le
MÊME CropConfig (cf. `scripts/recrop_with_config.py` + `training/train_embedder.py`
+ `training/compute_embeddings.py`).

Usage :
    cd ml
    .venv/bin/python -m scripts.eval_cohort_ablation \\
        --device-pull /path/to/debug_pull/20260601_120000 \\
        --model checkpoints/best_model_m10-feathered-s224-fw04.pth \\
        --embeddings output/embeddings_v1_m10-feathered.json \\
        --crop-config-json datasets/eurio-poc-m10-feathered-s224-fw04/_crop_config.json \\
        --output state/ablation_eval/m10-feathered-s224-fw04.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from torchvision import transforms

_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from scan.normalize_snap import CropConfig, normalize_device  # noqa: E402


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def load_crop_config(path: Path) -> CropConfig:
    """Charge un CropConfig depuis le _crop_config.json écrit par
    `recrop_with_config.py`."""
    d = json.loads(path.read_text())
    d.pop("_slug", None)
    return CropConfig(**d)


def load_embeddings(path: Path) -> tuple[list[str], np.ndarray, dict[str, list[str]]]:
    """Charge embeddings_v1.json. Retourne :
      - class_ids : ordre alpha des class_id (cohérent avec axis 0 de la matrix)
      - centroids : matrix (n_classes, embedding_dim), déjà L2-normalisée
      - eurio_to_class : map eurio_id → class_id (pour résoudre la vérité terrain)
    """
    raw = json.loads(path.read_text())
    coins = raw["coins"]
    class_ids = sorted(coins.keys())
    centroids = np.array([coins[c]["embedding"] for c in class_ids], dtype=np.float32)
    eurio_to_class: dict[str, list[str]] = defaultdict(list)
    for cid, payload in coins.items():
        for eid in payload.get("eurio_ids", []):
            eurio_to_class[eid].append(cid)
        # Cas fallback : si class_id est lui-même un eurio_id (mode eurio_id), map direct.
        if cid not in eurio_to_class:
            eurio_to_class[cid].append(cid)
    return class_ids, centroids, dict(eurio_to_class)


def load_model(checkpoint_path: Path, device: torch.device) -> tuple[torch.nn.Module, int]:
    from training.train_embedder import CoinEmbedder  # local import to avoid heavy boot
    ckpt = torch.load(str(checkpoint_path), map_location=device, weights_only=False)
    embedding_dim = ckpt["embedding_dim"]
    model = CoinEmbedder(embedding_dim=embedding_dim).to(device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return model, embedding_dim


def parse_manifest(manifest_path: Path) -> list[dict]:
    """Lit manifest.jsonl (1 ligne par snap, format défini dans ScanViewModel)."""
    entries = []
    for line in manifest_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"  ! manifest line skipped: {e}: {line[:100]}")
    return entries


def discover_captures(device_pull: Path) -> tuple[list[dict], Path]:
    """Trouve manifest.jsonl + raws sous device_pull/.

    Le pull copie eval_real/ avec manifest.jsonl à la racine et
    `<eurio_id>/<step>_p<n>_raw.jpg` par capture. Retourne :
      (entries, eval_real_dir) — `entries` enrichi avec absolute `raw_path` et
      `crop_path` quand existants.
    """
    eval_dir = device_pull / "eval_real"
    if not eval_dir.is_dir():
        # tolérance : layout direct sans le sous-dossier
        eval_dir = device_pull
    manifest = eval_dir / "manifest.jsonl"
    if not manifest.is_file():
        raise SystemExit(
            f"manifest.jsonl absent sous {eval_dir}. "
            "Vérifie le device pull (cf. `go-task -t app-android/Taskfile.yml pull-debug`)."
        )
    entries = parse_manifest(manifest)
    # Enrichis avec paths absolus
    for e in entries:
        eid = e.get("eurio_id")
        step = e.get("step_id")
        photo_idx = e.get("photo_index", 0) or 0
        if not eid or not step:
            continue
        suffix = f"_p{photo_idx}" if photo_idx > 0 else ""
        e["raw_path"] = str(eval_dir / eid / f"{step}{suffix}_raw.jpg")
        e["crop_path_device"] = str(eval_dir / eid / f"{step}{suffix}_crop.jpg")
    return entries, eval_dir


# ---------------------------------------------------------------------------
# Eval core
# ---------------------------------------------------------------------------

_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD = [0.229, 0.224, 0.225]


def _to_tensor_normalize(bgr: np.ndarray) -> torch.Tensor:
    """BGR uint8 (de normalize_device) → RGB float tensor [1,C,H,W] normalisé
    ImageNet. PAS de Resize car le crop est DÉJÀ à la bonne taille (output_size
    du CropConfig)."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    tfm = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=_IMAGENET_MEAN, std=_IMAGENET_STD),
    ])
    return tfm(pil).unsqueeze(0)


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v if n < 1e-8 else v / n


def _eval_one(raw_path: Path, model: torch.nn.Module,
               config: CropConfig, device: torch.device,
               centroids: np.ndarray, class_ids: list[str], top_k: int = 5,
               ) -> tuple[list[str], list[float], str | None]:
    """Re-normalise raw + forward + top-K. Retourne (top_classes, top_sims, err)."""
    bgr = cv2.imread(str(raw_path), cv2.IMREAD_COLOR)
    if bgr is None:
        return [], [], "raw_unreadable"
    res = normalize_device(bgr, config=config)
    if res.image is None:
        return [], [], f"normalize_failed:{res.debug.get('error')}"
    with torch.no_grad():
        t = _to_tensor_normalize(res.image).to(device)
        emb = model(t).cpu().numpy()[0]
    emb = _l2_normalize(emb)
    sims = centroids @ emb  # (n_classes,)
    top_idx = np.argsort(-sims)[:top_k]
    return ([class_ids[i] for i in top_idx],
            [float(sims[i]) for i in top_idx],
            None)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Évalue R@1/R@5 d'un modèle ArcFace sur cohort captures.")
    parser.add_argument("--device-pull", type=Path, required=True,
                         help="Dossier issu de `pull-debug` (contient eval_real/manifest.jsonl).")
    parser.add_argument("--model", type=Path, required=True,
                         help="Checkpoint .pth (CoinEmbedder).")
    parser.add_argument("--embeddings", type=Path, required=True,
                         help="embeddings_v1.json produit par compute_embeddings.")
    parser.add_argument("--crop-config-json", type=Path, required=True,
                         help="_crop_config.json du dataset sur lequel le modèle "
                              "a été entraîné. Critical : eval doit normaliser avec "
                              "le MÊME CropConfig sinon train/infer drift.")
    parser.add_argument("--output", type=Path, required=True,
                         help="CSV de sortie par capture.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0,
                         help="Limite n captures (0 = tout). Debug.")
    args = parser.parse_args()

    config = load_crop_config(args.crop_config_json)
    print(f"Eval config: {config}")
    print(f"  slug: m{int(config.margin_frac*100):02d}-{config.edge_mode}-s{config.output_size}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    print(f"Loading model {args.model}…")
    model, embedding_dim = load_model(args.model, device)
    print(f"  embedding_dim={embedding_dim}")

    print(f"Loading embeddings {args.embeddings}…")
    class_ids, centroids, eurio_to_class = load_embeddings(args.embeddings)
    print(f"  {len(class_ids)} classes, {centroids.shape[1]}-dim centroids")
    if centroids.shape[1] != embedding_dim:
        raise SystemExit(
            f"embedding_dim mismatch: model={embedding_dim} vs centroids={centroids.shape[1]}"
        )

    print(f"Discovering captures under {args.device_pull}…")
    entries, eval_dir = discover_captures(args.device_pull)
    print(f"  {len(entries)} manifest entries from {eval_dir}")
    if args.limit > 0:
        entries = entries[: args.limit]
        print(f"  --limit {args.limit} → eval {len(entries)} entries")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    correct_at_1 = 0
    correct_at_5 = 0
    eval_count = 0
    errors_by_kind: dict[str, int] = defaultdict(int)
    per_step_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "ok1": 0, "ok5": 0})

    for i, e in enumerate(entries, 1):
        raw_path = Path(e.get("raw_path", ""))
        true_eurio = e.get("eurio_id")
        step = e.get("step_id", "?")
        photo_idx = e.get("photo_index", 0) or 0
        if not raw_path.is_file():
            errors_by_kind["raw_missing"] += 1
            print(f"  [{i}/{len(entries)}] ⨯ raw missing: {raw_path}")
            continue
        top_cls, top_sims, err = _eval_one(
            raw_path, model, config, device, centroids, class_ids, top_k=args.top_k,
        )
        if err:
            errors_by_kind[err] += 1
            print(f"  [{i}/{len(entries)}] ⨯ {err}")
            continue

        # Vérité terrain : true_eurio peut mapper à un class_id (mode design_group)
        # ou être lui-même un class_id (mode eurio_id).
        true_class_candidates = eurio_to_class.get(true_eurio, [true_eurio])
        ok1 = top_cls[0] in true_class_candidates
        ok5 = any(c in true_class_candidates for c in top_cls[: args.top_k])
        eval_count += 1
        correct_at_1 += int(ok1)
        correct_at_5 += int(ok5)
        per_step_stats[step]["n"] += 1
        per_step_stats[step]["ok1"] += int(ok1)
        per_step_stats[step]["ok5"] += int(ok5)

        rows.append({
            "eurio_id_true": true_eurio,
            "step_id": step,
            "photo_index": photo_idx,
            "raw_path": str(raw_path.relative_to(args.device_pull)
                            if raw_path.is_relative_to(args.device_pull) else raw_path),
            "predicted_top1": top_cls[0],
            "similarity_top1": round(top_sims[0], 4),
            "is_correct": int(ok1),
            "is_correct_at_5": int(ok5),
            "top5": "|".join(f"{c}:{s:.3f}" for c, s in zip(top_cls, top_sims)),
        })

    # CSV
    if rows:
        with args.output.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"\n→ {args.output} ({len(rows)} rows)")

    # Summary
    print("\n=== R@K summary ===")
    if eval_count == 0:
        print("  (aucune capture évaluée — voir errors_by_kind)")
    else:
        r1 = 100 * correct_at_1 / eval_count
        r5 = 100 * correct_at_5 / eval_count
        print(f"  R@1 = {correct_at_1}/{eval_count} = {r1:.2f} %")
        print(f"  R@5 = {correct_at_5}/{eval_count} = {r5:.2f} %")
    if errors_by_kind:
        print("\nErreurs :")
        for k, v in sorted(errors_by_kind.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
    print("\nPar condition (step) :")
    for step, s in sorted(per_step_stats.items()):
        r1 = 100 * s["ok1"] / s["n"] if s["n"] else 0
        r5 = 100 * s["ok5"] / s["n"] if s["n"] else 0
        print(f"  {step:<20} n={s['n']:>3}  R@1={r1:5.1f}%  R@5={r5:5.1f}%")

    # Aussi : écrit un sidecar JSON avec le résumé pour le sweep wrapper
    summary = {
        "crop_config": asdict(config),
        "n_eval": eval_count,
        "r_at_1": correct_at_1 / eval_count if eval_count else None,
        "r_at_5": correct_at_5 / eval_count if eval_count else None,
        "errors": dict(errors_by_kind),
        "per_step": {k: dict(v) for k, v in per_step_stats.items()},
        "model": str(args.model),
        "device_pull": str(args.device_pull),
    }
    sidecar = args.output.with_suffix(".summary.json")
    sidecar.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nSummary sidecar: {sidecar}")


if __name__ == "__main__":
    main()
