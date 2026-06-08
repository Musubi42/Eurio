"""train_fragment_probe.py — probe « face entière vs fragment » sur features DINO.

Piste 3 (census-detector-design.md). Entraîne une régression logistique 1 couche
sur les embeddings DINO des crops census (label binaire : face_whole=1, sinon=0),
TRAIN sur des classes diverses, TEST held-out sur at-2002 (jamais en train).

Mesure go/no-go : séparabilité (AP, precision/recall), et impact end-to-end sur
at-2002 = taux de fragments AVANT/APRÈS le gate (faces gardées vs fragments coupés)
en fonction du seuil τ. Bench-first, ne touche rien en prod.

Entrées (state/fragment_probe/) : manifest_{train,test}.jsonl + labels_{train,test}.jsonl
({crop_id, label} avec label ∈ {face_whole, fragment, capsule, clutter}).

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/train_fragment_probe.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parents[1]
OUT = ML_DIR / "state" / "fragment_probe"
POS_LABEL = "face_whole"


def _load_split(split: str):
    man = {json.loads(l)["crop_id"]: json.loads(l)
           for l in (OUT / f"manifest_{split}.jsonl").read_text().splitlines() if l.strip()}
    labels = {}
    lp = OUT / f"labels_{split}.jsonl"
    for l in lp.read_text().splitlines():
        if not l.strip():
            continue
        d = json.loads(l)
        labels[d["crop_id"]] = d["label"]
    ids = [cid for cid in man if cid in labels]
    crop_dir = OUT / "crops" / split
    paths = [crop_dir / f"{cid}.png" for cid in ids]
    y = np.array([1 if labels[cid] == POS_LABEL else 0 for cid in ids])
    return ids, paths, y, labels


def _features(paths):
    from training.foundation.encoder import encode_paths
    kept, mat = encode_paths(paths)
    kept_stems = [p.stem for p in kept]
    return kept_stems, mat


def main() -> int:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score

    tr_ids, tr_paths, tr_y, tr_lab = _load_split("train")
    te_ids, te_paths, te_y, te_lab = _load_split("test")
    print(f"TRAIN {len(tr_ids)} crops ({tr_y.sum()} face / {len(tr_y)-tr_y.sum()} non-face)")
    print(f"TEST  {len(te_ids)} crops ({te_y.sum()} face / {len(te_y)-te_y.sum()} non-face)\n")

    tr_stems, tr_X = _features(tr_paths)
    te_stems, te_X = _features(te_paths)
    # réaligner y sur les stems effectivement encodés
    tr_map = {cid: tr_y[i] for i, cid in enumerate(tr_ids)}
    te_map = {cid: te_y[i] for i, cid in enumerate(te_ids)}
    tr_y = np.array([tr_map[s] for s in tr_stems])
    te_y = np.array([te_map[s] for s in te_stems])

    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(tr_X, tr_y)
    te_score = clf.predict_proba(te_X)[:, 1]

    ap = average_precision_score(te_y, te_score)
    print(f"TEST average precision (face=positif) : {ap:.3f}")
    print(f"  (baseline = part de faces = {te_y.mean():.3f})\n")

    n_face = int(te_y.sum())
    n_frag = int((te_y == 0).sum())
    print(f"{'τ':>5}{'faces gardées':>16}{'frag. coupés':>16}{'frag. restants':>16}{'taux frag après':>18}")
    for tau in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        keep = te_score >= tau
        faces_kept = int(((te_y == 1) & keep).sum())
        frag_cut = int(((te_y == 0) & ~keep).sum())
        frag_left = int(((te_y == 0) & keep).sum())
        total_kept = int(keep.sum())
        rate_after = frag_left / total_kept if total_kept else 0.0
        print(f"{tau:>5.1f}{faces_kept:>7}/{n_face:<8}{frag_cut:>7}/{n_frag:<8}"
              f"{frag_left:>12}{rate_after:>18.1%}")

    print(f"\nTaux de fragments AVANT gate (test) : {n_frag/len(te_y):.1%} "
          f"({n_frag}/{len(te_y)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
