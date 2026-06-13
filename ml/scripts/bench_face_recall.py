"""Bench C7 pilier 1 (rappel) — replay du détecteur de face sur le gold.

Mesure l'effet des **ancres revers wild** (`state/face_bench/reverse_wild_anchors.jsonl`)
sur le détecteur `face=reverse si reverse-ness − obverse-ness ≥ τ` :
compare la banque **canonique** (2 webp APK) à la banque **enrichie**
(canonique + wild), sur les segments du gold `face_gold.jsonl` :

- ``obverse`` (566, admin_confirmed) — contrôle : **FP doit rester ~0** à τ prod ;
- ``reverse`` faciles (mined_verified_top40) — déjà détectés par la banque
  canonique, le rappel doit rester haut ;
- ``reverse`` durs (denom-rescue-*) — les revers RATÉS par la banque canonique
  (rescued du gate denom, tour de boucle 1) : c'est la frontière de rappel.

Les asset_id des ancres wild sont exclus de l'éval (et par construction la
curation les prend HORS gold). Rejouable après chaque enrichissement du fichier
wild ou du gold.

Usage : python -m scripts.bench_face_recall
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from PIL import Image

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from shared.storage.local_cache import local_path  # noqa: E402
from sources._base.steps.auto_validate import FACE_REVERSE_TAU  # noqa: E402
from training.foundation.anchors import (  # noqa: E402
    _REVERSE_ANCHOR_SOURCES,
    _REVERSE_WILD_FILE,
    SUGGESTIONS_ANCHORS_KIND,
    load_anchors,
)
from training.foundation.encoder import build_transform, load_encoder  # noqa: E402

GOLD = ML_DIR / "state" / "face_bench" / "face_gold.jsonl"
TAUS = (0.0, FACE_REVERSE_TAU, 0.10)


@torch.no_grad()
def _encode(images: list[Image.Image], model, device, tf) -> np.ndarray:
    vecs = []
    for i in range(0, len(images), 16):
        batch = torch.stack([tf(im) for im in images[i:i + 16]]).to(device)
        feat = torch.nn.functional.normalize(model(batch), dim=1)
        vecs.append(feat.cpu().numpy())
    return np.concatenate(vecs).astype(np.float32)


def _segment(row: dict) -> str:
    if row["face"] == "obverse":
        return "obverse (contrôle FP)"
    if row["source"].startswith("denom-rescue"):
        return "reverse DUR (denom-rescue)"
    return "reverse facile (mined_top40)"


def main() -> int:
    model, device = load_encoder(encoder_version="dinov2-vitl14")
    tf = build_transform()

    obv_bank = load_anchors(SUGGESTIONS_ANCHORS_KIND)
    if obv_bank is None or obv_bank.encoder_version != "dinov2-vitl14":
        sys.exit("banque 2eur_all vitl14 absente — go-task ml:dino-anchors:build")

    canon_imgs = [Image.open(p).convert("RGB")
                  for _, p in _REVERSE_ANCHOR_SOURCES if p.is_file()]
    if len(canon_imgs) < 2:
        sys.exit("webp revers canoniques manquants")
    wild_rows = []
    if _REVERSE_WILD_FILE.is_file():
        wild_rows = [json.loads(l) for l in _REVERSE_WILD_FILE.read_text().splitlines()
                     if l.strip()]
    wild_imgs, wild_ids = [], set()
    for r in wild_rows:
        p = Path(local_path("enrichment-crops", r["storage_path"]))
        if p.is_file():
            wild_imgs.append(Image.open(p).convert("RGB"))
            wild_ids.add(r["asset_id"])

    canon = _encode(canon_imgs, model, device, tf)
    banks = {"canonique (2 ancres)": canon}
    if wild_imgs:
        wild = _encode(wild_imgs, model, device, tf)
        banks[f"enrichie (2+{len(wild_imgs)} wild)"] = np.concatenate([canon, wild])

    rows = [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["asset_id"] not in wild_ids]
    by_seg: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_seg[_segment(r)].append(r)

    seg_vecs: dict[str, np.ndarray] = {}
    for seg, seg_rows in by_seg.items():
        imgs, kept = [], []
        for r in seg_rows:
            try:
                p = Path(local_path("enrichment-crops", r["storage_path"]))
                imgs.append(Image.open(p).convert("RGB"))
                kept.append(r)
            except Exception:
                pass
        by_seg[seg] = kept
        seg_vecs[seg] = _encode(imgs, model, device, tf)
        print(f"{seg} : {len(kept)} queries")

    obv_m = obv_bank.matrix.T
    for bank_name, rev_anchors in banks.items():
        print(f"\n{'=' * 64}\nBANQUE {bank_name}\n{'=' * 64}")
        for seg in sorted(by_seg):
            vecs = seg_vecs[seg]
            margin = (vecs @ rev_anchors.T).max(axis=1) - (vecs @ obv_m).max(axis=1)
            is_obv = seg.startswith("obverse")
            for t in TAUS:
                hit = float((margin >= t).mean())
                label = "FP" if is_obv else "rappel"
                star = "  ← τ prod" if abs(t - FACE_REVERSE_TAU) < 1e-9 else ""
                print(f"  {seg:<28} {label}@τ={t:+.2f} : {hit:6.1%}{star}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
