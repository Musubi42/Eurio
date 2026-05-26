# Vision — Crop forensics

## But

Réduire le taux de **mauvais crops** produits par
`ml/scan/normalize_snap.py` sur les listings eBay réels du run V.3
(`059dc8d9`, 1 678 image_assets). "Mauvais" = un humain (Raphaël) regarde
la sortie du bench `/bench/runs/{id}/crops#crop` et juge que ça ne
correspond pas à la pièce attendue.

## Catégories d'erreur (cf. findings/01)

- **A — faux positif non-pièce** : Hough vote sur un timbre, un logo,
  une bande numérique "1234567890", un sticker.
- **B — inner feature** : Hough vote un cercle INTÉRIEUR sur un macro
  shot (le "10" gravé, l'œil d'un portrait). C'est le bug bimétal
  généralisé.
- **C — multi-pièce album** : un album N pièces génère N crops valides,
  mais on ne sait pas laquelle map au listing target.
- **D — OK** : crop centré sur la bonne pièce, rim visible.

**Scope crop forensics** : on attaque **A et B**. **C est hors scope** —
c'est une question de routing (`review_lot` est déjà géré par le pipeline
filter, pas par le détecteur).

## Critères de succès

Le chantier est gagné quand **sur le bench `/bench/runs/{id}/crops`** :

- Le **tri par défaut** met les cas A et B en bas (au moins 70 % des
  bottom-30 sont A+B), pour que Raphaël les attaque en review en
  priorité.
- Le **flag visuel** (badge rouge / surlignement) sur la card identifie
  ≥ 70 % des cas A+B sans flagger > 20 % des cas D (faux positifs UI).
- Sans toucher au pipeline producer (YOLO+Hough+polish reste intact).

## Contraintes dures

- ❌ Pas de retrain YOLO11-nano (hors scope, embarqué).
- ❌ Pas d'utilisation des 340 captures device cohorte (réservées pour
  l'ablation format crop, autre chantier).
- ✅ Modifications algorithmiques pures (OpenCV / numpy / SQL).
- ✅ Post-filter, scorer dérivé, UI overlay autorisés.
- ✅ Sub-agents pour des tâches isolées (recherche SOTA, classification
  visuelle, gros refactor).

## État de l'art (mai 2026, cf. findings/02)

- Pas de standard académique pour la détection coin produit bien-cropée.
- Pratiques : combinaison Hough + segmentation de fond + filtre
  géométrique (ratio diamètre/cadre).
- Notre baseline : YOLO11-nano + Hough en parallèle, merge IoU,
  rerank ArcFace, area_ratio comme filtre faible. Sortie : 1 678 crops
  pour 795 raws sur le run V.3, **74 % flaggés undercrop** par
  area_ratio < 0.10 (signal trop large).

## Ce qui a déjà été testé

| Idée | Résultat | Référence |
|------|----------|-----------|
| Composite is_coin (rim×continuity×metal) | TOP-tri OK, BOTTOM-flag KO | [expe 01](../experiments/01-composite-scorer-ab-d.md) |
| Composite × area_ratio_factor (unified v2) | Marginal | [expe 02](../experiments/02-unified-score-v2.md) |

## Ce qui reste à essayer (priorité 1)

1. **Anti-A dédié** : signal `bg_uniformity` sur l'extérieur du disque
   inscrit (théorie 01 non testée). Idée : un strip numérique a un fond
   bruité (digits autour), une vraie pièce isolée a un fond clean.
2. **Anti-B dédié** : signal `bbox_to_max_circle_ratio` — on relance
   Hough sur le **raw** entier, on prend le plus gros cercle plausible
   ; si la bbox courante est nettement plus petite, on flag undercrop B.
3. **Reject auto séparé** : deux thresholds indépendants au lieu d'un
   score unifié.
