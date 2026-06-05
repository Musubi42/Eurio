"""build_fragment_probe.py — calibre (LOCO-CV) + entraîne + persiste la probe face-vs-fragment.

Piste 3 (census-detector-design.md §9). La probe = régression logistique 1 couche
sur features DINO des crops census normalisés 224 (label binaire face_whole=1).

1. Encode une seule fois tous les crops labellisés (train 8 classes + test at-2002).
2. **Leave-One-Class-Out CV** : pour chaque classe, entraîne sur les autres, évalue
   sur elle → AP + recall faces / coupe fragments par τ. Calibration HONNÊTE
   (aucune fuite inter-classe ; mesure la généralisation à une classe non vue).
3. Entraîne la probe FINALE sur TOUTES les classes → persiste
   `state/fragment_face_probe.npz` (coef, intercept, dim) pour `scan/census.py`.

Features = embeddings DINO L2-normalisés (encode_paths) ; pas de scaler (la
logistique encaisse l'échelle). Le gate s'applique côté `normalize_listing` APRÈS
le crop (la probe a vu les crops 224 finaux, pas les bbox brutes).

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/build_fragment_probe.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parents[1]
OUT = ML_DIR / "state" / "fragment_probe"
PROBE_PATH = ML_DIR / "state" / "fragment_face_probe.npz"
POS_LABEL = "face_whole"
TAUS = [0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7]


def _load(split: str):
    man = {json.loads(l)["crop_id"]: json.loads(l)
           for l in (OUT / f"manifest_{split}.jsonl").read_text().splitlines() if l.strip()}
    labels = {json.loads(l)["crop_id"]: json.loads(l)["label"]
              for l in (OUT / f"labels_{split}.jsonl").read_text().splitlines() if l.strip()}
    rows = []
    crop_dir = OUT / "crops" / split
    for cid, rec in man.items():
        if cid in labels:
            rows.append({"crop_id": cid, "class": rec["class"], "label": labels[cid],
                         "path": crop_dir / f"{cid}.png"})
    return rows


def _operating(y, score, tau):
    keep = score >= tau
    nf = int((y == 1).sum()); nfr = int((y == 0).sum())
    faces_kept = int(((y == 1) & keep).sum())
    frag_cut = int(((y == 0) & ~keep).sum())
    return faces_kept, nf, frag_cut, nfr


def main() -> int:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score
    from foundation.encoder import encode_paths

    rows = _load("train") + _load("test")
    # Split hardneg (probe v2) : hard-negatives minés sur le run census-recover
    # (blanks/packaging/dark que v1 laissait passer). Optionnel — absent = probe v1.
    if (OUT / "manifest_hardneg.jsonl").exists() and (OUT / "labels_hardneg.jsonl").exists():
        hn = _load("hardneg")
        rows += hn
        print(f"+ split hardneg : {len(hn)} crops "
              f"({sum(r['label'] == POS_LABEL for r in hn)} faces)")
    print(f"{len(rows)} crops labellisés, "
          f"{sum(r['label'] == POS_LABEL for r in rows)} faces")

    stems, X = [], None
    paths = [r["path"] for r in rows]
    kept, X = encode_paths(paths)
    kept_stems = {p.stem for p in kept}
    rows = [r for r in rows if r["crop_id"] in kept_stems]
    # réaligner X sur rows (encode_paths garde l'ordre des paths valides)
    order = {p.stem: i for i, p in enumerate(kept)}
    X = X[[order[r["crop_id"]] for r in rows]]
    y = np.array([1 if r["label"] == POS_LABEL else 0 for r in rows])
    cls = np.array([r["class"] for r in rows])
    classes = sorted(set(cls))

    print(f"\nLeave-One-Class-Out CV ({len(classes)} classes) :")
    print(f"{'classe held-out':45s}{'n':>5}{'faces':>7}{'AP':>7}"
          f"{'  recall@.4':>11}{' cut@.4':>9}{' recall@.5':>11}")
    aps = []
    agg = {t: [0, 0, 0, 0] for t in TAUS}  # fk, nf, fc, nfr
    for c in classes:
        te = cls == c
        tr = ~te
        if y[te].sum() == 0 or y[tr].sum() == 0:
            continue
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
        clf.fit(X[tr], y[tr])
        sc = clf.predict_proba(X[te])[:, 1]
        ap = average_precision_score(y[te], sc) if y[te].sum() else float("nan")
        aps.append(ap)
        fk4, nf4, fc4, nfr4 = _operating(y[te], sc, 0.4)
        fk5, nf5, _, _ = _operating(y[te], sc, 0.5)
        for t in TAUS:
            fk, nf, fc, nfr = _operating(y[te], sc, t)
            agg[t][0] += fk; agg[t][1] += nf; agg[t][2] += fc; agg[t][3] += nfr
        print(f"{c[:45]:45s}{te.sum():>5}{int(y[te].sum()):>7}{ap:>7.3f}"
              f"{fk4:>6}/{nf4:<4}{fc4:>5}/{nfr4:<3}{fk5:>7}/{nf5:<4}")

    print(f"\nMoyenne AP (LOCO) : {np.mean(aps):.3f}")
    print(f"\nAgrégat tous-crops par τ :")
    print(f"{'τ':>6}{'faces gardées':>16}{'frag. coupés':>16}{'recall faces':>14}{'cut frag':>10}")
    for t in TAUS:
        fk, nf, fc, nfr = agg[t]
        print(f"{t:>6.2f}{fk:>8}/{nf:<7}{fc:>8}/{nfr:<7}"
              f"{fk/nf:>13.1%}{fc/nfr:>10.1%}")

    # Probe finale sur TOUTES les classes.
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(X, y)
    np.savez(PROBE_PATH,
             coef=clf.coef_.astype(np.float32).ravel(),
             intercept=np.float32(clf.intercept_[0]),
             dim=np.int32(X.shape[1]),
             classes_trained=np.array(classes),
             pos_label=POS_LABEL)
    print(f"\n→ probe finale persistée : {PROBE_PATH} (dim {X.shape[1]}, "
          f"{len(rows)} crops, {int(y.sum())} faces)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
