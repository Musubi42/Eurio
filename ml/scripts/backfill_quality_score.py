"""Backfill ``image_assets.quality_score`` depuis l'oracle de crop (P3 du
chantier crop-quality-overhaul, jamais câblé — cf. doc §4 P3 et question #5).

Source = ``state/crop_diag/results.csv`` (diagnostic post-refine, par crop :
``r_ratio = r_pipe / r_probe`` via l'oracle Otsu ``_probe_true_rim``). L'oracle
ne couvre que ~46 % des crops (fond uni où Otsu isole le rim) ; les autres
restent NULL = « non mesuré » (l'expert crop_quality s'abstient).

quality_score = closeness symétrique au rim vrai, clampée [0,1] :
    clamp(min(r_ratio, 2 - r_ratio), 0, 1)
  - r_ratio = 1.0 (parfait)            → 1.0
  - undercrop r_ratio < 0.85           → r_ratio (0.60 → 0.60, 0.50 → 0.50)
  - overcrop  r_ratio > 1.15           → 2 - r_ratio (1.20 → 0.80, 1.43 → 0.57)
Le seuil de pénalité de l'expert (review/validation/experts.py, _QUALITY_MIN)
est 0.85 = le seuil d'undercrop documenté du chantier.

Additif et réversible : ``UPDATE ... SET quality_score=NULL, quality_pipeline_version=NULL``
annule. Idempotent (re-run = mêmes valeurs).

Usage :
    python scripts/backfill_quality_score.py            # dry-run (distribution)
    python scripts/backfill_quality_score.py --commit   # écrit en base

⚠️  MIGRATION VPS-ONLY sous Direction A (docs/work-in-progress/local-sync/
migration-direction-a.md §C7) : ce script écrit le canonique (``UPDATE
image_assets`` non transporté par une route ``/ingest``). Ne PAS le lancer
contre une réplique locale (Mac/PC read-only ou client d'un VPS canonique) —
refuse automatiquement sauf ``--i-know-this-is-canonical``.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parent.parent
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from scripts._vps_only_guard import guard_vps_only  # noqa: E402

# Version du pipeline de score (oracle r_ratio v1) — tracée pour invalidation.
QUALITY_PIPELINE_VERSION = 1

_ML_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CSV = _ML_ROOT / "state" / "crop_diag" / "results.csv"
_DEFAULT_DB = _ML_ROOT / "state" / "eurio.db"


def quality_score_from_r_ratio(r_ratio: float) -> float:
    """closeness symétrique au rim vrai, clampée [0,1]."""
    return max(0.0, min(1.0, min(r_ratio, 2.0 - r_ratio)))


def _bucket(q: float) -> str:
    if q < 0.60:
        return "severe (<0.60)"
    if q < 0.85:
        return "penalised [0.60,0.85)"
    return "ok [0.85,1.0]"


def load_scores(csv_path: Path) -> list[tuple[str, float]]:
    """(asset_id, quality_score) pour les crops avec un r_ratio oracle."""
    out: list[tuple[str, float]] = []
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            raw = row.get("r_ratio")
            if not raw:
                continue
            out.append((row["asset_id"], round(quality_score_from_r_ratio(float(raw)), 4)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=_DEFAULT_CSV)
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--commit", action="store_true", help="écrit en base (défaut = dry-run)")
    ap.add_argument(
        "--i-know-this-is-canonical", action="store_true", dest="allow_non_vps",
        help="Bypass le garde-fou VPS-only (Direction A) — --db pointe une copie canonique.",
    )
    args = ap.parse_args()
    guard_vps_only("backfill_quality_score", allow=args.allow_non_vps)

    scores = load_scores(args.csv)
    conn = sqlite3.connect(args.db)
    known = {r[0] for r in conn.execute("SELECT id FROM image_assets")}
    matched = [(a, q) for a, q in scores if a in known]
    missing = len(scores) - len(matched)

    dist = Counter(_bucket(q) for _, q in matched)
    print(f"CSV: {args.csv}")
    print(f"crops with r_ratio oracle: {len(scores)}  (in image_assets: {len(matched)}, "
          f"absent: {missing})")
    print("quality_score distribution:")
    for k in ("ok [0.85,1.0]", "penalised [0.60,0.85)", "severe (<0.60)"):
        n = dist.get(k, 0)
        print(f"  {k:24} {n:5} ({100 * n / max(1, len(matched)):.1f}%)")
    flagged = sum(1 for _, q in matched if q < 0.85)
    print(f"would be penalised by crop_quality (score < 0.85): {flagged}")

    if not args.commit:
        print("\nDRY-RUN — rien écrit. Relancer avec --commit pour persister.")
        conn.close()
        return

    conn.execute("BEGIN")
    try:
        conn.executemany(
            "UPDATE image_assets SET quality_score = ?, quality_pipeline_version = ? "
            "WHERE id = ?",
            [(q, QUALITY_PIPELINE_VERSION, a) for a, q in matched],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print(f"\nCOMMIT — quality_score écrit sur {len(matched)} assets "
          f"(quality_pipeline_version={QUALITY_PIPELINE_VERSION}).")
    conn.close()


if __name__ == "__main__":
    main()
