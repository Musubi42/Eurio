# Algorithms — Studio Pipeline & Device Pipeline

> Spec des deux normalizers. Le contrat ε qui les lie est dans [`parity-contract.md`](parity-contract.md). Le pourquoi est dans [`VISION.md`](VISION.md).

## Working resolution unifié

Les deux pipelines exécutent leur **détection de cercle** à `working_res = 1024` (long-side). C'est la résolution `wr_1024_tightR` validée par le bench pré-rework (cf. [`bench-results-pre.md`](bench-results-pre.md)).

```python
WORKING_RES = 1024  # long-side, both pipelines
```

**Pourquoi unifié** :
- Comportement morphologique prévisible (kernel `k = max(3, short // 200) | 1` → `k=5` à 1024, contre `k=15` à 3000 px).
- Hough côté studio évite les hangs content-dependent (la cause du rework).
- Hough côté device évite le hang sur des snaps haute-res si la Phase F (ImageCapture full-res) est activée.
- Les paramètres morpho/Hough sont calibrables une seule fois.

**Détection à 1024 → crop à la résolution native** : la détection retourne `(cx, cy, r)` à l'échelle 1024, qu'on remonte à l'échelle native via le facteur `scale = native_short / 1024` avant d'appliquer `_crop_mask_resize`. Le 224 final est un downsample `INTER_AREA` depuis l'image native — on ne perd aucune info à passer par 1024 pour la *détection*.

## Pipeline studio (training)

**Contexte** : sources Numista scannées, BG quasi-uniforme (blanc/gris clair), coin centré, qualité élevée, taille 1500–3000 px native.

**Pipeline** :

1. Downscale à `working_res=1024` (long-side, `cv2.INTER_AREA`).
2. `cv2.cvtColor(BGR2GRAY)` — gris.
3. **Check polarité** : sample des 4 coins du gris. Si `mean(corners) < threshold_otsu` → BG est plus sombre que le coin (cas atypique : pièce claire sur BG médium), inverser le flag `THRESH_BINARY_INV` → `THRESH_BINARY`. Sinon (cas normal Numista : coin sombre sur BG clair) → `THRESH_BINARY_INV`.
4. `cv2.threshold(gray, 0, 255, FLAG | THRESH_OTSU)` — binarisation.
5. `cv2.morphologyEx(MORPH_CLOSE)` puis `MORPH_OPEN` — fermer les trous fins (relief, gravure intérieure), virer le bruit isolé. Kernel `k=5` à 1024.
6. `cv2.findContours(RETR_EXTERNAL, CHAIN_APPROX_NONE)` → contours candidats.
7. **Sélection du plus gros contour centré** : centroïde dans un cercle de rayon `0.30 * short` autour du centre image (même règle que Hough).
8. **Garde-fou bimétal/anneau** : si le contour sélectionné a un trou intérieur significatif (vérifié via `RETR_CCOMP` second pass ou via `contourArea / minEnclosingCircleArea < 0.7`), c'est probablement un anneau (Otsu a séparé centre argent/anneau or au lieu de coin/BG). Fallback.
9. `cv2.minEnclosingCircle(contour)` → `(cx, cy, r)` en sub-pixel float, à l'échelle 1024.
10. Remonter `(cx, cy, r) *= scale` à l'échelle native.
11. `_crop_mask_resize(bgr_native, cx, cy, r, method="contour")` — sub-pixel propagé.

**Pseudo-code** (à raffiner en implémentation) :

