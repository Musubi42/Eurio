"""Bench C7 (face) — séparation avers national vs revers commun via DINO.

Question fondatrice : les embeddings DINOv2 séparent-ils le côté AVERS
(national, ce qu'on matche) du côté REVERS commun (la carte + « 2 EURO »,
identique à tous les pays) ? Si oui, un détecteur de face léger est possible
sans réentraînement — soit par ancres (top-1 sur une banque avers+revers),
soit par un score `reverse-ness` (sim max aux 2 designs de revers commun).

Le revers commun 2€ a EXACTEMENT 2 designs : v1 (≤2006) et v2 (≥2007),
packagés dans l'APK (`app-android/.../shared_reverse/reverse_2eur_v*.webp`).
On s'en sert comme ancres revers.

Données (DB canonique) :
  - POSITIFS avers : crops `image_assets.face='obverse'` (566, contrôle — ne
    doivent PAS être classés revers) ;
  - REVERS « canonique » : revers numista d'autres pièces 2€ (téléchargés),
    régime propre — borne SUPÉRIEURE de rappel ;
  - (le revers WILD eBay labellisé manque encore — voir §gold à miner).

Métriques : pour chaque query, `rev_sim` = max cos aux 2 ancres revers,
`obv_sim` = top-1 cos à la banque avers `2eur_all`. Score de face =
`rev_sim - obv_sim`. On sort la séparation (AUC-like via balayage de seuil),
le FP sur les avers et le TP sur les revers canoniques.

Usage :
  python -m scripts.bench_face_detection [--n-reverse 60] [--limit-obverse 400]
"""

from __future__ import annotations

import argparse
import io
import sqlite3
import sys
import urllib.request
from pathlib import Path

import numpy as np
import torch
from PIL import Image

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from shared.storage.local_cache import local_path  # noqa: E402
from training.foundation.anchors import load_anchors  # noqa: E402
from training.foundation.encoder import build_transform, load_encoder  # noqa: E402
from store import resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")
REPO_ROOT = ML_DIR.parent
REVERSE_ASSETS = [
    REPO_ROOT / "app-android" / "src" / "main" / "assets" / "shared_reverse" / "reverse_2eur_v1.webp",
    REPO_ROOT / "app-android" / "src" / "main" / "assets" / "shared_reverse" / "reverse_2eur_v2.webp",
]
REV_CACHE = ML_DIR / "state" / "face_bench" / "reverse_canonical"


@torch.no_grad()
def _encode(images: list[Image.Image], model, device, tf) -> np.ndarray:
    vecs = []
    for i in range(0, len(images), 16):
        batch = torch.stack([tf(im) for im in images[i:i + 16]]).to(device)
        feat = torch.nn.functional.normalize(model(batch), dim=1)
        vecs.append(feat.cpu().numpy())
    return np.concatenate(vecs).astype(np.float32)


