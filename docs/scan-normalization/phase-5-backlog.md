# Phase 5 — Snap UX & input quality backlog

> Liste des améliorations identifiées après les Phases 0-4 (capture mode, normalize_snap, port Kotlin, validation Python ↔ Kotlin). Aucune n'est implémentée — chacune attend que les phases d'avant aient produit assez de données device pour qu'on puisse mesurer si elle est nécessaire.

## Status post Phase 4

- Photo mode device produit un input strictement aligné avec le training (Hough + tight crop + black mask + 224 INTER_AREA).
- Live ring vert/gris donne au user un signal real-time avant de snap.
- 4/4 pièces ACCEPTED en photo mode après le centroid fix + Phase 4 (top1 0.91-0.97 sur intérieur lumineux).
- 1 miss naturel observé sur eval_real_norm (`ad-2014/bright_textured`, margin 0.000) — cas limite du dataset, pas un bug pipeline.

Pas de raison d'ajouter de la complexité pipeline tant qu'on n'a pas mesuré, sur un dataset à 20+ classes, ce qui reste fragile. Les pistes ci-dessous sont gardées au chaud pour quand un signal d'échec aura été observé.

## Pistes (ordre de priorité ascendante de complexité)

### P1 — Auto AF/AE settle delay avant snap

**Symptôme à attraper** : snap pris pendant que l'autofocus ou l'autoexposure n'a pas convergé → image floue/mal exposée → cosine bas. Le user ressent ça comme "j'ai vu le ring vert mais le snap est pas net".

**Fix** : avant de capturer la frame de snap, déclencher `Camera2.Capture.AF_TRIGGER` + `AE_PRECAPTURE_TRIGGER`, attendre le state `CONTROL_AF_STATE_FOCUSED_LOCKED` ou un timeout (200-300 ms), puis snap. Le ring live actuel devrait déjà refléter une frame récente, donc le delay est court.

**Coût** : ~30 lignes Kotlin dans CameraX integration. Demande une callback CameraX qui n'est pas dans la version courante.

**Acceptance** : snaps sur surface texturée / lumière variable doivent passer de 50% nets à >90% nets.

### P2 — Sharpness gate (Laplacian variance)

**Symptôme à attraper** : snap accepté ArcFace mais flou — le top1 peut tomber bas (ou tomber sur la mauvaise classe si le flou rend la pièce ambiguë).

**Fix** : calculer la variance du Laplacien sur le crop normalisé 224 (côté Kotlin, OpenCV `Imgproc.Laplacian` + `Core.meanStdDev`). Seuil empirique typique pour des macro coins : variance > 100. En dessous → "snap flou, refais" via le UI failure card existant.

**Coût** : ~20 lignes dans `SnapNormalizer` (nouveau check post-resize) + un état UI "blurred".

**Acceptance** : seuil calibré sur les snaps device pulled — on prend le 5e percentile des "OK" snaps comme cutoff. Pas de gate s'il n'y a pas de signal d'échec sur device.

### P3 — Exposure gate (histogramme luminance)

**Symptôme à attraper** : snap sur/sous-exposé. Le mask noir cache déjà la BG mais la pièce elle-même peut être saturée (highlight cramé) ou dans le noir.

**Fix** : calculer l'histogramme sur le disque (mask appliqué). Reject si `> 5%` de pixels saturés à 255 ou `> 5%` à 0 (hors-disque). Optionnel : compter les pixels dans la fourchette [30, 230] et imposer ≥ 70%.

**Coût** : ~30 lignes Kotlin (histogramme sur masked Mat). Pas de runtime cost notable.

**Acceptance** : on regarde les snaps device qui ont un cos top1 < 0.8 après les autres fixes. Si beaucoup sont sur/sous-exposés → on calibre les seuils.

### P4 — Off-center orange ring (3 états)

**Symptôme à attraper** : aujourd'hui le ring est binaire (vert si Hough OK, gris sinon). Si Hough trouve un cercle mais hors centre, l'utilisateur n'a pas de feedback "tu y es presque".

**Fix** : remonter dans `SnapNormalizer.detectCircleOnly` un statut tri-state — `Centered` / `OffCenter` / `None`. La logique `_detect_coin_circle` pourrait retourner *tous* les candidats Hough, le caller décide. Orange = un cercle détecté mais hors `CENTER_TOL_FRACTION × short`.

**Coût** : ~20 lignes Kotlin + 1 nouvelle teinte d'overlay.

**Acceptance** : soft — c'est purement UX. À mesurer en utilisation réelle.

### P5 — Burst capture + best-frame selection

**Symptôme à attraper** : même avec AF/AE settle, une frame unique peut tomber sur un micro-jitter / léger flou. Le burst le mitige.

**Fix** : à snap, capturer 3 frames espacées de 50 ms, scorer chacune (Laplacian variance par exemple), garder la meilleure pour la pipeline. Si les 3 sont sous-seuil → reject.

**Coût** : ~80 lignes (CameraX burst + scoring). Latence snap +150 ms.

**Acceptance** : seulement si P1 + P2 ne suffisent pas — le burst est une assurance contre la variance frame-à-frame.

### P6 — Auto-snap (ready mode)

**Symptôme à attraper** : friction UX du "regarde ton screen, vise jusqu'à voir vert, tap snap". Sur grand volume (capture mode 24 snaps × 20 classes), le user est ralenti par la confirmation manuelle.

**Fix** : nouveau toggle "Auto-snap ON". Une fois ON, dès que le ring reste vert ≥ N=3 frames consécutives (~600 ms) ET sharpness OK (P2) ET exposure OK (P3), snap automatiquement.

**Coût** : ~40 lignes ViewModel (compteur de frames vertes consécutives) + bouton overlay.

**Acceptance** : utile si capture mode devient un goulot. Pas urgent tant qu'on est à 4-20 classes manuellement.

## Anti-pistes (pourquoi certaines idées NE seront pas faites)

- **Test sans masque** (mentionné en discussion initiale) : abandonné. Le training est déjà aligné sur black mask. Pour tester sans mask il faudrait re-train sans, ce qui casse l'invariant "train et inference partagent normalize_snap". Pas de gain attendu.
- **Detection multi-coin** : abandonné. La feedback `Scan = QR scanner = une pièce à la fois` (memory) est durable. Hough déjà filtre largest centered = exactement l'invariant souhaité.
- **Background augmentation** : virée en Phase 2 (recipes vidées), ne pas la ré-introduire. Le mask noir empêche qu'elle fournisse un signal cohérent.

## Ordre d'attaque suggéré (quand on déclenchera Phase 5)

1. **Mesurer d'abord** : avec ≥ 20 classes entraînées, faire une capture mode complète, eval_real_snaps, et regarder les snaps misclassified ou à top1 < 0.85.
2. **Diagnostiquer ce qui leur manque** : si flous → P2. Si sur/sous-exposés → P3. Si AF lent au reset → P1. Si user râle UX → P4 ou P6.
3. **Implémenter au cas par cas**, jamais le bundle complet d'un coup.

Le principe : zéro complexité prophylactique. Chaque piste justifie sa présence par un signal mesuré.
