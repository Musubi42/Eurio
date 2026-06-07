# Crop bimétal — sous-crop sur les 2 € (à reprendre)

> **Contexte** : découvert pendant la revue des items auto-accept (2026-05-24).
> Sur les pièces 2 €, le crop applique parfois un cercle interne qui ne garde
> que la partie dorée (l'intérieur), ou un cercle décentré / trop petit qui
> coupe la partie argentée (anneau extérieur). Les images source contiennent
> pourtant la pièce entière — c'est bien la pipeline crop qui sous-crop.

> **Statut** : observation, pas encore fixée. À reprendre dans une session
> dédiée crop / Hough.

---

## Signal observé

Page `/review/auto-accept` (chunk auto-accept déterministe livré 2026-05-24).
Sur ~107 items auto-acceptables, **plusieurs crops montrent uniquement le
disque central doré** — l'anneau argenté extérieur (signature bimétal 2 €)
est absent. Quelques cas montrent aussi un cercle de Hough décentré ou plus
petit que la pièce réelle.

Impact :
- L'image canonique stockée pour entraînement n'est pas la pièce entière → biais
  d'apprentissage (le modèle voit le motif central mais pas les étoiles du
  contour).
- Le scan terrain Android voit la pièce **entière**, donc divergence
  distribution train / inference.
- Le bench Dino reste correct (le motif central suffit souvent à identifier),
  ce qui masque le bug — mais il faut s'attendre à des faux négatifs sur des
  cas où la frontière bimétal porte du signal.

## Hypothèses sur la cause

À investiguer (ne pas implémenter sans vérification) :

1. **Hough rate l'anneau extérieur** — la transition métal doré → métal
   argenté crée un faux cercle plus discriminant que la silhouette pièce/fond,
   surtout sur photos contrastées. La pipeline pick le plus saillant.
   - Cf. `ml/scan/normalize_snap.py` § `detect_circles_multi`.
2. **YOLO bbox trop serrée** — le détecteur de listings (Phase listing-
   detection) cadre sur le centre brillant, le crop downstream hérite du biais.
3. **Filtre IoU au merge** privilégie la plus petite des deux détections
   quand YOLO et Hough divergent — il faudrait l'inverse pour les bimétaux.

## Données pour reproduire

- Database : `ml/state/eurio.db`
- Filtre proposé : `image_assets` où `eurio_id` correspond à une 2 €
  commémorative récemment auto-acceptée :

```sql
SELECT a.id, a.storage_path, a.bbox_json, rq.decided_eurio_id
  FROM image_assets a
  JOIN review_queue rq ON rq.image_asset_id = a.id
 WHERE rq.decided_by = 'auto_dino'
 ORDER BY rq.decided_at DESC
 LIMIT 30;
```

Visualiser le crop côté admin via `/review/auto-accept` (les vignettes
"CROP" à gauche de chaque card) — l'écart se voit à l'œil sur le sample
récent.

## Critères de fix

À considérer pour la session dédiée :

- [ ] La majorité des crops 2 € capture l'anneau argenté (mesurable : bbox
      réelle ≥ ~85 % de la silhouette détectée par re-seg).
- [ ] Pas de régression sur les 1 € / 50 cents / autres bimétaux ni sur les
      mono-métaux (1 cent, 5 cent…).
- [ ] Bench Dino stable ou en hausse — si le bench baisse après fix, c'est
      qu'on apprenait sur le mauvais signal (à reverter ou recalibrer).

## Liens

- Pipeline scan : `docs/research/detection-pipeline-unified.md`
- Code Hough multi : `ml/scan/normalize_snap.py`
- Pipeline listing detection : `project_listing_detection_pipeline.md`
  (memory ; livré 2026-05-04)

---

**Origine de la découverte** : revue manuelle des cards auto-accept
heuristique (chunk J1, session 2026-05-24). L'auto-accept a paradoxalement
servi de loupe sur un bug crop qu'on n'aurait pas vu en review one-by-one.
