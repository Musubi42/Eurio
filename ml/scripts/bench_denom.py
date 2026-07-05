"""Bench C7 (dénomination) — gate « est-ce un 2€ ? » via bimétal géométrique.

Question fondatrice : le contraste de couleur radial (anneau ↔ disque) sépare-t-il
les 2€ **bimétal** des non-2€ **monométal** (1/2/5 ct cuivre, 10/20/50 ct nordic
gold) qui polluent les crops de **photos de lots** ? Si oui, gate zéro-training.

Cf. docs/model-efficiency/HANDOFF-C7.md §2 (piste 1, recommandée) et
`ml/vision/denom_geometry.py:bimetal_score`. Aucun seuil de similarité ne sépare
(mesuré 2026-06-12) — d'où ce signal physique.

Données (DB canonique) :
  - POSITIFS 2€ : crops `image_assets.face IN ('obverse','reverse')` (confirmés 2€,
    bimétal attendu → score HAUT) ;
  - POOL LOT (mixte, non labellisé) : crops des listings lot du run 059
    (`route_reason IN multi_coin_photo|is_lot_suspected|listing_kind_lot`,
    `face IS NULL`) — contient les non-2€ à isoler (score BAS attendu).

Sortie : distributions, planches-contact par bande de score (vérif visuelle de la
queue basse = monométal non-2€), JSONL des candidats (graine du gold denom).

Usage :
  python -m scripts.bench_denom [--limit-pos 600] [--pool 1500] [--run 059dc8d]
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from shared.storage.local_cache import local_path  # noqa: E402
from vision.denom_geometry import bimetal_score  # noqa: E402
from store import resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")
OUT_DIR = ML_DIR / "state" / "denom_bench"
LOT_REASONS = ("multi_coin_photo", "is_lot_suspected", "listing_kind_lot")


def _load_bgr(storage_path: str) -> np.ndarray | None:
    try:
        p = local_path("enrichment-crops", storage_path)
        im = cv2.imread(str(p), cv2.IMREAD_COLOR)
        return im if im is not None and im.size else None
    except Exception:
        return None


def _score_rows(rows) -> tuple[list[float], list[dict]]:
    scores, kept = [], []
    for r in rows:
        im = _load_bgr(r["storage_path"])
        if im is None:
            continue
        res = bimetal_score(im)
        if not res["ok"]:
            continue
        scores.append(res["score"])
        kept.append({"asset_id": r["id"], "storage_path": r["storage_path"],
                     "score": round(res["score"], 3),
                     "delta_b": round(res["delta_b"], 2)})
    return scores, kept


def _pct(a) -> str:
    a = np.asarray(a, dtype=np.float32)
    if not len(a):
        return "[empty]"
    return (f"[min={a.min():.2f} p10={np.percentile(a,10):.2f} "
            f"p50={np.median(a):.2f} p90={np.percentile(a,90):.2f} max={a.max():.2f}]")


def _montage(cands: list[dict], path: Path, title: str, cols: int = 8,
             cell: int = 130, cap: int = 48) -> None:
    sample = cands[:cap]
    if not sample:
        return
    from PIL import Image, ImageDraw
    rows = math.ceil(len(sample) / cols)
    sheet = Image.new("RGB", (cols * cell, rows * cell + 18), (25, 25, 25))
    dr = ImageDraw.Draw(sheet)
    dr.text((4, 2), title, fill=(120, 200, 255))
    for k, c in enumerate(sample):
        im = _load_bgr(c["storage_path"])
        if im is None:
            continue
        rgb = cv2.cvtColor(cv2.resize(im, (cell - 8, cell - 20)), cv2.COLOR_BGR2RGB)
        x, y = (k % cols) * cell, (k // cols) * cell + 18
        sheet.paste(Image.fromarray(rgb), (x + 4, y + 4))
        dr.text((x + 4, y + cell - 15), f"{c['score']:.2f} b{c['delta_b']:+.0f}",
                fill=(255, 230, 0))
    sheet.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-pos", type=int, default=600)
    ap.add_argument("--pool", type=int, default=1500)
    ap.add_argument("--run", default="059dc8d")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    # ── POSITIFS 2€ confirmés (avers + revers) ──────────────────────────────
    pos_rows = con.execute(
        "SELECT id, storage_path FROM image_assets "
        "WHERE face IN ('obverse','reverse') AND storage_status='present' "
        "AND storage_path IS NOT NULL LIMIT ?",
        (args.limit_pos,),
    ).fetchall()
    pos_scores, _ = _score_rows(pos_rows)
    print(f"positifs 2€ scorés : {len(pos_scores)}/{len(pos_rows)}")

    # ── POOL LOT (mixte non labellisé) ──────────────────────────────────────
    pool_rows = con.execute(
        "SELECT a.id, a.storage_path FROM image_assets a "
        "JOIN source_images s ON s.id = a.source_image_id "
        f"WHERE s.run_id LIKE '{args.run}%' "
        f"AND s.route_reason IN ({','.join('?' * len(LOT_REASONS))}) "
        "AND a.face IS NULL AND a.storage_status='present' "
        "AND a.storage_path IS NOT NULL LIMIT ?",
        (*LOT_REASONS, args.pool),
    ).fetchall()
    pool_scores, pool_cands = _score_rows(pool_rows)
    print(f"pool lot scoré : {len(pool_scores)}/{len(pool_rows)}")

    # ── distributions ───────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print("BIMÉTAL — distribution du score (distance chroma anneau↔disque)")
    print("=" * 64)
    print(f"  POSITIFS 2€   {_pct(pos_scores)}")
    print(f"  POOL LOT      {_pct(pool_scores)}")

    # ── balayage de seuil : rappel 2€ vs part du pool droppé ────────────────
    pos = np.asarray(pos_scores)
    pool = np.asarray(pool_scores)
    print("\n  seuil τ (garder si score≥τ) :")
    print("   τ      rappel 2€   pool droppé(<τ)")
    for t in (4, 6, 8, 10, 12, 14, 16, 20):
        recall = float((pos >= t).mean()) if len(pos) else 0.0
        dropped = float((pool < t).mean()) if len(pool) else 0.0
        print(f"   {t:>4}   {recall:>7.1%}     {dropped:>7.1%}")

    # ── planches par bande (vérif visuelle de la séparation) ────────────────
    pool_cands.sort(key=lambda c: c["score"])
    for f in OUT_DIR.glob("band_*.png"):
        f.unlink()
    bands = [(0, 4), (4, 8), (8, 12), (12, 18), (18, 999)]
    print("\n  planches pool par bande de score :")
    for lo, hi in bands:
        seg = [c for c in pool_cands if lo <= c["score"] < hi]
        tag = f"band_{lo:03d}_{hi:03d}"
        _montage(seg, OUT_DIR / f"{tag}.png", f"score [{lo},{hi}) — n={len(seg)}")
        print(f"    [{lo:>3},{hi:>3}) : {len(seg):>4} crops → {tag}.png")

    (OUT_DIR / "pool_candidates.jsonl").write_text(
        "\n".join(json.dumps(c) for c in pool_cands) + "\n")
    print(f"\n  candidats pool → {OUT_DIR}/pool_candidates.jsonl")
    print("  ⚠️ vérifier band_000_004 (= monométal non-2€ attendu) avant de fixer τ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
