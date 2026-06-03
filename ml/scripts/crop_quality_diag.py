"""Diagnostic chiffré de la qualité des crops eBay existants (lecture seule).

Ne modifie pas eurio.db, ne re-croppe pas, ne scrape pas eBay.
Travaille exclusivement sur les raws + crops en cache local.

Métriques (mêmes que l'oracle bench_listing_bimetal) :
  - fill_ratio   : aire pièce estimée / aire crop (224×224)
  - r_pipe/r_probe : rayon crop vs rayon oracle Otsu (_probe_true_rim)
  - class : undercrop / overcrop / wrong / ok
  - bimetal_inner_ring : détecté si deux cercles concentriques nets

Buckets : bimetal_2eur / mono, × fond_clair / fond_texturé
  - bimetal = face_value==2.0 AND is_commemorative==1
  - fond_clair = mediane gris du fond du crop > seuil (heuristique)

Sorties dans ml/state/crop_diag/ :
  - contact_sheet.jpg   — planche contact des pires crops classés
  - results.csv         — chemin,classe,fill_ratio,r_ratio,bucket
"""
from __future__ import annotations

import csv
import sys
import sqlite3
import random
from pathlib import Path

import cv2
import numpy as np

_ML = Path(__file__).resolve().parents[1]
if str(_ML) not in sys.path:
    sys.path.insert(0, str(_ML))

from scripts.bench_listing_bimetal import _probe_true_rim  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DB = _ML / "state" / "eurio.db"
_CACHE = Path.home() / ".cache" / "eurio"
_OUT = _ML / "state" / "crop_diag"

_UNDERCROP_TOLERANCE = 0.85   # r_pipe/r_probe < 0.85 → undercrop
# fill_ratio ici = non_black_pixels / inscribed_circle_area (max ~0.97 pour bon crop)
# Un crop correct = 0.90-1.00. Si < 0.70, la pièce n'occupe qu'une portion du cercle.
_FILL_RATIO_UNDERCROP_FALLBACK = 0.70  # si oracle n/a et fill bas → suspect undercrop
_FILL_RATIO_WRONG = 0.50       # fill < 0.50 → pas de pièce reconnaissable (wrong/parasite)

# Heuristic pour fond clair : luminosité médiane des coins du crop > seuil
_LIGHT_BG_THRESHOLD = 140

# Contact sheet settings
_CONTACT_CELL = 224           # px par cell
_CONTACT_COLS = 10
_CONTACT_MAX_WORST = 100      # nombre de pires crops dans la planche

_BG = (24, 24, 24)

# Sample size cap (pour limiter le temps : on prend tous les présents si <= MAX)
_MAX_SAMPLE = 2274  # tous les crops eBay présents


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _crop_local_path(storage_path: str) -> Path:
    return _CACHE / "enrichment-crops" / storage_path


def _raw_local_path(storage_path: str) -> Path:
    return _CACHE / "enrichment-raws" / storage_path


def _estimate_fill_ratio(crop_bgr: np.ndarray) -> float:
    """Estime fill_ratio = aire pièce visible / aire cercle inscrit théorique.

    Les crops sont masqués circulairement (coins noirs). On compte les pixels
    non-noirs (somme canal > 15) et on rapporte au cercle inscrit dans le
    carré 224×224 (aire = π × (112)² ≈ 39478 px).

    Un crop correct (pièce bien centrée) → ~0.97 (la pièce remplit la quasi-
    totalité du cercle).
    Un undercrop (pièce + fond visible autour) → > 1.0 théoriquement mais est
    capé à 1.0 car le fond noir est exclu.
    Un overcrop sévère → 0 (pièce absente ou hors cadre).
    Un crop "pièce trop petite" → < 0.50 (anneau interne, fond visible).
    """
    h, w = crop_bgr.shape[:2]
    non_black = int((crop_bgr.sum(axis=2) > 15).sum())
    inscribed_r = min(h, w) / 2.0
    inscribed_area = np.pi * inscribed_r ** 2
    return float(non_black) / inscribed_area


def _estimate_radius_in_crop(crop_bgr: np.ndarray) -> float | None:
    """Estime le rayon en pixels dans le crop 224×224 via Otsu+contour.
    Retourne None si pas de contour centré trouvé."""
    h, w = crop_bgr.shape[:2]
    cx, cy = w // 2, h // 2
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    best_r = None
    for inv in (False, True):
        flag = cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY
        _, bw = cv2.threshold(gray, 0, 255, flag | cv2.THRESH_OTSU)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            if cv2.pointPolygonTest(cnt, (cx, cy), False) < 0:
                continue
            area = cv2.contourArea(cnt)
            if area < 500:
                continue
            (_, _), r_enc = cv2.minEnclosingCircle(cnt)
            fill = area / max(1.0, np.pi * r_enc ** 2)
            if fill < 0.50:
                continue
            if best_r is None or r_enc > best_r:
                best_r = float(r_enc)
    return best_r


