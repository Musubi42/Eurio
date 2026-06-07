# Feature : Model — embedder qui produit les vecteurs

> Question centrale : **quel modèle transforme une photo en vecteur,
> et comment on l'entraîne pour que les vecteurs séparent les
> classes ?**
>
> Le modèle est le dernier maillon : `scrape` lui fournit le pool
> de photos, `augmentation` les variantes, et lui sort des
> embeddings + des centroïdes que l'app on-device utilise pour
> matcher.

## État actuel — ArcFace from-scratch

- **Backbone** : ResNet-style entraîné from-scratch sur nos données.
- **Tête** : ArcFace (margin 0.2, scale 25, cosine similarity).
- **Training** : 40 epochs, batch_size 256, m_per_class 4,
  prebaked_augmentations.
- **Export** : TFLite via `ml/scripts/export_tflite.py`.
- **Runtime Android** : `app-android/src/main/java/com/musubi/eurio/ml/EmbeddingMatcher.kt`
  charge le TFLite + la lib `embeddings_v1.json`.

Performance baseline (test-1 v2 sur cohort 7-classes) :

- Bench R@1 strict : 92.86%
- Live R@1 strict : 85.7%
- mean_spread top-1/top-2 : 0.09 (serré sur les standards UE)

## Limites observées

- **Backbone from-scratch souffre du peu de données.** ArcFace est
  pensé pour des millions de visages — entraîner un ResNet
  from-scratch sur 50 augs de 7 classes est techniquement légal
  mais sub-optimal. Le réseau apprend autant les artefacts d'aug
  que la sémantique de la pièce.
- **Cluster standards UE serré.** mean_spread 0.09 et top-1/2
  collés à <0.05 sur certains cas révèlent que le backbone
  from-scratch ne crée pas de marge confortable sur les designs
  proches.
- **Plafonnement attendu sur cohorts plus larges.** Avec 7 classes
  on est à 86% live ; avec 100+ classes (full euro catalog) le mur
  arrivera plus bas, sauf amélioration backbone.

## Pivot stratégique : DINOv2 backbone + tête ArcFace fine-tunée

La littérature (Pl@ntNet, retrieval fine-grained CARS196 / SOP /
iNaturalist) converge vers une recette :

> Foundation backbone pré-entraîné (DINOv2 / SigLIP / CLIP), tête
> métric learning (ArcFace) fine-tunée sur la tâche cible. Le
> backbone apporte une base "visuelle générique" déjà robuste aux
> conditions wild, la tête spécialise sur les classes du domaine.

Pourquoi c'est probable de mieux marcher pour Eurio :

- **DINOv2 a vu des milliards d'objets** (textures, reliefs
  métalliques, formes circulaires, conditions de lumière variées).
  La studio→wild gap est partiellement absorbée "gratuitement".
- **Self-supervised, pas de biais culturel** vers les pièces US ou
  asiatiques (objection légitime mais non rédhibitoire — le modèle
  n'a pas appris des classes nominales mais des features visuelles
  bas et moyen niveau qui transfèrent).
- **Fine-tuning ciblé** : on ne ré-entraîne pas le backbone (ou
  juste une LoRA / dernier bloc) — on entraîne la tête ArcFace sur
  nos eurio_ids. Bien moins de paramètres = bien moins de risque
  d'overfit sur peu de données.
- **Le validateur scrape réutilise le même DINOv2** (cf.
  [`scrape.md`](./scrape.md)). Investissement code partagé.

## Le défi on-device

DINOv2 ViT-S/14 fait ~21M params. Faisable mais lourd pour un
téléphone. Trois stratégies :

1. **Distillation** : entraîner un mobile-friendly student
   (MobileViT, EfficientFormer) à reproduire les embeddings DINOv2.
   Standard, bien documenté.
2. **Quantization INT8** : garder DINOv2 mais le quantizer
   agressivement. TFLite supporte. Latence et taille acceptables
   sur device récents (≥ 2022).
