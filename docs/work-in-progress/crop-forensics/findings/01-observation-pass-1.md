# Finding 01 — Observation pass 1 (2026-05-26)

**Setup** : sampler HTML statique (`ml/scripts/crop_exp/sampler.py`) sur run
`059dc8d9`, 4 groupes × 4 methods = ~13 panels (certaines combos vides), 6-8
cards aléatoires (seed 42) par panel. Screenshots HD (force-scale 2x) puis
inspection œil humain.

## Comportement attendu vs observé

L'attendu : la bbox couvre exactement la pièce visible dans le raw, le crop
chip 224×224 montre cette même pièce centrée.

L'observé : très variable. Quatre catégories d'erreurs récurrentes.

## Catégorie A — Detection d'objet circulaire non-pièce (faux positif)

Exemples : bbox sur un timbre dans une enveloppe (cover philatélique), sur
un logo de packaging, sur un médaillon décoratif dans un livret, sur le
watermark eBay.

- Card AT-2005-yolo+hough #8 : enveloppe avec timbre rond → bbox détecte le
  timbre comme une pièce.
- Card DE-2007-yolo+hough #2 : note manuscrite + petits éléments → bbox sur
  un sticker.
- Card IT-2016-yolo+hough+polish #4 : livret "DONATELLO" → bbox sur élément
  graphique du livret.

**Volume estimé** : ~10-15 % des crops sur ces groupes.

## Catégorie B — Detection d'un détail intérieur sur macro shot (inner feature)

Quand la pièce remplit la quasi-totalité du raw (macro shot, eBay vendeur
pro), Hough vote parfois un cercle INTÉRIEUR à la pièce : le "10" gravé,
le rond intérieur d'un dessin, l'œil d'un portrait.

- Card DE-2010-yolo+hough #4 : raw 1600×1280, énorme pièce de 2 € avec "10"
  visible (sans doute "2010"). bbox tiny sur le "10".
- Card DE-2007-yolo+hough+polish #1 : énorme pièce sur fond noir, bbox tiny
  sur une feature interne.

C'EST EXACTEMENT LE BUG BIMÉTAL ANCESTRAL, mais sa généralisation : pas
seulement le rim manqué, c'est un cercle plus petit que la pièce qui passe.

**Volume estimé** : ~5 % des crops, mais TRÈS visible.

## Catégorie C — Multi-pièce dans un raw d'album set (légitime mais ambigu)

Listings qui vendent un set complet (5-10 pièces) dans un album. Le pipeline
crée 1 crop par pièce détectée (`crop_index` 0..N). Chaque crop est OK
visuellement mais on ne sait pas laquelle des N pièces correspond au
`target_eurio_id` cherché par la query eBay.

**Volume estimé** : ~50-60 % des listings 2 € commémo.

C'est un problème de TAGGING (résolution eurio_id), pas de QUALITÉ DE CROP.
Hors scope direct de ce chantier, mais à mentionner car la résolution
downstream sera difficile.

## Catégorie D — Crops corrects

Listings avec 1 pièce centrale bien lisible, bbox sur la pièce, crop chip
qui montre la pièce. Volume estimé : ~25-30 %.

## Pourquoi le `area_ratio < 0.10` flag tout

Confirmation visuelle de la limite [[01-known-limits.md#L1]] : sur les ~30
cards inspectées, ~70 % ont area_ratio < 0.10 (donc flag rouge) mais
seulement ~20 % sont des erreurs réelles (catégories A+B). Le mask rouge
crie au loup sur les "petites pièces dans grand cadre" qui sont pourtant
des crops parfaits.

## Conséquence pour les théories

Les fixes à creuser, par ordre d'impact apparent :

1. **Filtrer les faux positifs (cat. A)** : ajouter un scoring "ceci est-il
   vraiment une pièce ?" post-détection. Critères : ratio luminance
   intérieur/extérieur, contraste circulaire, présence de gravure (variance
   locale, edges).

2. **Bloquer les détections "inner feature" (cat. B)** : quand le raw est
   majoritairement occupé par UNE grande pièce, refuser les bbox << taille
   raw. Heuristique : si bbox.r < 0.3 × min(raw.w, raw.h) ET le raw contient
   peu de circles forts, c'est probablement un inner-feature.

3. **Refondre area_ratio** : remplacer par un score multi-critères qui
   distingue "petite pièce légitime" (background varié, contraste fond/pièce)
   de "détail intérieur d'une grande pièce" (background = même métal).

4. **Hors scope crop, à signaler** : la cat. C (multi-pièce album) demande
   un labelling downstream. À ne pas confondre avec un bug crop.
