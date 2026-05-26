# Contexte — d'où on part

## Le pipeline de crop actuel

Fichier source : `ml/scan/normalize_snap.py`.

```
raw eBay (JPEG arbitraire)
    │
    ▼
detect_circles_multi(bgr)         ← YOLO11-nano → bboxes
    │
    ▼ (pour chaque bbox)
hough_refine_in_roi(roi)          ← Hough strict→loose dans la bbox
    │
    │   si fail → fallback "yolo+bbox" (centre = milieu bbox, r = min(w,h)/2)
    ▼
radial_gradient_polish(cx,cy,r)   ← optim ±radius ±2px pour max gradient
    │
    │   si polish améliore le score > 1.05 → method = "<base>+polish"
    ▼
_crop_mask_resize_int(bgr, cx, cy, r)
    │   crop = bgr[cy-r-margin : cy+r+margin, cx-r-margin : cx+r+margin]
    │   margin = 2 % de r par défaut (CropConfig)
    │   square snap : side = min(w, h) après clamp aux bords
    │   apply edge mask (hard / feathered / none)
    │   resize 224×224 INTER_AREA
    ▼
NormalizationResult(image=BGR 224×224, cx, cy, r, method)
```

Méthodes produites dans le run `059dc8d9` (2026-05-26, 12 recherches eBay,
1 678 crops) :

| Méthode             | Crops | Part |
|---------------------|-------|------|
| `yolo+hough`        | 1 233 | 73 % |
| `yolo+hough+polish` |   427 | 25 % |
| `yolo+bbox+polish`  |    16 |  1 % |
| `yolo+bbox`         |     2 | <1 % |

## Ce qu'on a livré sur le forensics

3 chunks committés sur branche `coin-richness/p3-schema` :

- **Chunk 1** `99e54dc` — backend : endpoint `GET /bench/runs/{id}/crops`
  avec aggregats + diagnostic auto. Fix producer `detect_crop.py` pour
  persister `bbox_json` (était oublié). Script `backfill_bbox_from_normalize.py`
  (re-run normalize déterministe, UPDATE bbox sur l'existant). Backfill
  fait sur les 1 678 crops du run.
- **Chunk 2** `b21190a` — frontend : toggle Filter/Crop dans le header,
  composants `BenchCropAnalytics`, `BenchCropEvidenceCard`, panel
  orchestrateur `BenchRunAuditCropPanel`.
- **Chunk 3** `7902c17` — UX/CSS : fix bbox alignment (inner-frame avec
  aspect-ratio du raw), pattern "masque CV pro" (4 darkenings autour de
  la bbox), layout filter-like (pas de sélection par défaut, recherches
  toujours visibles, detail panel scrollable via sticky analytics).

## Données + outils disponibles

- DB SQLite : `ml/state/eurio.db`
- Table clé : `image_assets` (1 678 rows pour le run) avec `bbox_json`,
  `detection_method`, `storage_path`, `width`, `height`, `phash`.
- Table source : `source_images` (795 raws pour le run) avec
  `storage_path`, `width`, `height`, `listing_title`, `listing_country`,
  `listing_year`.
- Buckets MinIO : `enrichment-raws`, `enrichment-crops` (read via
  `storage.local_cache.local_path`).
- API : `http://localhost:8042/bench/runs/{run_id}/crops?...`
- Vue : `http://localhost:5173/bench/runs/{run_id}#crop`

## Code Python clé

- `ml/scan/normalize_snap.py:794` — `normalize_listing(bgr)` (entry)
- `ml/scan/normalize_snap.py:710` — `detect_circles_multi(bgr)` (YOLO+Hough)
- `ml/scan/normalize_snap.py:645` — `_radial_gradient_polish` (post-fit)
- `ml/scan/normalize_snap.py:242` — `_crop_mask_resize_int` (crop final)
- `ml/sources/_base/steps/detect_crop.py:187` — orchestrateur batch
