"""Compute reference (centroid) embeddings for each coin class.

Output:
  - embeddings_v1.json — rich per-class info (class_kind, member eurio_ids,
    embedding). Consumed by seed_supabase and other ML tooling.
  - coin_embeddings.json — flat numista_id → embedding map. Preserved for
    the Android reader (EmbeddingMatcher). For a design_group class the
    same centroid is emitted once per member numista_id.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

from training.eval.class_resolver import MANIFEST_FILENAME, read_manifest
from training.train_embedder import build_embedder, get_device, get_val_transforms

CATALOG_PATH = Path(__file__).parent.parent / "datasets" / "coin_catalog.json"


def describe_auto_source(dataset_root: Path, *, explicit: bool = False) -> str:
    """Message WARNING nommant la source que `--centroid-source auto` retiendra.

    `auto` bascule val_mean → arcface_w selon que `val/` est peuplé ou non, et
    cette bascule silencieuse est exactement le motif « valeur par défaut
    plausible » du catalogue `eurio-verify`. Le défaut est conservé pour les
    appels manuels ; il n'est plus muet.

    ⚠️ `explicit` dit si la valeur `auto` a été **passée** sur la ligne de
    commande ou **héritée** de l'absence de drapeau. Le message ne les
    distinguait pas jusqu'au 2026-08-25 : il annonçait « --centroid-source
    absent » alors que `training/pipeline.py` le passe explicitement depuis
    le lot 2, et
    accusait donc une cause fausse (LOT4-RESULTATS.md §6).
    """
    val_dir = Path(dataset_root) / "val"
    n_val = (
        sum(1 for f in val_dir.rglob("*") if f.is_file()) if val_dir.exists() else 0
    )
    effective = "val_mean (+ arcface_w en repli)" if n_val else "arcface_w"
    provenance = (
        "--centroid-source auto passé explicitement"
        if explicit
        else "--centroid-source absent → défaut 'auto'"
    )
    return (
        f"WARNING: {provenance}. "
        f"Source réellement retenue : {effective} "
        f"(val/ contient {n_val} fichier(s) sous {val_dir}). "
        "Un appelant automatisé DOIT passer une valeur explicite AUTRE que "
        "'auto' (cf. docs/work-in-progress/juge-et-banc/PROBLEME.md §1bis)."
    )


def load_display_names() -> dict[str, str]:
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH) as f:
            catalog = json.load(f)["coins"]
        return {k: v.get("name", k) for k, v in catalog.items()}
    return {}


@torch.no_grad()
def compute(args: argparse.Namespace) -> None:
    device = get_device(getattr(args, "device", "auto"))

    # Load weights on CPU (map_location) then move the model to the compute
    # device. Forward runs on CUDA/MPS when available; outputs are pulled back
    # to CPU before .numpy() so the centroid math (and its 6-decimal rounding)
    # stays byte-identical to the historical CPU path within float tolerance.
    checkpoint = torch.load(args.model, map_location="cpu", weights_only=False)
    embedding_dim = checkpoint["embedding_dim"]
    backbone = checkpoint.get("backbone", "mobilenet_v3_small")
    model = build_embedder(backbone, embedding_dim)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    model.to(device)

    print(f"Model from epoch {checkpoint['epoch']}, dim={embedding_dim} | device={device}")

    dataset_root = Path(args.dataset)
    manifest = read_manifest(dataset_root / MANIFEST_FILENAME)
    manifest_by_class = {d.class_id: d for d in manifest}
    if not manifest_by_class:
        print(
            f"WARNING: no class manifest at {dataset_root / MANIFEST_FILENAME}; "
            "class_kind will default to eurio_id."
        )

    # Stratégie de centroïde par classe — trois sources possibles :
    #
    #   (a) train_mean — moyenne des embeddings du split train. **C'est la
    #       source à préférer**, et c'est celle que `training/pipeline.py`
    #       passe explicitement.
    #   (b) arcface_w — prototype ArcFace W.
    #   (c) val_mean — moyenne des embeddings du split val.
    #
    # ⚠️ Le commentaire qui vivait ici jusqu'au 2026-08-25 argumentait
    # l'inverse : il recommandait (c) en s'appuyant sur un diagnostic
    # « R@1 = 95,83 % par KNN sur val contre 50 % déployé via W ». Ce chiffre
    # porte sur **24 images / 4 classes, avril 2026, zéro crop eBay en base** —
    # il n'a jamais été reproduit à l'échelle, et il a été **réfuté deux fois** :
    #
    #   • docs/model-efficiency/C1-reliable-centroids.md — 2026-06-11, n = 317
    #     photos : train_mean 82,97 % > arcface_w 82,65 % > val_mean 77,60 %,
    #     val_mean est le PIRE des trois ; il ne couvrait que 27 classes / 546.
    #   • docs/work-in-progress/scan-quality/exp-02-centroids-arcfacew.md —
    #     2026-07-06, n = 73 frames appariées, test de McNemar :
    #     train_mean 0,7671 (+8,2 pts) > arcface_w 0,7397 > val_mean 0,6849 ;
    #     p = 0,180 — un défaut de PUISSANCE (n = 73), pas un défaut de
    #     train_mean.
    #
    # 🔴 Et surtout : `prepare_dataset` remplit `val/` avec le corpus device
    # `ml/datasets/eval_real_norm/`, qui est **le juge du benchmark**. Prendre
    # val_mean, c'est fabriquer le prototype d'une classe à partir des photos
    # qui la testent — une fuite d'étiquette directe, pas un biais de quelques
    # points. Cf. docs/work-in-progress/juge-et-banc/PROBLEME.md §1bis.
    class_embeddings: dict[str, list[np.ndarray]] = {}
    centroid_sources: dict[str, str] = {}

    # Source du centroïde par classe (cf. C1 — model-efficiency) :
    #   auto       : val-mean où dispo, fallback ArcFace-W (comportement legacy)
    #   val_mean   : moyenne d'images val uniquement
    #   train_mean : moyenne d'images train (couvre toutes les classes)
    #   arcface_w  : prototype ArcFace-W pour toutes les classes
    # `None` = le drapeau n'a pas été fourni (sentinelle d'argparse) ; une
    # Namespace fabriquée à la main n'a pas l'attribut du tout. Les deux cas
    # retombent sur `auto`, mais ils ne se journalisent pas pareil.
    raw_source = getattr(args, "centroid_source", None)
    source = raw_source if raw_source is not None else "auto"
    if source == "auto":
        print(describe_auto_source(dataset_root, explicit=raw_source is not None))

    def _split_means(split: str) -> None:
        split_dir = dataset_root / split
        if not split_dir.exists():
            return
        ds = ImageFolder(str(split_dir), transform=get_val_transforms())
        if len(ds) == 0:
            return
        loader = DataLoader(ds, batch_size=32, shuffle=False, num_workers=0)
        for images, labels in loader:
            emb = model(images.to(device)).cpu().numpy()
            for i, label in enumerate(labels):
                cls_name = ds.classes[label]
                class_embeddings.setdefault(cls_name, []).append(emb[i])
        for cls in ds.classes:
            if cls in class_embeddings:
                centroid_sources[cls] = f"{split}_mean(n={len(class_embeddings[cls])})"

    # (a) Moyennes d'images (val et/ou train selon la source).
    if source in ("auto", "val_mean"):
        _split_means("val")
    if source == "train_mean":
        _split_means("train")

    # (b) ArcFace W : toutes les classes (arcface_w) ou fallback (auto).
    arcface_W = checkpoint.get("arcface_weights")
    if source in ("auto", "arcface_w") and checkpoint.get("mode") == "arcface" and arcface_W is not None:
        ckpt_classes = checkpoint.get("classes") or []
        if not ckpt_classes:
            raise SystemExit(
                "Checkpoint has arcface_weights but no `classes` list — "
                "cannot map prototype index to class_id."
            )
        if isinstance(arcface_W, list):
            arcface_W = torch.tensor(arcface_W)
        W = arcface_W.t() if arcface_W.shape[0] == embedding_dim else arcface_W
        W = torch.nn.functional.normalize(W, p=2, dim=1).numpy()
        for idx, cls_name in enumerate(ckpt_classes):
            if source == "arcface_w" or cls_name not in class_embeddings:
                class_embeddings[cls_name] = [W[idx]]
                centroid_sources[cls_name] = "arcface_W"

    # (c) Legacy: average across all splits when no W available.
    if not class_embeddings:
        for split in ("train", "val", "test"):
            split_dir = dataset_root / split
            if not split_dir.exists():
                continue

            dataset = ImageFolder(str(split_dir), transform=get_val_transforms())
            loader = DataLoader(dataset, batch_size=32, shuffle=False, num_workers=0)

            for images, labels in loader:
                emb = model(images.to(device)).cpu().numpy()
                for i, label in enumerate(labels):
                    cls_name = dataset.classes[label]
                    class_embeddings.setdefault(cls_name, []).append(emb[i])
                    centroid_sources[cls_name] = "all_splits_mean(legacy)"

    if not class_embeddings:
        raise SystemExit(
            f"No source for centroids: val/ empty, no arcface_W in checkpoint, "
            f"no splits under {dataset_root}."
        )

    print("\nCentroid sources:")
    for cls in sorted(class_embeddings.keys()):
        print(f"  {cls:<55} {centroid_sources.get(cls, '?')}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    display_names = load_display_names()
    coins_full: dict[str, dict] = {}
    coins_flat: dict[str, list[float]] = {}

    model_version = args.model_version
    if not model_version:
        ckpt_version = checkpoint.get("model_version")
        if ckpt_version:
            model_version = ckpt_version
        else:
            model_version = f"v1-{checkpoint.get('mode', 'unknown')}"

    for class_id, emb_list in sorted(class_embeddings.items()):
        stacked = np.stack(emb_list)
        centroid = stacked.mean(axis=0)
        centroid = centroid / np.linalg.norm(centroid)
        embedding_list = [round(float(x), 6) for x in centroid]

        descriptor = manifest_by_class.get(class_id)
        class_kind = descriptor.class_kind if descriptor else "eurio_id"
        numista_ids = list(descriptor.numista_ids) if descriptor else []
        eurio_ids = list(descriptor.eurio_ids) if descriptor else []
        display_name = display_names.get(class_id, class_id)

        coins_full[class_id] = {
            "name": display_name,
            "class_kind": class_kind,
            "numista_ids": numista_ids,
            "eurio_ids": eurio_ids,
            "n_samples": len(emb_list),
            "embedding": embedding_list,
        }

        for nid in numista_ids:
            coins_flat[str(nid)] = embedding_list
        if not numista_ids:
            # Fallback: no numista mapping available (manifest missing).
            coins_flat[class_id] = embedding_list

        print(f"  {class_id} [{class_kind}]: {len(emb_list)} imgs → centroid")

    full_output = {
        "version": "1.0",
        "model": model_version,
        "embedding_dim": embedding_dim,
        "coins": coins_full,
    }
    full_path = output_dir / "embeddings_v1.json"
    full_path.write_text(json.dumps(full_output, indent=2))
    print(f"\nFull embeddings: {full_path}")

    flat_path = output_dir / "coin_embeddings.json"
    flat_path.write_text(json.dumps(coins_flat))
    print(f"Flat embeddings: {flat_path} ({flat_path.stat().st_size / 1024:.1f} KB)")


def main():
    parser = argparse.ArgumentParser(description="Compute reference embeddings")
    parser.add_argument("--model", type=str, default="./checkpoints/best_model.pth")
    parser.add_argument("--dataset", type=str, default="./datasets/eurio-poc")
    parser.add_argument("--output-dir", type=str, default="./output")
    parser.add_argument(
        "--model-version",
        type=str,
        default="",
        help="Override model version string (else read from checkpoint or derived).",
    )
    parser.add_argument(
        "--centroid-source",
        choices=["auto", "val_mean", "train_mean", "arcface_w"],
        default=None,  # sentinelle : distingue « absent » de « auto passé »
        help="Source du centroïde par classe. 'train_mean' est la valeur à "
             "utiliser (C1 2026-06-11 n=317 ; exp-02 2026-07-06 n=73). "
             "'val_mean' fuite le juge quand val/ = eval_real_norm. 'auto' est "
             "conservé pour les appels manuels et journalise un WARNING.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="Compute device (auto|cuda|mps|cpu). auto picks cuda→mps→cpu.",
    )
    args = parser.parse_args()
    compute(args)


if __name__ == "__main__":
    main()
