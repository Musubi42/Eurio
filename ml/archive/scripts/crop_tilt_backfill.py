"""Backfill des colonnes de tilt dans ``state/crop_diag/results.csv``
(chantier crop-quality-overhaul — mesure d'inclinaison des pièces).

Le banc ``/crop-bench`` sait déjà mesurer le tilt à la volée (``measure_tilt``)
et l'afficher par carte, mais le TRI « plus ovales d'abord » lit la colonne
``axis_ratio`` de ``results.csv`` — absente tant que ce backfill n'a pas tourné.
Ce script calcule ``measure_tilt`` sur TOUT le parc eBay du diagnostic et écrit
trois colonnes (``axis_ratio``, ``tilt_deg``, ``tilt_trustworthy``) dans le CSV,
pour que le tri corpus-wide fonctionne ET pour sortir l'histogramme réel du tilt.

Mesure IDENTIQUE à celle du ``/sample`` : même hint (``_oracle_from_raw`` →
centre + ``r_pipe``), même ``measure_tilt``. Lecture seule de la DB ; seul
``results.csv`` est réécrit (atomique via fichier temporaire).

Usage :
    cd ml
    .venv/bin/python -m scripts.crop_tilt_backfill            # calcule + réécrit
    .venv/bin/python -m scripts.crop_tilt_backfill --limit 50 # test rapide
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from pathlib import Path

import cv2

_ML = Path(__file__).resolve().parents[1]
if str(_ML) not in sys.path:
    sys.path.insert(0, str(_ML))

from serving.crop_bench_routes import _asset_map, _RESULTS_CSV  # noqa: E402
from vision.crop_detectors import measure_tilt  # noqa: E402
from scripts.crop_quality_diag import _oracle_from_raw, _raw_local_path  # noqa: E402

_NEW_COLS = ["axis_ratio", "tilt_deg", "tilt_trustworthy"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Max lignes (0 = toutes).")
    args = ap.parse_args()

    if not _RESULTS_CSV.exists():
        raise SystemExit(f"results.csv absent : {_RESULTS_CSV} — lance d'abord le diagnostic.")

    with _RESULTS_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    for c in _NEW_COLS:
        if c not in fieldnames:
            fieldnames.append(c)

    amap = _asset_map()
    n = {"seen": 0, "no_meta": 0, "no_raw": 0, "measured": 0, "trustworthy": 0}
    buckets = {"round": 0, "slight": 0, "tilted": 0, "strong": 0, "untrust": 0}
    t0 = time.time()

    for r in rows:
        if args.limit and n["seen"] >= args.limit:
            # Lignes restantes : colonnes tilt vides (None → sentinel au tri).
            for c in _NEW_COLS:
                r.setdefault(c, "")
            continue
        n["seen"] += 1
        for c in _NEW_COLS:
            r.setdefault(c, "")

        meta = amap.get(r["asset_id"])
        if not meta or not meta.get("raw_storage_path"):
            n["no_meta"] += 1
            continue
        raw_path = _raw_local_path(meta["raw_storage_path"])
        if not raw_path.exists():
            n["no_raw"] += 1
            continue
        bgr = cv2.imread(str(raw_path), cv2.IMREAD_COLOR)
        if bgr is None:
            n["no_raw"] += 1
            continue

        oracle = _oracle_from_raw(bgr, meta.get("bbox_json"))
        hint = {"cx": oracle["hint_cx"], "cy": oracle["hint_cy"], "r": oracle["r_pipe"]}
        tilt = measure_tilt(bgr, hint)

        ar = tilt.get("axis_ratio")
        td = tilt.get("tilt_deg")
        trust = bool(tilt.get("trustworthy"))
        r["axis_ratio"] = "" if ar is None else f"{ar:.4f}"
        r["tilt_deg"] = "" if td is None else f"{td:.2f}"
        r["tilt_trustworthy"] = "1" if trust else "0"

        if ar is not None:
            n["measured"] += 1
        # Histogramme (uniquement sur les mesures fiables — les autres = inconnu).
        if not trust or td is None:
            buckets["untrust"] += 1
        else:
            n["trustworthy"] += 1
            if ar is not None and ar >= 0.97:
                buckets["round"] += 1
            elif td < 10:
                buckets["slight"] += 1
            elif td < 30:
                buckets["tilted"] += 1
            else:
                buckets["strong"] += 1

        if n["seen"] % 200 == 0:
            print(f"  {n['seen']} traités ({time.time()-t0:.0f}s)", flush=True)

    # Réécriture atomique.
    tmp = _RESULTS_CSV.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(_RESULTS_CSV)

    print(f"\n[BACKFILL] {n}")
    print("histogramme tilt (fiables uniquement) :")
    total_trust = n["trustworthy"] or 1
    labels = {
        "round": "rond     (axis≥0.97, indéterminable)",
        "slight": "léger    (<10°)",
        "tilted": "net      (10–30°)",
        "strong": "fort     (≥30°)",
    }
    for k in ("round", "slight", "tilted", "strong"):
        v = buckets[k]
        bar = "█" * int(40 * v / total_trust)
        print(f"  {labels[k]:38s} {v:4d}  {bar}")
    print(f"  (non fiables / non mesurés : {buckets['untrust']})")
    print(f"durée {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