3. **Backbone mobile-natif pré-entraîné** : MobileCLIP, FastViT-MA.
   Moins puissant que DINOv2 mais pré-entraîné sur foundation-style
   data, pas from-scratch.

Choix à trancher après le bench DINOv2 zero-shot (phase 1 du
track harvest).

## Méthodologie pour pivoter

L'isolation par `iteration_id` (lab-prod-refacto phase 2) rend ça
sûr : on peut faire tourner une itération "DINOv2 + ArcFace head"
en parallèle de l'itération courante "ResNet from-scratch +
ArcFace" sans qu'aucune ne pollue l'autre. Le promote step (phase 3)
décide laquelle ship en prod.

Plan :

1. **Bench DINOv2 zero-shot** sur la cohort `mix-zone-7-cls-v2` —
   chiffre stratégique. Si ≥ 86% sans training → pivot validé.
   Si < 70% → on creuse autrement. Cf.
   [`harvest/phase-1-dinov2-bring-up.md`](../training-pipeline/harvest/phase-1-dinov2-bring-up.md).
2. **Fine-tune ArcFace head** sur DINOv2 frozen, mêmes données que
   ResNet from-scratch. Comparer side-by-side.
3. **Distill / quantize** vers TFLite mobile.
4. **Intégration Android** dans le matcher existant.

## Pistes ouvertes

- **Multi-vue training** : si scrape donne plusieurs photos par
  pièce, on peut entraîner avec triplet/contrastive sur des paires
  réelles plutôt que via aug synthétique. Plus puissant que ArcFace
  classique sur certains benchmarks.
- **Hard negative mining** spécifique au cluster standards UE
  (forcer le réseau à séparer AT-2002 / BE-2007 / ES-1999 plus
  fortement).
- **Multi-task learning** : prédire pays / année / commémo en
  parallèle comme tâche auxiliaire. Pas évident, à explorer si on
  plafonne.
- **Test-time augmentation** côté Android : moyenner les embeddings
  de plusieurs crops de la même photo. Coûte un peu de latence,
  peut casser certaines confusions condition-extrême.

## Métriques pour piloter cette feature

- **Live R@1 strict** sur cohort frozen — métrique de vérité
- **Bench R@1 strict + R@3 + R@5**
- **mean_spread** — marge entre top-1 et top-2 (proxy de
  robustesse)
- **Latence d'inférence on-device** — contrainte produit (cible
  <300ms par scan, à benchmarker)
- **Taille TFLite** — contrainte APK (cible <50MB par modèle, à
  réviser selon stratégie)

## Implémentation référencée

- Training pipeline : `ml/training/train_embedder.py`
- Compute embeddings : `ml/training/compute_embeddings.py`
- Export TFLite : `ml/scripts/export_tflite.py`
- Runtime Android : `app-android/src/main/java/com/musubi/eurio/ml/EmbeddingMatcher.kt`

## Liens vers features voisines

- **Scrape** : fournit les données. Plus de photos = meilleur
  fine-tuning, surtout pour DINOv2 qui a besoin de moins de samples
  qu'un from-scratch. Cf. [`scrape.md`](./scrape.md).
- **Augmentation** : un foundation backbone change la pertinence
  des augs. Beaucoup d'augs deviennent superflues parce que DINOv2
  les a déjà vues en pré-entraînement. Cf.
  [`augmentation.md`](./augmentation.md).

## Tracks d'implémentation associés

| Track | Doc |
|---|---|
| Harvest phase 1 (DINOv2 bring-up) | [`harvest/phase-1-dinov2-bring-up.md`](../training-pipeline/harvest/phase-1-dinov2-bring-up.md) |
| Lab/prod isolation (phase 2) | [`lab-prod-refacto/phase-2-isolation-artefacts.md`](../lab-prod-refacto/phase-2-isolation-artefacts.md) — prérequis pour faire cohabiter ArcFace-scratch et DINOv2 sans pollution |
| Promote (phase 3) | [`lab-prod-refacto/phase-3-promote.md`](../lab-prod-refacto/phase-3-promote.md) — décide quel modèle ship |
