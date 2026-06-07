"""Calcule un score `is_coin` purement géométrique (OpenCV) pour chaque
image_asset d'un run, et persiste un sidecar JSON pour inspection
ultérieure via sampler.

Approche A de docs/crop-forensics/findings/02-sota-research.md :
- Pour chaque crop 224×224, on traite le crop COMME un disque centré
  (les normalize_listing l'ont déjà centré, rim ≈ aux bords avec margin
  de 2%).
- 3 signaux :
    rim_peak       : gradient radial max moyenné sur l'anneau aux bords.
                      Élevé = vrai rim métallique. Bas = bord flou / pas
                      de pièce.
    rim_continuity : variance angulaire du peak (256 angles). Faible =
                      uniforme sur 360°. Forte = peak ponctuel suspect.
    disc_metalness : ratio pixels HSV avec saturation < 50 et value
                      40-230 (gris / argent / or / cuivre) DANS le disque.
- composite = rim_peak * (1 - rim_continuity_normed) * disc_metalness
  Score haut = vraie pièce centrée. Score bas = false positive.

Sidecar : `ml/state/crop_scores/{run_id}.json` (liste de records par
asset_id, à charger côté sampler pour tri).

Usage::

    cd ml
    python -m scripts.crop_exp.score_crops --run-id <id>
    python -m scripts.crop_exp.score_crops --run-id <id> --limit 100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

_ML_DIR = Path(__file__).resolve().parents[2]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from store import Store
from shared.storage.local_cache import local_path


def _disc_mask(size: int, r_inner: int, r_outer: int) -> np.ndarray:
    """Anneau binaire entre r_inner et r_outer pixels."""
    cy = cx = size // 2
    yy, xx = np.ogrid[:size, :size]
    d2 = (yy - cy) ** 2 + (xx - cx) ** 2
    return ((d2 >= r_inner * r_inner) & (d2 < r_outer * r_outer)).astype(np.uint8)


def score_one(crop_bgr: np.ndarray) -> dict[str, float]:
    """Calcule les 3 signaux + composite pour un crop carré (typiquement
    224×224 mais marche sur n'importe quel carré centré)."""
    h, w = crop_bgr.shape[:2]
    if h != w or h < 64:
        return {"rim_peak": 0.0, "rim_continuity": 1.0,
                "disc_metalness": 0.0, "composite": 0.0, "ok": False}

    size = h
    r_nominal = size // 2  # bord, là où le rim DEVRAIT être

    # ── Signal 1 : rim_peak ──────────────────────────────────────────────
    # Passe en polaire centré, calcule la moyenne de l'amplitude du gradient
    # radial sur la bande "près du bord".
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # warpPolar : sortie (rho, theta). On veut un échantillonnage régulier.
    n_rho = size // 2
    n_theta = 256
    polar = cv2.warpPolar(
        gray, (n_rho, n_theta),
        (size / 2, size / 2), r_nominal,
        cv2.WARP_POLAR_LINEAR + cv2.INTER_LINEAR,
    )
    # Gradient radial : différence sur l'axe rho (axe 1).
    grad_rho = np.abs(np.diff(polar, axis=1))  # shape (n_theta, n_rho-1)
    # Zone "rim attendu" : 85-100% du rayon.
    lo, hi = int(0.85 * (n_rho - 1)), n_rho - 1
    rim_band = grad_rho[:, lo:hi]                # (n_theta, rim_width)
    rim_per_angle = rim_band.max(axis=1)         # peak par angle
    rim_peak = float(rim_per_angle.mean())       # peak moyen sur 360°

    # ── Signal 2 : rim_continuity ─────────────────────────────────────────
    # Variance des peaks par angle, normalisée par la moyenne. 0 = parfait
    # rim continu ; > 1 = très ponctué.
    if rim_per_angle.mean() > 0:
        rim_continuity = float(rim_per_angle.std() / rim_per_angle.mean())
    else:
        rim_continuity = 2.0

    # ── Signal 3 : disc_metalness (corrigé v2 — tolère l'or saturé) ──────
    # On accepte les pixels :
    #   - gris/argent : S < 60 ET 40 < V < 235
    #   - or/cuivre   : H ∈ [10, 35] (jaune-orange) ET S > 60 ET 50 < V < 230
    # Couvre tous les types de pièces euro réelles.
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    silver = (S < 60) & (V > 40) & (V < 235)
    gold = (H >= 10) & (H <= 35) & (S > 60) & (V > 50) & (V < 230)
    metal_mask = (silver | gold).astype(np.uint8)
    inner_mask = _disc_mask(size, 0, int(0.85 * r_nominal))
    total = int(inner_mask.sum())
    metal_in_disc = int((metal_mask * inner_mask).sum())
    disc_metalness = metal_in_disc / total if total > 0 else 0.0

    # ── Composite (additif normalisé — évite le zero-trap multiplicatif) ─
    # Normalise rim_peak à [0,1] via /80 clamped. Empirique : p90 ≈ 80.
    rim_peak_n = min(rim_peak / 80.0, 1.0)
    # cont_penalty : 1 - clamp(continuity / 1.5, 0, 1). 1 = rim parfaitement
    # continu sur 360°.
    cont_penalty = max(0.0, 1.0 - min(rim_continuity / 1.5, 1.0))
    # Composite additif avec poids — somme attendue ≤ 1.
    # Priorité : continuity (un rim 360° = très distinctif) > rim_peak >
    # metalness (un signal couleur juste pour pénaliser les non-pièces).
    composite = float(0.45 * cont_penalty + 0.35 * rim_peak_n
                       + 0.20 * disc_metalness)

    return {
        "rim_peak": rim_peak,
        "rim_continuity": rim_continuity,
        "disc_metalness": disc_metalness,
        "composite": composite,
        "ok": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--limit", type=int, default=None, help="debug : process max N")
    ap.add_argument("--output", default=None,
                    help="sidecar JSON path (default: ml/state/crop_scores/<run>.json)")
    args = ap.parse_args()

    store = Store(_ML_DIR / "state" / "eurio.db")
    conn = store._connection()

    rows = conn.execute(
        """
        SELECT a.id AS asset_id, a.storage_path AS storage_path,
               a.detection_method AS method, a.crop_index AS crop_index,
               s.listing_country AS country, s.listing_year AS year
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.run_id = ?
         ORDER BY a.fetched_at DESC
        """,
        (args.run_id,),
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    out_path = Path(args.output) if args.output else (
        _ML_DIR / "state" / "crop_scores" / f"{args.run_id}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[score_crops] run={args.run_id} processing {len(rows)} crops…")
    records: list[dict] = []
    n_err = 0
    for i, r in enumerate(rows, 1):
        try:
            p = local_path("enrichment-crops", r["storage_path"])
            crop = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if crop is None:
                n_err += 1
                continue
            signals = score_one(crop)
            records.append({
                "asset_id": r["asset_id"],
                "method": r["method"],
                "crop_index": r["crop_index"],
                "country": r["country"],
                "year": r["year"],
                **signals,
            })
        except Exception as exc:  # noqa: BLE001
            n_err += 1
            if n_err < 5:
                print(f"  ! err on {r['asset_id'][:8]} : {exc}")
        if i % 200 == 0 or i == len(rows):
            print(f"  [{i}/{len(rows)}] (errs={n_err})")

    out_path.write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(f"[score_crops] wrote {len(records)} records to {out_path}")

    # Stats rapides.
    if records:
        composites = sorted(r["composite"] for r in records)
        n = len(composites)
        print(f"  composite distribution : "
              f"min={composites[0]:.3f}  "
              f"p10={composites[n//10]:.3f}  "
              f"median={composites[n//2]:.3f}  "
              f"p90={composites[(9*n)//10]:.3f}  "
              f"max={composites[-1]:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