```python
WORKING_RES = 1024

def normalize_studio(bgr: np.ndarray) -> NormalizationResult:
    h0, w0 = bgr.shape[:2]
    short0 = min(h0, w0)
    scale = max(h0, w0) / WORKING_RES if max(h0, w0) > WORKING_RES else 1.0
    if scale > 1.0:
        new_w, new_h = int(w0 / scale), int(h0 / scale)
        work = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    else:
        work = bgr
    h, w = work.shape[:2]
    short = min(h, w)

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

    # Polarité Otsu : BG clair (Numista normal) → INV ; BG sombre → direct.
    corners = np.array([gray[0,0], gray[0,-1], gray[-1,0], gray[-1,-1]])
    otsu_thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    flag = cv2.THRESH_BINARY_INV if corners.mean() > otsu_thr else cv2.THRESH_BINARY
    _, mask = cv2.threshold(gray, 0, 255, flag | cv2.THRESH_OTSU)

    k = max(3, short // 200) | 1  # ≈5 à 1024
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  np.ones((k, k), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return _fallback_to_device(bgr)

    img_cx, img_cy = w / 2.0, h / 2.0
    tol_sq = (0.30 * short) ** 2
    centered = []
    for c in contours:
        M = cv2.moments(c)
        if M["m00"] == 0: continue
        ccx, ccy = M["m10"]/M["m00"], M["m01"]/M["m00"]
        if (ccx - img_cx)**2 + (ccy - img_cy)**2 <= tol_sq:
            centered.append((cv2.contourArea(c), c))
    if not centered:
        return _fallback_to_device(bgr)

    _, best = max(centered, key=lambda x: x[0])
    (cx, cy), r = cv2.minEnclosingCircle(best)

    # Garde-fou bimétal : si le contour ne remplit pas suffisamment son cercle
    # englobant, c'est probablement un anneau → fallback.
    fill_ratio = cv2.contourArea(best) / max(1.0, np.pi * r * r)
    if fill_ratio < 0.7:
        return _fallback_to_device(bgr)

    # Remonter à l'échelle native, sub-pixel préservé.
    cx_n, cy_n, r_n = cx * scale, cy * scale, r * scale
    return _crop_mask_resize(bgr, cx_n, cy_n, r_n, method="contour")
```

**Caractéristiques attendues** (à valider Phase A) :
- Coût : **~10–30 ms/image**, indépendant de la taille native.
- Précision : sub-pixel sur `(cx, cy, r)` propagée jusqu'au crop.
- Déterminisme : 100%.
- Taux de fallback : **≤ 2%** sur le `parity_dataset.yaml`.

**Cas pièges** (déjà testés ou à tester en Phase A) :

| Cas | Mécanisme | Gestion |
|---|---|---|
| Bimétal 2 EUR | Otsu peut séparer centre/anneau au lieu de coin/BG → contour = anneau, trou intérieur | Garde-fou `fill_ratio < 0.7` → fallback |
| Coin clair sur BG médium/sombre | Otsu inversé | Check polarité (corners) |
| Ombre dure du coin sur le BG | L'ombre devient foreground, déforme `minEnclosingCircle` | À mesurer Phase A. Atténuable par `MORPH_OPEN` plus large ou seuil adaptatif. Sinon fallback. |
| Multiples objets dans le frame | "Plus gros contour centré" filtre les petits parasites | Si parasite gros et centré → fallback |
| Coin quasi-pleine-image | Otsu peut binariser tout en foreground | Garde-fou `largest_area / image_area > 0.85` → fallback |

**Fallback** : si la sélection contour échoue, retomber sur `normalize_device(bgr)`. Le fallback est trace-loggé (`debug={"fallback_reason": "..."}`) pour qu'on identifie les images problématiques. Phase A doit valider que le taux de fallback sur `parity_dataset.yaml` est ≤ 2% — au-dessus, l'algo studio n'est pas mature et la Phase C est bloquée.

## Pipeline device (Android + Python miroir)

