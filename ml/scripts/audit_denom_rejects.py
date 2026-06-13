"""Audit visuel C7 pilier 2 — planches des rejets candidats du gate dénomination.

Génère des planches-contact des crops ``denom='not_2eur'`` encore ``open`` en
review (= ce que ``backfill_denom --reject`` évacuerait), triées par
``denom_2eur_score`` DÉCROISSANT : la première page = la bande grise proche du
seuil, là où vivent les faux drops potentiels. Ajoute une planche des conflits
« probe dit junk / review humaine a identifié une vraie pièce » (faux drops
avérés, à verser au gold comme positifs durs).

Routes/labels : AUCUNE écriture DB — lecture seule, sortie PNG + JSONL.

Usage :
  python -m scripts.audit_denom_rejects [--per-page 48] [--out reject_audit]
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

import cv2

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from scripts.bench_denom import _load_bgr  # noqa: E402

DB_PATH = ML_DIR / "state" / "eurio.db"
OUT_DIR = ML_DIR / "state" / "denom_bench"

OPEN_REJECTS_SQL = """
SELECT ia.id AS asset_id, ia.storage_path,
       MAX(p.denom_2eur_score) AS score,
       substr(si.run_id, 1, 8) AS run
FROM image_assets ia
JOIN source_images si ON si.id = ia.source_image_id
JOIN review_queue rq ON rq.image_asset_id = ia.id
LEFT JOIN image_asset_dino_predictions p ON p.asset_id = ia.id
WHERE ia.denom = 'not_2eur' AND rq.status = 'open'
GROUP BY ia.id
ORDER BY score DESC
"""

HUMAN_CONFLICTS_SQL = """
SELECT ia.id AS asset_id, ia.storage_path,
       MAX(p.denom_2eur_score) AS score,
       rq.decided_eurio_id, rq.decided_by,
       substr(si.run_id, 1, 8) AS run
FROM image_assets ia
JOIN source_images si ON si.id = ia.source_image_id
JOIN review_queue rq ON rq.image_asset_id = ia.id
LEFT JOIN image_asset_dino_predictions p ON p.asset_id = ia.id
WHERE ia.denom = 'not_2eur' AND rq.status = 'done'
  AND rq.decided_eurio_id IS NOT NULL AND rq.decided_by != 'auto_dino'
GROUP BY ia.id
ORDER BY score DESC
"""


def _montage(cands: list[dict], path: Path, title: str, cols: int = 8,
             cell: int = 150) -> None:
    from PIL import Image, ImageDraw
    rows = math.ceil(len(cands) / cols)
    sheet = Image.new("RGB", (cols * cell, rows * cell + 18), (25, 25, 25))
    dr = ImageDraw.Draw(sheet)
    dr.text((4, 2), title, fill=(120, 200, 255))
    for k, c in enumerate(cands):
        im = _load_bgr(c["storage_path"])
        if im is None:
            continue
        rgb = cv2.cvtColor(cv2.resize(im, (cell - 8, cell - 22)), cv2.COLOR_BGR2RGB)
        x, y = (k % cols) * cell, (k // cols) * cell + 18
        sheet.paste(Image.fromarray(rgb), (x + 4, y + 4))
        score = "?" if c["score"] is None else f"{c['score']:.3f}"
        dr.text((x + 4, y + cell - 16), f"{score} {c['run']}", fill=(255, 230, 0))
    sheet.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-page", type=int, default=48)
    ap.add_argument("--out", default="reject_audit",
                    help="sous-dossier de state/denom_bench/")
    args = ap.parse_args()

    out = OUT_DIR / args.out
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rejects = [dict(r) for r in conn.execute(OPEN_REJECTS_SQL)]
    conflicts = [dict(r) for r in conn.execute(HUMAN_CONFLICTS_SQL)]

    pages = math.ceil(len(rejects) / args.per_page) if rejects else 0
    for i in range(pages):
        chunk = rejects[i * args.per_page:(i + 1) * args.per_page]
        _montage(chunk, out / f"page_{i:02d}.png",
                 f"open not_2eur (rejet candidat) — page {i + 1}/{pages}, "
                 f"score desc (bande grise d'abord)")
    if conflicts:
        _montage(conflicts, out / "human_conflicts.png",
                 "probe=not_2eur MAIS review humaine=vraie piece (faux drops "
                 "averes — candidats positifs durs du gold)")

    with (out / "rejects.jsonl").open("w") as f:
        for r in rejects:
            f.write(json.dumps(r) + "\n")
        for r in conflicts:
            f.write(json.dumps({**r, "human_conflict": True}) + "\n")

    print(f"open not_2eur : {len(rejects)} crops → {pages} planches dans {out}")
    print(f"conflits humains (faux drops avérés) : {len(conflicts)} "
          f"→ human_conflicts.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