def _load(p: Path) -> Image.Image | None:
    try:
        return Image.open(p).convert("RGB")
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-obverse", type=int, default=600)
    ap.add_argument("--pool", type=int, default=1500, help="taille pool non-labellisé à scorer")
    ap.add_argument("--mine", type=int, default=40, help="top candidats revers à sauver pour vérif")
    ap.add_argument("--bank", default="2eur_all")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    model, device = load_encoder(encoder_version="dinov2-vitl14")
    tf = build_transform()

    bank = load_anchors(args.bank)
    if bank is None:
        sys.exit(f"banque {args.bank} absente — go-task ml:dino-anchors:build")
    print(f"banque avers : {bank.count} ancres ({bank.encoder_version})")

    # ── ancres revers (2 designs communs packagés) ──────────────────────
    rev_imgs = [im for p in REVERSE_ASSETS if (im := _load(p))]
    if len(rev_imgs) < 2:
        sys.exit(f"ancres revers manquantes : {REVERSE_ASSETS}")
    rev_anchors = _encode(rev_imgs, model, device, tf)  # (2, D)
    print(f"ancres revers : {len(rev_imgs)} (designs communs v1/v2)")

    def face_scores(vecs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rev = (vecs @ rev_anchors.T).max(axis=1)          # reverse-ness
        obv = (vecs @ bank.matrix.T).max(axis=1)          # obverse-ness (top-1)
        return rev, obv

    # ── queries AVERS (contrôle négatif) ────────────────────────────────
    obv_rows = con.execute(
        "SELECT storage_path FROM image_assets WHERE face='obverse' "
        "AND storage_status='present' AND storage_path IS NOT NULL LIMIT ?",
        (args.limit_obverse,),
    ).fetchall()
    obv_imgs, n_miss = [], 0
    for r in obv_rows:
        try:
            im = _load(local_path("enrichment-crops", r["storage_path"]))
            if im is not None:
                obv_imgs.append(im)
            else:
                n_miss += 1
        except Exception:
            n_miss += 1
    print(f"queries avers : {len(obv_imgs)} ({n_miss} manquants)")

    # ── pool NON-LABELLISÉ pour mining de revers wild ────────────────────
    pool_rows = con.execute(
        "SELECT id, storage_path FROM image_assets WHERE face IS NULL "
        "AND storage_status='present' AND storage_path IS NOT NULL LIMIT ?",
        (args.pool,),
    ).fetchall()
    pool_imgs, pool_keys = [], []
    for r in pool_rows:
        try:
            im = _load(local_path("enrichment-crops", r["storage_path"]))
            if im is not None:
                pool_imgs.append(im)
                pool_keys.append((r["id"], r["storage_path"]))
        except Exception:
            pass
    print(f"pool non-labellisé : {len(pool_imgs)}")

    # ── scores ──────────────────────────────────────────────────────────
    obv_vecs = _encode(obv_imgs, model, device, tf)
    obv_rev, obv_obv = face_scores(obv_vecs)
    obv_margin = obv_rev - obv_obv   # <0 attendu (avers matche mieux l'avers)

    def pct(a):
        a = np.asarray(a)
        return f"[{a.min():.3f}, p50={np.median(a):.3f}, p90={np.percentile(a,90):.3f}, {a.max():.3f}]"

    print("\n" + "=" * 64)
    print("FACE — distribution sur AVERS confirmés (contrôle négatif)")
    print("=" * 64)
    print(f"  reverse-ness {pct(obv_rev)}")
    print(f"  obverse-ness {pct(obv_obv)}")
    print(f"  marge rev-obv {pct(obv_margin)}   (doit être <0 : avers matche l'avers)")
    print(f"  avers avec marge≥0 (faux positifs bruts) : "
          f"{float((obv_margin>=0).mean()):.1%}")
    for t in (-0.05, 0.0, 0.05, 0.10):
        print(f"    FP_avers @ marge≥{t:+.2f} : {float((obv_margin>=t).mean()):.1%}")

    # ── mining par BANDES de marge → planche par bande pour vérif ────────
    if pool_imgs:
        import math
        pool_vecs = _encode(pool_imgs, model, device, tf)
        p_rev, p_obv = face_scores(pool_vecs)
        p_margin = p_rev - p_obv
        bands = [(-1.0, -0.05), (-0.05, 0.0), (0.0, 0.05), (0.05, 0.10), (0.10, 1.0)]
        out = ML_DIR / "state" / "face_bench"
        for f in out.glob("band_*.png"):
            f.unlink()
        # JSONL des candidats scorés (pour figer un gold élargi après vérif)
        import json
        cand = []
        print("\n" + "=" * 64)
        print("MINING PAR BANDE DE MARGE (pool non-labellisé)")
        print("=" * 64)
        for lo, hi in bands:
            idxs = [i for i in range(len(p_margin)) if lo <= p_margin[i] < hi]
            idxs.sort(key=lambda i: -p_margin[i])
            print(f"  marge [{lo:+.2f},{hi:+.2f}) : {len(idxs)} crops")
            for i in idxs:
                aid, sp = pool_keys[i]
                cand.append({"asset_id": aid, "storage_path": sp,
                             "margin": round(float(p_margin[i]), 4)})
            # planche-contact (max 48 par bande)
            sample = idxs[:48]
            if sample:
                cols, cell = 8, 130
                rows = math.ceil(len(sample) / cols)
                sheet = Image.new("RGB", (cols * cell, rows * cell), (25, 25, 25))
                from PIL import ImageDraw
                dr = ImageDraw.Draw(sheet)
                for k, i in enumerate(sample):
                    aid, sp = pool_keys[i]
                    try:
                        im = Image.open(local_path("enrichment-crops", sp)).convert("RGB").resize((cell - 8, cell - 20))
                        x, y = (k % cols) * cell, (k // cols) * cell
                        sheet.paste(im, (x + 4, y + 4))
                        dr.text((x + 4, y + cell - 15), f"{p_margin[i]:+.3f}", fill=(255, 230, 0))
                    except Exception:
                        pass
                tag = f"band_{lo:+.2f}_{hi:+.2f}".replace(".", "")
                sheet.save(out / f"{tag}.png")
        (out / "mined_candidates.jsonl").write_text(
            "\n".join(json.dumps(c) for c in cand) + "\n")
        print(f"\n  total scoré : {len(p_margin)} | marge≥0 : "
              f"{int((p_margin>=0).sum())} ({float((p_margin>=0).mean()):.1%})")
        print(f"  planches → {out}/band_*.png ; candidats → mined_candidates.jsonl")
    print("\n⚠️ rappel wild : valider les bandes frontière (−0,05..+0,05) pour fixer τ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
