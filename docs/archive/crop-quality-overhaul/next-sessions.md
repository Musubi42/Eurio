# Crop-quality-overhaul — prompts des sessions suivantes

Deux sessions distinctes, à lancer séparément. Le chantier algo (crop eBay) est
fait (~92 % bon via `detect_bbox_refine`). Le reste se gère **par l'humain** :
améliorer le scan Android (train↔inference) + outils de review manuelle pour le tail.

Contexte commun : `docs/operations/crop-quality-overhaul/00-diagnostic-and-architecture.md`.

---

## Session A — Améliorer le crop du scan Android (train ↔ inference)

```
Améliore la qualité du crop du SCAN ANDROID (le scan live de l'app). Mode de
travail : test MANUEL via l'écran debug /dev/photo, pas de bench automatisé.

POURQUOI (le vrai enjeu = drift train↔inference) :
On vient de corriger le crop des images d'ENTRAÎNEMENT eBay (chantier
crop-quality-overhaul). Le détecteur ml/scan/crop_detectors.py::detect_bbox_refine
corrige l'undercrop bimétal — Hough accroche l'anneau interne or↔argent au lieu
du rim externe — et le parc eBay est passé de 79.9 % → 91.7 % de crops corrects.
MAIS ce fix est listing-only (chemin normalize_listing). Le scan Android live
utilise un chemin SÉPARÉ, normalize_device (cascade Hough), porté bit-for-bit
dans app-android/src/main/java/com/musubi/eurio/ml/SnapNormalizer.kt, et il a
EXACTEMENT le même bug bimétal (documenté ml/scan/normalize_snap.py:122, ~36 %).
=> Les crops d'entraînement capturent désormais le rim externe complet ; si le
scan device croppe l'anneau interne, ArcFace voit deux distributions → reco
dégradée. Objectif : le scan device doit produire LE MÊME crop (la pièce entière).

À LIRE d'abord :
- docs/operations/crop-quality-overhaul/00-diagnostic-and-architecture.md
  (l'archi, bbox_refine, et l'impasse "rim-gradient" à NE PAS refaire)
- ml/scan/normalize_snap.py : normalize_device, _detect_circle_hough, commentaire :122
- ml/scan/crop_detectors.py : detect_bbox_refine (la logique outer-rim validée :
  ROI bornée autour du hint, plancher r≥0.9·hint, plafond r≤2.6·hint)
- app-android/.../ml/SnapNormalizer.kt (port Kotlin du device path, parité ε=2px)
- app-android/.../features/dev/photo/{PhotoScreen,PhotoSnapResultLayer,PhotoViewModel}.kt
  (le HARNESS de test manuel : snap → affiche le crop généré par l'app)
- parité : go-task ml:scan:diff, go-task ml:scan:bench-normalize, tests/test_normalize_dispatch.py

CONTRAINTES (lire CLAUDE.md) :
- R0 zéro dette ; discuter avant si la solution propre n'est pas claire.
- Parité web↔android = même RÉSULTAT (technique libre). Si tu touches
  normalize_device, mets SnapNormalizer.kt à jour symétriquement et fais passer
  le gate de parité — ou justifie explicitement une divergence contrôlée.
- Le rim-refine doit rester tractable on-device (minSdk 26, OpenCV Android dispo ;
  pas de SAM/gros modèle).
- /dev/photo est un outil debug (exempt de proto-first R1). Mais toute UX scan
  PRODUIT-facing nouvelle doit d'abord exister dans le proto HTML.
- go-task pour build/install (android:run, android:logs). Pas d'édition manuelle
  de Color.kt/Shape.kt/Spacing.kt.

DÉMARCHE (chunk par chunk, audit screenshot entre chaque, attendre mon "go") :
1. Reproduire le bug sur device : /dev/photo, snap d'une 2€ bimétal → confirmer
   l'undercrop (anneau interne). Me montrer le crop actuel.
2. Porter la sélection outer-rim de detect_bbox_refine dans le device path
   (contour-fitEllipse / sélecteur, ROI bornée autour du Hough), côté Kotlin +
   Python normalize_device en parité.
3. Itération manuelle : je fournis des screenshots /dev/photo avec les conditions
   (angle, fond, lumière, capsule…), on corrige au cas par cas.

PREMIÈRE ACTION : lis les fichiers, build+install (go-task android:run), ouvre
/dev/photo, et PROPOSE un plan en chunks AVANT de coder. Je te fournirai des
photos de ~15 pièces dans des conditions variées pour tester.
```

