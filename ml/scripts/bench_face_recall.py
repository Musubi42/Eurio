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
        python -m scripts.bench_face_recall --taus -0.05:0.12:0.005

⚠️ **Ce banc DÉRIVE tout seul, et c'est structurel.** La marge est
``max cosinus sur les ancres de REVERS − max cosinus sur la banque des AVERS``
(`sources/_base/steps/auto_validate.py:828`) : 34 vecteurs d'un côté, 2 062 de
l'autre au 2026-08-24. Un max sur plus de vecteurs est plus haut par
construction, donc **chaque agrandissement de la banque des avers rabote la
marge et rend le détecteur plus aveugle aux revers, à τ constant.**

Mesuré le 2026-08-27 en rejouant ce banc sans rien changer d'autre — banque
enrichie, τ prod = 0,065, contre les chiffres de calibration du 2026-06-13 :

| segment            | 2026-06-13 | 2026-08-27 |
|--------------------|-----------:|-----------:|
| avers (contrôle FP)|       0 %  |      0 %   |
| revers faciles     |     100 %  |   80,0 %   |
| revers durs        |    73,3 %  |   40,0 %   |

Pendant ce temps la banque des avers est passée d'environ 1 250 à 2 062 ancres
(+65 %). **Rejoue ce banc après CHAQUE rebuild de la banque des avers**, pas
seulement après un enrichissement du fichier wild.
"""

from __future__ import annotations

import argparse
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


def _parse_taus(spec: str) -> tuple[float, ...]:
    """``"-0.05:0.12:0.005"`` (début:fin:pas) ou ``"0,0.065,0.10"``."""
    if ":" in spec:
        lo, hi, step = (float(x) for x in spec.split(":"))
        if step <= 0:
            raise ValueError("le pas doit être > 0")
        n = int(round((hi - lo) / step))
        return tuple(round(lo + i * step, 6) for i in range(n + 1))
    return tuple(float(x) for x in spec.split(","))


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--taus", default=None,
        help="seuils à balayer : 'début:fin:pas' ou liste séparée par des "
             "virgules (défaut : 0, τ prod, 0.10)",
    )
    args = ap.parse_args(argv)
    taus = _parse_taus(args.taus) if args.taus else TAUS

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

    print(f"\nbanque des AVERS : {obv_bank.count} ancres "
          f"({obv_bank.encoder_version}) — c'est elle qui rabote la marge")

    obv_m = obv_bank.matrix.T
    for bank_name, rev_anchors in banks.items():
        print(f"\n{'=' * 64}\nBANQUE {bank_name}\n{'=' * 64}")
        # Quantiles de marge : c'est ce qui permet de CHOISIR τ, là où un
        # taux à trois seuils ne fait que le constater. Pour le segment de
        # contrôle, le maximum est le chiffre décisif — tout τ au-dessus rend
        # FP = 0 sur ce gold.
        print(f"  {'segment':<28} {'p05':>8}{'médiane':>10}{'p95':>8}{'max':>8}")
        margins: dict[str, np.ndarray] = {}
        for seg in sorted(by_seg):
            m = (seg_vecs[seg] @ rev_anchors.T).max(axis=1) - (
                seg_vecs[seg] @ obv_m).max(axis=1)
            margins[seg] = m
            print(f"  {seg:<28} {np.percentile(m, 5):+8.4f}"
                  f"{np.median(m):+10.4f}{np.percentile(m, 95):+8.4f}{m.max():+8.4f}")
        print()

        for seg in sorted(by_seg):
            margin = margins[seg]
            is_obv = seg.startswith("obverse")
            for t in taus:
                hit = float((margin >= t).mean())
                label = "FP" if is_obv else "rappel"
                star = "  ← τ prod" if abs(t - FACE_REVERSE_TAU) < 1e-9 else ""
                print(f"  {seg:<28} {label}@τ={t:+.3f} : {hit:6.1%}{star}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