def _detect_bimetal_inner_ring(crop_bgr: np.ndarray) -> bool:
    """Détecte si le crop a été pris sur le disque interne d'une pièce bimétallique.

    Heuristique : deux cercles concentriques nets dans le crop (Hough), le
    grand (outer) et le petit (inner). Ratio inner/outer ~ 0.55-0.75.
    Si crop_r_outer/crop_short < 0.45 (pièce très petite dans le crop),
    on suspecte que c'est l'anneau interne qui a été cropped.
    """
    h, w = crop_bgr.shape[:2]
    short = min(h, w)
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    # Hough circles dans le crop
    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT,
        dp=1.2, minDist=short * 0.3,
        param1=80, param2=20,
        minRadius=int(short * 0.05),
        maxRadius=int(short * 0.50),
    )
    if circles is None:
        return False
    circles = np.round(circles[0, :]).astype(int)
    # Trie par rayon décroissant
    circles = sorted(circles, key=lambda c: -c[2])
    if len(circles) >= 2:
        r_outer = circles[0][2]
        r_inner = circles[1][2]
        ratio = r_inner / max(1, r_outer)
        if 0.40 <= ratio <= 0.80:
            # Deux cercles concentriques dont le plus grand < 45% du short
            if r_outer < 0.48 * short:
                return True
    # Cas alternatif : un seul cercle mais très petit (< 42% short) → suspect
    if len(circles) >= 1 and circles[0][2] < 0.42 * short:
        return True
    return False


def _is_light_background(raw_bgr: np.ndarray, n: int = 40) -> bool:
    """Retourne True si le fond du RAW est clair (médiane des coins > seuil).

    Appliqué sur le raw, pas sur le crop (les crops ont des coins masqués noirs).
    """
    h, w = raw_bgr.shape[:2]
    gray = cv2.cvtColor(raw_bgr, cv2.COLOR_BGR2GRAY)
    corners = [
        gray[:n, :n], gray[:n, w - n:], gray[h - n:, :n], gray[h - n:, w - n:]
    ]
    vals = np.concatenate([c.ravel() for c in corners])
    return float(np.median(vals)) > _LIGHT_BG_THRESHOLD


# ---------------------------------------------------------------------------
# Oracle appliqué sur le raw (identique à bench_listing_bimetal)
# ---------------------------------------------------------------------------

def _oracle_from_raw(raw_bgr: np.ndarray, bbox_json: str | None) -> dict:
    """Applique _probe_true_rim sur le raw en utilisant le bbox crop si dispo.

    Si bbox_json est NULL (125 entrées 'collected'), on utilise le centre du raw.
    Retourne dict(r_pipe, r_probe, r_ratio, hint_cx, hint_cy).
    """
    import json
    h, w = raw_bgr.shape[:2]
    if bbox_json:
        try:
            bb = json.loads(bbox_json)
            # bbox_json format: {x, y, w, h} (top-left + size)
            if "x" in bb and "w" in bb:
                bx, by, bw, bh = bb["x"], bb["y"], bb["w"], bb["h"]
                hint_cx = int(bx + bw / 2)
                hint_cy = int(by + bh / 2)
                r_pipe = int(min(bw, bh) / 2)
            elif "cx" in bb:
                hint_cx, hint_cy, r_pipe = int(bb["cx"]), int(bb["cy"]), int(bb["r"])
            elif "x1" in bb:
                x1, y1, x2, y2 = bb["x1"], bb["y1"], bb["x2"], bb["y2"]
                hint_cx = int((x1 + x2) / 2)
                hint_cy = int((y1 + y2) / 2)
                r_pipe = int(min(x2 - x1, y2 - y1) / 2)
            else:
                hint_cx, hint_cy = w // 2, h // 2
                r_pipe = min(h, w) // 4
        except Exception:
            hint_cx, hint_cy = w // 2, h // 2
            r_pipe = min(h, w) // 4
    else:
        # Pas de bbox stocké — on essaie quand même de prober le centre
        hint_cx, hint_cy = w // 2, h // 2
        r_pipe = min(h, w) // 4

    r_probe = _probe_true_rim(raw_bgr, hint_cx, hint_cy, r_pipe)
    r_ratio = (r_pipe / r_probe) if r_probe else None
    return {
        "hint_cx": hint_cx, "hint_cy": hint_cy,
        "r_pipe": r_pipe, "r_probe": r_probe, "r_ratio": r_ratio,
    }