---

## Session B — Review crop manuelle : trash + re-crop manuel (le tail ~2 %)

```
Ajoute, dans la section REVIEW de l'admin, les outils humains pour traiter le
tail des crops imprécis : jeter le déchet, et re-cropper à la main les vraies
pièces mal cadrées.

CONTEXTE :
Chantier crop-quality-overhaul (docs/operations/crop-quality-overhaul/00-*.md).
Le crop auto eBay est ~92 % bon (detect_bbox_refine). Il reste ~8 % d'imprécis :
la plupart = DÉCHET (pas une pièce : certificats, coincards, photos illisibles)
à exclure du training ; un petit ~2 % = vraies pièces mal cropées à SAUVER via
un re-crop manuel léger. La review attribue déjà "ce crop appartient à telle
pièce (eurio_id) + valeur" ; on AJOUTE deux capacités à ce flow.

OBJECTIF :
1. TRASH / exclure : marquer un asset "pas une pièce" ou "trop mauvaise qualité"
   → exclu du training (image_assets.training_eligible=0 + quality_reason).
2. RE-CROP MANUEL : éditeur de cercle sur le raw — dessiner / déplacer /
   agrandir / rétrécir un cercle, preview live du crop 224, valider → régénère
   le crop avec le MÊME format que la prod (CropConfig: marge 0.02, masque hard,
   224) et écrase le crop de l'asset (cache local + MinIO + DB), eurio_id préservé.

À LIRE d'abord :
- docs/operations/crop-quality-overhaul/00-diagnostic-and-architecture.md
- admin/packages/web/src/features/review/ (pages + composables ; ReviewPage.vue, useReviewApi.ts)
- ml/review/review_queue_routes.py (endpoints decide/reject/correct-listing/skip — où brancher)
- ml/serving/crop_bench_routes.py (PRÉCÉDENT direct : sert raw/crop, recrop via
  crop_with_detector, écrit le crop — réutiliser le pattern)
- ml/scan/normalize_snap.py::_crop_mask_resize_float (LE format de crop à
  réutiliser : (cx,cy,r) natifs → 224 masqué — NE PAS réinventer)
- ml/scripts/recrop_ebay_refine.py (pattern d'écriture : cache local +
  upload_through MinIO + UPDATE image_assets bbox_json/detection_method/width/
  height/phash, eurio_id PRÉSERVÉ)

CONTRAINTES (lire CLAUDE.md) :
- R0 zéro dette. SQLite-only (eurio.db = source de vérité).
- Admin Vue exempté de proto-first (design direct + tokens.css partagé,
  skill frontend-design dispo).
- Le crop manuel DOIT produire exactement le même format que l'auto (réutiliser
  _crop_mask_resize_float) → cohérence training. detection_method = "manual".
- Images servies via /sources/{source}/raws|assets/{id}/file (cache local) ;
  ML_API = http://127.0.0.1:8042.

DÉMARCHE (chunk par chunk, audit entre chaque) :
1. Backend : POST .../manual-crop {asset_id, cx, cy, r (en px natifs du raw)} →
   recrop via _crop_mask_resize_float, écrit cache+MinIO+DB (calque
   recrop_ebay_refine), renvoie le nouveau crop. + POST .../trash {asset_id,
   reason} → training_eligible=0 + quality_reason.
2. Front : dans le flow review, sur un asset → bouton "crop manuel" ouvrant un
   éditeur de cercle sur le raw (drag du centre, poignée/molette = rayon),
   preview live du 224, valider. + bouton "trash" avec raison.
3. Chunk par chunk, audit visuel entre chaque, attendre mon "go".

PREMIÈRE ACTION : lis, puis PROPOSE le plan en chunks + le design de l'éditeur
de cercle (interaction + rendu) AVANT de coder.
```

---

### Notes de cadrage (décisions bakées — à corriger si besoin)
- **Session A** est fondamentalement un travail Kotlin/Android (le crop device est on-device). La motivation = cohérence train↔inference, pas l'esthétique. Test 100 % manuel via /dev/photo.
- **Session B** vit dans `features/review` (le flow qui attribue crop→pièce), pas dans le crop-bench. Trois actions sur un asset : attribuer (existe) · re-crop manuel (nouveau) · trash (nouveau).
- Les deux réutilisent le **format de crop de prod** (`_crop_mask_resize_float`) pour ne pas réintroduire de drift.
