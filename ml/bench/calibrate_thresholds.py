"""Grid search des seuils qualité — maximise le best-frame agreement.

Usage (depuis ml/) :

    .venv/bin/python -m bench.calibrate_thresholds --device Pixel9a

Pour chaque config candidate (grille chunk-7 : 6×4×4 = 96), rejoue toutes les
sessions **annotées** (``ground_truth.json`` avec ``human_best_frame_id``) et
mesure le % de sessions où la sélection D8 tombe sur la frame désignée par
l'humain. Sortie : ranking top-10 + ``recommended_thresholds.json`` sous
``ml/bench/reports/``.

Les sessions sans annotation sont listées puis ignorées — jamais comptées
comme accord silencieux (``feedback_no_debt``).
"""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import dataclass
from pathlib import Path

from bench.replay import replay
from bench.session_io import (
    ML_DIR,
    SESSIONS_ROOT,
    Session,
    iter_session_dirs,
    load_ground_truth,
    load_session,
)

REPORTS_DIR = ML_DIR / "bench" / "reports"

# Grille v1 du chunk-7. Extension (motion, ceiling…) → passer à optuna.
SHARPNESS_MIN_GRID = (40.0, 60.0, 80.0, 100.0, 120.0, 160.0)
EXPOSURE_BAND_GRID = (0.15, 0.20, 0.25, 0.30)
COMPLETENESS_MIN_GRID = (0.85, 0.90, 0.95, 0.98)


@dataclass(frozen=True)
class Candidate:
    sharpness_min: float
    exposure_band_half_width: float
    completeness_min: float


def agreement(
    candidate: Candidate, annotated: list[tuple[Session, int]]
) -> tuple[float, int]:
    """(taux d'accord, nb de sessions avec sélection) pour *candidate*."""
    hits = 0
    selected = 0
    for session, human_pick in annotated:
        config = session.config.with_overrides(
            {
                "sharpness_min": candidate.sharpness_min,
                "exposure_band_half_width": candidate.exposure_band_half_width,
                "completeness_min": candidate.completeness_min,
            }
        )
        result = replay(session, config)
        pick = result.first_selection_frame_id
        if pick is None:
            continue
        selected += 1
        if pick == human_pick:
            hits += 1
    rate = hits / selected if selected else 0.0
    return rate, selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="ne calibrer que sur ce device")
    parser.add_argument("--root", default=str(SESSIONS_ROOT))
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)

    annotated: list[tuple[Session, int]] = []
    skipped: list[str] = []
    for device, path in iter_session_dirs(Path(args.root), args.device):
        gt = load_ground_truth(path)
        if gt is None or gt.human_best_frame_id is None:
            skipped.append(f"{device}/{path.name}")
            continue
        session = load_session(path, device=device)
        if session.config is None:
            skipped.append(f"{device}/{path.name} (sans config)")
            continue
        annotated.append((session, gt.human_best_frame_id))

    if skipped:
        print(f"⚠ {len(skipped)} session(s) sans annotation exploitable, ignorées :")
        for s in skipped:
            print(f"    {s}")
    if not annotated:
        print("error: aucune session annotée — lancer bench.annotate_session d'abord")
        return 2

    print(f"Calibration sur {len(annotated)} session(s) annotée(s)…")
    results = []
    for s_min, band, c_min in itertools.product(
        SHARPNESS_MIN_GRID, EXPOSURE_BAND_GRID, COMPLETENESS_MIN_GRID
    ):
        cand = Candidate(s_min, band, c_min)
        rate, n = agreement(cand, annotated)
        results.append((rate, n, cand))

    results.sort(key=lambda r: (-r[0], -r[1]))
    print(f"\nTop {args.top} / {len(results)} configs "
          "(agreement = sélection D8 == pick humain) :")
    print("  agree   n  sharpness_min  exposure_band  completeness_min")
    for rate, n, cand in results[: args.top]:
        print(
            f"  {rate:5.1%}  {n:2d}  {cand.sharpness_min:13.0f}"
            f"  {cand.exposure_band_half_width:13.2f}"
            f"  {cand.completeness_min:16.2f}"
        )

    best_rate, best_n, best = results[0]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "recommended_thresholds.json"
    out.write_text(
        json.dumps(
            {
                "sharpness_min": best.sharpness_min,
                "exposure_band_half_width": best.exposure_band_half_width,
                "completeness_min": best.completeness_min,
                "best_frame_agreement": best_rate,
                "n_sessions": best_n,
                "device": args.device,
                "grid_size": len(results),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nOK · recommandation écrite dans {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