# ---------------------------------------------------------------------------
# Classify crop
# ---------------------------------------------------------------------------

def _classify(fill_ratio: float, r_ratio: float | None) -> str:
    """Classe un crop en undercrop / overcrop / wrong / ok.

    fill_ratio = non_black / inscribed_circle_area. Bon crop ≈ 0.97.
    Undercrop oracle : r_pipe/r_probe < 0.85 (anneau interne ou bbox serrée).
    Wrong : fill < 0.50 (cercle parasite, date prise pour pièce, etc.).
    Overcrop fallback : fill < 0.70 quand oracle N/A (pièce trop petite dans cadre).
    """
    # Wrong = pas de pièce reconnaissable dans le crop
    if fill_ratio < _FILL_RATIO_WRONG:
        return "wrong"
    # Undercrop confirmé par oracle raw
    if r_ratio is not None and r_ratio < _UNDERCROP_TOLERANCE:
        return "undercrop"
    # Undercrop fallback via fill (oracle non disponible)
    if r_ratio is None and fill_ratio < _FILL_RATIO_UNDERCROP_FALLBACK:
        return "undercrop"
    return "ok"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _select_assets(n: int, seed: int = 42) -> list[dict]:
    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT
            a.id AS asset_id,
            a.storage_path AS crop_path,
            a.bbox_json,
            a.detection_method,
            si.storage_path AS raw_path,
            COALESCE(a.eurio_id, si.target_eurio_id) AS eurio_id,
            c.face_value,
            c.is_commemorative,
            c.country,
            c.year
        FROM image_assets a
        JOIN source_images si ON si.id = a.source_image_id
        LEFT JOIN coins c ON c.eurio_id = COALESCE(a.eurio_id, si.target_eurio_id)
        WHERE si.source = 'ebay'
          AND a.storage_status = 'present'
          AND si.storage_status = 'present'
        ORDER BY a.id
    """).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    rng = random.Random(seed)
    rng.shuffle(data)
    return data[:n]


def _process_asset(row: dict) -> dict | None:
    crop_local = _crop_local_path(row["crop_path"])
    raw_local = _raw_local_path(row["raw_path"])

    if not crop_local.exists():
        return None  # manque en cache
    if not raw_local.exists():
        return None

    crop_bgr = cv2.imread(str(crop_local), cv2.IMREAD_COLOR)
    if crop_bgr is None:
        return None

    raw_bgr = cv2.imread(str(raw_local), cv2.IMREAD_COLOR)
    if raw_bgr is None:
        return None

    # Métriques sur le crop
    fill_ratio = _estimate_fill_ratio(crop_bgr)
    # Fond clair/texturé détecté sur le RAW (coins du crop = masqués noirs)
    is_light_bg = _is_light_background(raw_bgr)
    is_bimetal_coin = (
        row.get("face_value") == 2.0 and bool(row.get("is_commemorative"))
    )

    # Oracle sur le raw
    oracle = _oracle_from_raw(raw_bgr, row.get("bbox_json"))
    r_ratio = oracle.get("r_ratio")

    # Détection anneau interne (coûteux : seulement sur bimetal)
    bimetal_inner_ring = False
    if is_bimetal_coin:
        bimetal_inner_ring = _detect_bimetal_inner_ring(crop_bgr)

    # Classe
    crop_class = _classify(fill_ratio, r_ratio)

    # Bucket
    coin_type = "bimetal" if is_bimetal_coin else "mono"
    bg_type = "light" if is_light_bg else "textured"
    bucket = f"{coin_type}_{bg_type}"

    return {
        "asset_id": row["asset_id"],
        "crop_path": str(crop_local),
        "raw_path": str(raw_local),
        "eurio_id": row.get("eurio_id") or "",
        "face_value": row.get("face_value"),
        "is_commemorative": int(row.get("is_commemorative") or 0),
        "country": row.get("country") or "",
        "year": row.get("year"),
        "detection_method": row.get("detection_method") or "",
        "fill_ratio": round(fill_ratio, 4),
        "r_pipe": oracle.get("r_pipe"),
        "r_probe": oracle.get("r_probe"),
        "r_ratio": round(r_ratio, 4) if r_ratio is not None else None,
        "bimetal_inner_ring": int(bimetal_inner_ring),
        "is_light_bg": int(is_light_bg),
        "is_bimetal_coin": int(is_bimetal_coin),
        "bucket": bucket,
        "crop_class": crop_class,
    }


def _make_contact_sheet(results: list[dict], max_n: int = _CONTACT_MAX_WORST,
                         cols: int = _CONTACT_COLS, cell: int = _CONTACT_CELL,
                         out_path: Path = _OUT / "contact_sheet.jpg") -> None:
    """Planche contact des pires crops (undercrop+wrong en premier, puis overcrop)."""
    priority = {"undercrop": 0, "wrong": 1, "overcrop": 2, "ok": 3}
    ordered = sorted(results, key=lambda r: (
        priority.get(r["crop_class"], 9),
        r.get("r_ratio") if r.get("r_ratio") is not None else 1.0,
        r["fill_ratio"],
    ))[:max_n]

    rows_count = (len(ordered) + cols - 1) // cols
    sheet_h = rows_count * (cell + 24)
    sheet_w = cols * cell
    sheet = np.full((sheet_h, sheet_w, 3), _BG, dtype=np.uint8)

    for i, r in enumerate(ordered):
        col = i % cols
        row_i = i // cols
        x0 = col * cell
        y0 = row_i * (cell + 24)

        crop_bgr = cv2.imread(r["crop_path"], cv2.IMREAD_COLOR)
        if crop_bgr is None:
            thumb = np.full((cell, cell, 3), 60, dtype=np.uint8)
        else:
            thumb = cv2.resize(crop_bgr, (cell, cell), interpolation=cv2.INTER_AREA)

        # Bordure couleur selon classe
        colors = {
            "undercrop": (0, 0, 200),
            "wrong": (0, 0, 200),
            "overcrop": (0, 165, 255),
            "ok": (0, 180, 0),
        }
        border_color = colors.get(r["crop_class"], (128, 128, 128))
        cv2.rectangle(thumb, (0, 0), (cell - 1, cell - 1), border_color, 3)

        # Label superposé
        label = f"{r['crop_class']} f={r['fill_ratio']:.2f}"
        if r.get("r_ratio") is not None:
            label += f" rr={r['r_ratio']:.2f}"
        cv2.putText(thumb, label, (3, cell - 5), cv2.FONT_HERSHEY_SIMPLEX,
                    0.32, (255, 255, 255), 1)
        inner_flag = " BI" if r.get("bimetal_inner_ring") else ""
        cv2.putText(thumb, r.get("country", "") + inner_flag,
                    (3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (220, 220, 0), 1)

        sheet[y0:y0 + cell, x0:x0 + cell] = thumb

        # Label texte sous chaque thumbnail
        strip = np.full((24, cell, 3), _BG, dtype=np.uint8)
        txt = f"{r.get('eurio_id', '')[:22]}"
        cv2.putText(strip, txt, (2, 17), cv2.FONT_HERSHEY_SIMPLEX,
                    0.28, (200, 200, 200), 1)
        sheet[y0 + cell:y0 + cell + 24, x0:x0 + cell] = strip

    cv2.imwrite(str(out_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"  Contact sheet → {out_path}  ({len(ordered)} crops)")


def _write_csv(results: list[dict], out_path: Path) -> None:
    if not results:
        return
    fields = ["asset_id", "crop_path", "raw_path", "eurio_id", "country", "year",
              "face_value", "is_commemorative", "detection_method",
              "fill_ratio", "r_pipe", "r_probe", "r_ratio",
              "bimetal_inner_ring", "is_light_bg", "is_bimetal_coin",
              "bucket", "crop_class"]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"  CSV → {out_path}  ({len(results)} lignes)")


def _bucket_stats(results: list[dict]) -> dict[str, dict]:
    buckets: dict[str, list] = {}
    for r in results:
        b = r["bucket"]
        buckets.setdefault(b, []).append(r)

    out = {}
    for bname, items in sorted(buckets.items()):
        n = len(items)
        undercrop = sum(1 for r in items if r["crop_class"] == "undercrop")
        overcrop = sum(1 for r in items if r["crop_class"] == "overcrop")
        wrong = sum(1 for r in items if r["crop_class"] == "wrong")
        ok = sum(1 for r in items if r["crop_class"] == "ok")
        fill_ratios = [r["fill_ratio"] for r in items]
        r_ratios = [r["r_ratio"] for r in items if r.get("r_ratio") is not None]
        bimetal_inner = sum(1 for r in items if r.get("bimetal_inner_ring"))
        out[bname] = {
            "n": n,
            "undercrop_pct": round(100 * undercrop / n, 1),
            "overcrop_pct": round(100 * overcrop / n, 1),
            "wrong_pct": round(100 * wrong / n, 1),
            "ok_pct": round(100 * ok / n, 1),
            "mean_fill_ratio": round(float(np.mean(fill_ratios)), 3),
            "bimetal_inner_ring_pct": round(100 * bimetal_inner / max(1, n), 1),
            "r_ratio_median": round(float(np.median(r_ratios)), 3) if r_ratios else None,
            "r_ratio_p25": round(float(np.percentile(r_ratios, 25)), 3) if r_ratios else None,
        }
    return out


def main() -> None:
    import time
    _OUT.mkdir(parents=True, exist_ok=True)

    print(f"=== Diagnostic qualité crops eBay ===")
    print(f"DB : {_DB}")
    print(f"Cache : {_CACHE}")
    print(f"Sortie : {_OUT}")
    print()

    assets = _select_assets(_MAX_SAMPLE)
    print(f"Assets sélectionnés (DB) : {len(assets)}")

    results = []
    errors = 0
    t0 = time.time()
    for i, row in enumerate(assets):
        r = _process_asset(row)
        if r is None:
            errors += 1
        else:
            results.append(r)
        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(assets)}] ok={len(results)} err={errors} "
                  f"({elapsed:.0f}s)")

    print(f"\nTraités : {len(results)} OK, {errors} ignorés (cache manquant)")

    # Statistiques globales
    n = len(results)
    if n == 0:
        print("AUCUN RÉSULTAT — arrêt")
        return

    classes = [r["crop_class"] for r in results]
    n_undercrop = classes.count("undercrop")
    n_overcrop = classes.count("overcrop")
    n_wrong = classes.count("wrong")
    n_ok = classes.count("ok")
    fill_ratios = [r["fill_ratio"] for r in results]
    bimetal_inner = sum(1 for r in results if r.get("bimetal_inner_ring"))

    print(f"\n=== RÉSULTATS GLOBAUX (n={n}) ===")
    print(f"  undercrop   : {n_undercrop:4d} ({100*n_undercrop/n:.1f}%)")
    print(f"  overcrop    : {n_overcrop:4d} ({100*n_overcrop/n:.1f}%)")
    print(f"  wrong       : {n_wrong:4d} ({100*n_wrong/n:.1f}%)")
    print(f"  ok          : {n_ok:4d} ({100*n_ok/n:.1f}%)")
    print(f"  fill_ratio  : mean={np.mean(fill_ratios):.3f}  "
          f"p25={np.percentile(fill_ratios,25):.3f}  "
          f"med={np.median(fill_ratios):.3f}  "
          f"p75={np.percentile(fill_ratios,75):.3f}")
    print(f"  bimetal_inner_ring détectés : {bimetal_inner} "
          f"({100*bimetal_inner/n:.1f}%)")

    print("\n=== PAR BUCKET ===")
    bstats = _bucket_stats(results)
    for bname, s in bstats.items():
        print(f"  {bname:25s}  n={s['n']:4d}  "
              f"under={s['undercrop_pct']:4.1f}%  "
              f"over={s['overcrop_pct']:4.1f}%  "
              f"wrong={s['wrong_pct']:4.1f}%  "
              f"fill={s['mean_fill_ratio']:.3f}  "
              f"bi_inner={s['bimetal_inner_ring_pct']:.1f}%"
              + (f"  r_med={s['r_ratio_median']:.3f}" if s.get('r_ratio_median') else ""))

    # Pires exemples pour audit
    worst = sorted(
        [r for r in results if r["crop_class"] in ("undercrop", "wrong")],
        key=lambda r: (r.get("r_ratio") or 1.0, r["fill_ratio"])
    )[:20]
    print("\n=== PIRES EXEMPLES (undercrop/wrong) ===")
    for r in worst:
        print(f"  {r['crop_class']:10s}  fill={r['fill_ratio']:.3f}  "
              f"rr={r.get('r_ratio') or 'n/a'}  "
              f"bi={r['bimetal_inner_ring']}  "
              f"{r['country']}-{r['year']}  "
              f"{r['asset_id'][:16]}")

    # Sorties
    _make_contact_sheet(results)
    _write_csv(results, _OUT / "results.csv")
    print("\nTerminé.")

    # Retourne les stats pour la sortie structurée
    return results, bstats


if __name__ == "__main__":
    main()
