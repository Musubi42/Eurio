"""Construit les 3 jeux du banc (D1 gold géométrie, D2 récupération, D3 non-régression)
→ manifestes JSON dans `state/crop_recovery/`. Précalcule le HINT (détection prod) et le
SCORE BASELINE une fois pour toutes → les runs de stratégie sont rapides et identiques.

Coûteux (YOLO + DINO par cas) — à lancer UNE fois. `--limit-per` pour un build d'essai.

Usage : .venv/bin/python -m bench.crop_recovery.datasets --datasets D1,D2,D3a,D3b
"""

from __future__ import annotations

import argparse
import json
import sqlite3

import cv2
import numpy as np

from .common import (DB_PATH, RUN_ID, STATE_DIR, circle_from_bbox, crop_candidate,
                     detect_hint, load_raw, score_crops)


def _emu_globe(eid: str | None) -> bool:
    return bool(eid) and ("2009-2eur-10th-anniversary" in eid
                          or "2012-2eur-10-years-of-euro-cash" in eid)


def _finish(entries: list[dict]) -> list[dict]:
    """Crop le hint de chaque entrée + score baseline (batché)."""
    crops, idx = [], []
    for i, e in enumerate(entries):
        bgr = e.pop("_raw")
        h = e["hint"]
        c = crop_candidate(bgr, h["cx"], h["cy"], h["r_final"])
        if c is not None:
            crops.append(c); idx.append(i)
    if crops:
        scores = []
        for k in range(0, len(crops), 64):
            scores += score_crops(crops[k:k + 64])
        for i, s in zip(idx, scores):
            entries[i]["baseline_score"] = round(float(s), 4)
    for e in entries:
        e.setdefault("baseline_score", None)
    return entries


def _prep(rows, dataset, raw_key_of, gold_of=None, limit=None, hint_of=None):
    """`hint_of(row, bgr)` permet d'ancrer le hint sur une géométrie connue (D3a = le
    crop qui a PASSÉ le gate) au lieu de re-détecter. Défaut = détection prod."""
    out: list[dict] = []
    n = 0
    for row in rows:
        if limit and n >= limit:
            break
        raw_key = raw_key_of(row)
        bgr = load_raw(raw_key)
        if bgr is None:
            continue
        hint = hint_of(row, bgr) if hint_of else detect_hint(bgr)
        if hint is None:
            continue
        eid = row["target_eurio_id"] if "target_eurio_id" in row.keys() else row["eurio_id"]
        e = {
            "case_id": f"{dataset}:{row['id']}",
            "dataset": dataset,
            "raw_key": raw_key,
            "target_eurio_id": eid,
            "emu_globe": _emu_globe(eid),
            "hint": hint,
            "_raw": bgr,
        }
        if gold_of is not None:
            e["gold_circle"] = gold_of(row)
        out.append(e)
        n += 1
    return _finish(out)


def build_d1(conn, limit=None):
    rows = conn.execute(
        "SELECT ia.id, ia.eurio_id AS target_eurio_id, ia.bbox_json, si.storage_path AS raw_key "
        "FROM image_assets ia JOIN source_images si ON si.id=ia.source_image_id "
        "WHERE ia.resolution_status='manual' AND ia.face='obverse' "
        "AND ia.detection_method LIKE 'manual%' AND ia.bbox_json IS NOT NULL "
        "AND si.storage_path IS NOT NULL").fetchall()

    # Hint PAR PIÈCE : sur une planche multi-pièces, `detect_hint` (dominante) donnait le
    # MÊME hint à toutes les pièces → recrop mono-pièce sortait N fois le même crop. On
    # re-détecte toutes les pièces (caché par raw) et on prend la détection prod la plus
    # proche du gold de CETTE pièce. Si aucune détection proche (pièce ratée par la prod) →
    # hint dégradé centré sur la pièce, rayon réduit (simule l'undercrop), pour tester quand
    # même la récupération sans livrer le rayon gold.
    det_cache: dict[str, list[dict]] = {}

    def hint_of(row, bgr):
        from vision.normalize_snap import detect_circles_multi
        gx, gy, gr = circle_from_bbox(json.loads(row["bbox_json"]))
        H, W = bgr.shape[:2]
        short = float(min(H, W))
        rk = row["raw_key"]
        if rk not in det_cache:
            trace: list[dict] = []
            detect_circles_multi(bgr, census=True, trace=trace)
            det_cache[rk] = [t for t in trace if t.get("accepted") and t.get("r_bbox", 0) > 0]
        dets = det_cache[rk]
        if dets:
            d = min(dets, key=lambda t: (t["cx"] - gx) ** 2 + (t["cy"] - gy) ** 2)
            if (d["cx"] - gx) ** 2 + (d["cy"] - gy) ** 2 <= gr * gr:  # détection de CETTE pièce
                return {"cx": float(d["cx"]), "cy": float(d["cy"]),
                        "r_final": float(d["r_final"]), "r_bbox": float(d["r_bbox"]),
                        "short": short}
        return {"cx": float(gx), "cy": float(gy), "r_final": float(gr) * 0.5,
                "r_bbox": float(gr) * 0.5, "short": short}

    return _prep(rows, "D1", lambda r: r["raw_key"],
                 gold_of=lambda r: list(circle_from_bbox(json.loads(r["bbox_json"]))),
                 limit=limit, hint_of=hint_of)