**Contexte** : frames `ImageAnalysis` (~1280×720 aujourd'hui, potentiellement haute-res si Phase F activée), BG variable, exposition fluctuante, blur de mouvement, capture en main avec ring guide.

**Pipeline** :

1. Downscale à `working_res=1024` (long-side). À 720p le cas est trivial (déjà sous 1024) ; à 4K (Phase F) ça ramène au cas mesuré.
2. `cv2.cvtColor(BGR2GRAY) + medianBlur(5)` (inchangé vs prod actuelle).
3. **Hough cascade tight → relaxed** :
   - tight : `param1=100, param2=30, rmin=0.35*short, rmax=0.55*short` (variante `wr_1024_tightR` du bench).
   - relaxed (fallback) : `param1=60, param2=22, rmin=0.10*short, rmax=0.55*short`.
4. **Sélection** : drop circles dont le centre est > 30% de short loin du centre image, puis pick le plus grand rayon. Règle "largest centered" critique pour bimétal (Hough vote l'anneau intérieur plus haut que le bord extérieur sur les 2 EUR).
5. Remonter `(cx, cy, r) *= scale` à l'échelle native.
6. `_crop_mask_resize(bgr_native, cx, cy, r, method="hough_*")`.

**Coût mesuré (bench pré-rework, `wr_1024_tightR`)** : médiane 600 ms à 7 s selon image, dominée par les sources studio à 1700+ px. Sur frame 720p natif (cas device live), le cas mesuré est **50–150 ms/snap**.

**Différence vs `normalize` actuel** : la prod actuelle (`normalize_snap.py`) appelle Hough sur la résolution native sans downscale, et utilise un range radius plus large `0.15–0.55`. Le rework resserre à `0.35–0.55` (tight) et ajoute le downscale 1024. Le port Kotlin (`SnapNormalizer.kt`) doit suivre — c'est un de-facto algo change qui doit être testé via #2 cross-platform.

**Pourquoi pas le même algo studio sur device** : Otsu sur frame caméra avec BG noisy (table, main, ombres, reflets) sépare mal le coin du fond. Le contour résultant n'est rarement le coin et `minEnclosingCircle` retourne du bruit. Hough est plus robuste à un BG variable parce qu'il vote sur la *forme* (cercle), pas sur la *séparation foreground/background*.

**Pourquoi pas l'algo device sur studio** : Hough sur sources studio à 3000 px coûte 3+ min/image, content-dependent. C'est l'objet de cette refonte.

## Logique commune `_crop_mask_resize`

Inchangée par rapport à la prod actuelle (`normalize_snap.py:_crop_mask_resize`), à un détail près : accepte `(cx, cy, r)` en **float** (sub-pixel), fait l'arithmétique des bounds en float, et ne round qu'au moment du slicing entier final. Cela préserve la précision sub-pixel apportée par `minEnclosingCircle` côté studio.

```python
def _crop_mask_resize(bgr, cx: float, cy: float, r: float, method: str) -> NormalizationResult:
    h, w = bgr.shape[:2]
    margin = r * COIN_MARGIN
    half = r + margin
    x0_f, y0_f = max(0.0, cx - half), max(0.0, cy - half)
    x1_f, y1_f = min(float(w), cx + half), min(float(h), cy + half)
    side_f = min(x1_f - x0_f, y1_f - y0_f)
    x1_f, y1_f = x0_f + side_f, y0_f + side_f
    x0, y0, x1, y1 = int(round(x0_f)), int(round(y0_f)), int(round(x1_f)), int(round(y1_f))
    crop = bgr[y0:y1, x0:x1].copy()
    crop_cx = int(round(cx - x0_f))
    crop_cy = int(round(cy - y0_f))
    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    cv2.circle(mask, (crop_cx, crop_cy), int(round(r)), 255, -1)
    bg = np.full_like(crop, BG_COLOR, dtype=np.uint8)
    crop = np.where(mask[..., None].astype(bool), crop, bg)
    out = cv2.resize(crop, (OUTPUT_SIZE, OUTPUT_SIZE), interpolation=cv2.INTER_AREA)
    return NormalizationResult(image=out, cx=int(round(cx)), cy=int(round(cy)),
                               r=int(round(r)), method=method, ...)
```

## Le cas Android `SnapNormalizer.kt`

**Doit changer pour le rework** : ajout du downscale `working_res=1024` et du tight radius `0.35–0.55` en pass principal. Le pass relaxed reste comme fallback. La logique de sélection ("largest centered") est inchangée. Le test #2 cross-platform doit rester ε_pf ≈ 0–1/255 après le port.

`detectCircleOnly` (utilisé par le ring vert/gris à 5 fps) reçoit déjà des bitmaps preview ~720p donc le downscale 1024 est un no-op pour ce path — mais le code partagé doit être identique pour que le ring suive le même algo que le snap final.

## Constantes partagées (figées par le contrat ArcFace)

```python
OUTPUT_SIZE = 224
COIN_MARGIN = 0.02
BG_COLOR    = (0, 0, 0)
WORKING_RES = 1024
```

`OUTPUT_SIZE`, `COIN_MARGIN`, `BG_COLOR` sont **immuables** sans rejouer un cycle complet de validation ArcFace (cf. VISION.md, section "Ce qui ne change PAS"). `WORKING_RES` est partagé par convention pour aligner les comportements des deux algos ; un changement de `WORKING_RES` impose de re-bench (Phase A) et re-mesurer ε (Phase B).

## Mapping fichiers → rôles

| Fichier | Rôle après refonte |
|---|---|
| `ml/scan/normalize_snap.py` | dispatcher : expose `normalize_studio()` et `normalize_device()`, garde la logique commune `_crop_mask_resize` et la constante `WORKING_RES` |
| `ml/training/prepare_dataset.py` | utilise **`normalize_studio()`** |
| `ml/scan/sync_eval_real.py` | utilise **`normalize_device()`** (rename pur — c'est l'algo Hough actuel optimisé `wr_1024_tightR`, donc `eval_real_norm/` existant reste valide après ce rename, **pas de re-capture nécessaire**) |
| `app-android/.../SnapNormalizer.kt` | port de l'algo `normalize_device` post-rework (downscale 1024 + tight radius), validé par le test cross-platform |
