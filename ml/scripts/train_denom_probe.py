"""Probe DINO « 2€ vs junk » — baseline benchmark-first (C7 pilier 2).

Une *seule* probe logistique sur embeddings vitl14 gelés pour rejeter, per-crop,
tout ce qui n'est pas un 2€ unique : autres dénominations (cents, 1€), médailles/
jetons, mires de couleur, sets multi-pièces. Subsume coin-ness + dénomination pour
le problème de pollution de lot (cf. C7 §H10, gold `denom_gold.jsonl`).

Gold petit (≈111 crops) → éval honnête par **cross-val 5-fold stratifiée**
(`cross_val_predict` → scores held-out), AUC + precision/recall, et **rappel par
kind de négatif** (médaille/mire/cent…). Compare 3 jeux de features :
  - bimetal  : `bimetal_score` seul (baseline géométrique, AUC≈0,77) ;
  - dino     : embedding vitl14 (1024-d) seul ;
  - dino+bm  : embedding + bimetal_score en feature auxiliaire.

Usage : python -m scripts.train_denom_probe [--save]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import roc_auc_score, precision_recall_curve

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from shared.storage.local_cache import local_path  # noqa: E402
from training.foundation.encoder import build_transform, load_encoder  # noqa: E402
from vision.denom_geometry import bimetal_score  # noqa: E402
import cv2  # noqa: E402

GOLD = ML_DIR / "state" / "denom_bench" / "denom_gold.jsonl"
EMB_CACHE = ML_DIR / "state" / "denom_bench" / "gold_vitl14.npz"
PROBE_OUT = ML_DIR / "state" / "denom_probe.npz"


@torch.no_grad()
def _embed(paths: list[Path], model, device, tf) -> np.ndarray:
    vecs = []
    for i in range(0, len(paths), 16):
        ims = [Image.open(p).convert("RGB") for p in paths[i:i + 16]]
        batch = torch.stack([tf(im) for im in ims]).to(device)
        feat = torch.nn.functional.normalize(model(batch), dim=1)
        vecs.append(feat.cpu().numpy())
    return np.concatenate(vecs).astype(np.float32)


def _report(name: str, y: np.ndarray, score: np.ndarray, kinds: list) -> None:
    auc = roc_auc_score(y, score)
    prec, rec, thr = precision_recall_curve(y, score)
    # opérateur : meilleure precision à rappel 2€ ≥ 0.95 (R0 : ne pas droper les 2€)
    ok = rec[:-1] >= 0.95
    if ok.any():
        j = np.where(ok)[0][np.argmax(prec[:-1][ok])]
        t = thr[j]
        pred_pos = score >= t
        junk = y == 0
        caught = (junk & ~pred_pos).sum() / max(1, junk.sum())
        line = (f"  @rappel2€≥95% : seuil={t:.2f} precision={prec[j]:.1%} "
                f"junk_capté={caught:.1%}")
    else:
        line = "  (pas d'opérateur à rappel≥95%)"
    print(f"\n[{name}] AUC={auc:.3f}")
    print(line)
    # rappel par kind de négatif à cet opérateur
    if ok.any():
        from collections import defaultdict
        tot, hit = defaultdict(int), defaultdict(int)
        for i, k in enumerate(kinds):
            if y[i] == 0:
                kk = k or "?"
                tot[kk] += 1
                hit[kk] += int(not pred_pos[i])
        print("  junk capté / kind :", {k: f"{hit[k]}/{tot[k]}" for k in sorted(tot)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    rows = [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["label"] in ("pos", "neg")]  # drop unk
    y = np.array([1 if r["label"] == "pos" else 0 for r in rows])
    kinds = [r.get("kind") for r in rows]
    paths = [local_path("enrichment-crops", r["sp"]) for r in rows]
    print(f"gold : {int(y.sum())} pos / {int((y==0).sum())} neg")

    # bimetal feature (toujours recalculé, cheap)
    bm = np.array([(bimetal_score(cv2.imread(str(p))) or {}).get("score", 0.0)
                   for p in paths], dtype=np.float32)

    # embeddings vitl14 (cache)
    if EMB_CACHE.exists():
        emb = np.load(EMB_CACHE)["emb"]
        if len(emb) != len(rows):
            emb = None
    else:
        emb = None
    if emb is None:
        model, device = load_encoder(encoder_version="dinov2-vitl14")
        emb = _embed(paths, model, device, build_transform())
        np.savez_compressed(EMB_CACHE, emb=emb)
    print(f"embeddings : {emb.shape}")

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    clf = LogisticRegression(max_iter=2000, C=0.5, class_weight="balanced")

    # 1) bimetal seul (référence)
    _report("bimetal", y, bm, kinds)

    # 2) dino seul
    s_dino = cross_val_predict(clf, emb, y, cv=cv, method="predict_proba")[:, 1]
    _report("dino", y, s_dino, kinds)

    # 3) dino + bimetal
    X = np.concatenate([emb, (bm[:, None] - bm.mean()) / (bm.std() + 1e-6)], axis=1)
    s_both = cross_val_predict(clf, X, y, cv=cv, method="predict_proba")[:, 1]
    _report("dino+bm", y, s_both, kinds)

    if args.save:
        full = clf.fit(X, y)
        np.savez(PROBE_OUT, coef=full.coef_, intercept=full.intercept_,
                 bm_mean=bm.mean(), bm_std=bm.std(), encoder="dinov2-vitl14")
        print(f"\nprobe (dino+bm) → {PROBE_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