def build_d2(conn, limit=None):
    rows = conn.execute(
        "SELECT id, target_eurio_id, storage_path AS raw_key FROM source_images "
        "WHERE source='ebay' AND run_id=? AND crop_status='zero_crops' "
        "AND storage_path IS NOT NULL", (RUN_ID,)).fetchall()
    return _prep(rows, "D2", lambda r: r["raw_key"], limit=limit)


def build_d3a(conn, limit=None):
    """Crops qui ont PASSÉ le gate fragment (non rejetés ensuite) : hint = leur géométrie
    réelle (bbox du crop accepté) → baseline ≈ 100%, le test « ne pas casser » est honnête."""
    rows = conn.execute(
        "SELECT ia.id AS id, si.target_eurio_id AS target_eurio_id, "
        "si.storage_path AS raw_key, ia.bbox_json AS bbox_json "
        "FROM image_assets ia JOIN source_images si ON si.id=ia.source_image_id "
        "WHERE si.source='ebay' AND si.run_id=? AND si.storage_path IS NOT NULL "
        "AND ia.resolution_status IN ('auto_phash','auto_name','needs_review','manual') "
        "AND ia.bbox_json IS NOT NULL", (RUN_ID,)).fetchall()

    def hint_of(row, bgr):
        b = json.loads(row["bbox_json"])
        cx, cy, r = circle_from_bbox(b)
        H, W = bgr.shape[:2]
        return {"cx": cx, "cy": cy, "r_final": r, "r_bbox": r, "short": float(min(H, W))}

    return _prep(rows, "D3a", lambda r: r["raw_key"], limit=limit, hint_of=hint_of)


def build_d3b(d1_entries, n=80):
    """Fragments SYNTHÉTIQUES : crop central 0,5× d'un raw gold → image qui ne contient
    QUE le motif (pas de pièce entière récupérable). Une stratégie ne doit JAMAIS en faire
    passer un (faux-accept). Sauvés en PNG local."""
    frag_dir = STATE_DIR / "frag_synth"
    frag_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for e in d1_entries[:n]:
        bgr = load_raw(e["raw_key"])
        if bgr is None:
            continue
        gc = e.get("gold_circle")
        if not gc:
            continue
        gx, gy, gr = gc
        rr = int(gr * 0.5)
        x0, y0 = int(gx - rr), int(gy - rr)
        sub = bgr[max(0, y0):y0 + 2 * rr, max(0, x0):x0 + 2 * rr]
        if sub.size == 0 or min(sub.shape[:2]) < 16:
            continue
        path = frag_dir / f"{e['case_id'].replace(':', '_')}.png"
        cv2.imwrite(str(path), sub)
        hint = detect_hint(sub)
        if hint is None:  # pas de cercle détecté → hint trivial centré
            h, w = sub.shape[:2]
            hint = {"cx": w / 2.0, "cy": h / 2.0, "r_final": min(h, w) / 2.5,
                    "r_bbox": min(h, w) / 2.0, "short": min(h, w)}
        out.append({"case_id": f"D3b:{path.stem}", "dataset": "D3b",
                    "raw_key": str(path), "target_eurio_id": e["target_eurio_id"],
                    "emu_globe": e["emu_globe"], "hint": hint, "is_fragment": True,
                    "_raw": sub})
    return _finish(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", default="D1,D2,D3a,D3b")
    ap.add_argument("--limit-per", type=int, default=None)
    args = ap.parse_args()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    want = set(args.datasets.split(","))

    d1 = None
    if "D1" in want:
        d1 = build_d1(conn, args.limit_per)
        (STATE_DIR / "D1.json").write_text(json.dumps({"dataset": "D1", "cases": d1}))
        print(f"D1 gold géométrie : {len(d1)} cas (EMU/globe: {sum(e['emu_globe'] for e in d1)})")
    if "D2" in want:
        d2 = build_d2(conn, args.limit_per)
        (STATE_DIR / "D2.json").write_text(json.dumps({"dataset": "D2", "cases": d2}))
        print(f"D2 récupération   : {len(d2)} cas (EMU/globe: {sum(e['emu_globe'] for e in d2)})")
    if "D3a" in want:
        d3a = build_d3a(conn, args.limit_per)
        (STATE_DIR / "D3a.json").write_text(json.dumps({"dataset": "D3a", "cases": d3a}))
        print(f"D3a non-régr succ : {len(d3a)} cas")
    if "D3b" in want:
        if d1 is None:
            d1 = build_d1(conn, args.limit_per)
        d3b = build_d3b(d1, n=80 if not args.limit_per else args.limit_per)
        (STATE_DIR / "D3b.json").write_text(json.dumps({"dataset": "D3b", "cases": d3b}))
        print(f"D3b fragments synth: {len(d3b)} cas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
