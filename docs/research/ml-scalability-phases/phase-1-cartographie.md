# Phase 1 — Cartographie de confusion

> **Objectif** : avant de changer quoi que ce soit à l'entraînement ou à la collecte de données, savoir **où sont les paires à risque** dans le catalogue. Sortir une carte : zones vertes (designs isolés, 1 image Numista suffit), orange (voisins proches, enrichissement recommandé), rouges (paires quasi-jumelles, enrichissement obligatoire).

## Pourquoi cette phase en premier

Toutes les phases suivantes (augmentation ciblée, enrichissement eBay, sub-center, 3D) sont **pilotées par la cartographie**. Sans cette carte, on travaille à l'aveugle :

- Augmenter agressivement toutes les classes → gaspillage de calcul sur les 70% de zone verte déjà séparées
- Scraper eBay pour 3000 pièces → labélisation humaine massive non nécessaire
- Sub-center ArcFace → active la variation là où il n'y en a pas besoin

La cartographie borne le travail à ~30% du catalogue qui en a vraiment besoin.

## Dépendances

- Catalogue actuel dans Supabase avec images Numista disponibles (déjà en place)
- Admin existant : `CoinsPage`, `CoinDetailPage`, `TrainingPage` (déjà en place)
- **Aucune dépendance ML** : on utilise un encodeur pré-entraîné générique, pas notre modèle ArcFace

## Livrables

### 1. Script de cartographie `ml/scripts/confusion_map.py`

Rôle : calculer la matrice de similarité pairwise sur tous les designs du catalogue et produire un classement zone verte / orange / rouge.

**Encodeur** : **DINOv2 ViT-S/14** (Meta, self-supervised, excellent pour la similarité visuelle générique, ~22M params, dispo sur HuggingFace). Pas de fine-tuning, usage en zero-shot. Alternative de secours : CLIP ViT-B/32.

**Pourquoi DINOv2 plutôt que notre modèle ArcFace v1** : l'ArcFace actuel est entraîné sur 7 classes, donc biaisé. DINOv2 donne une baseline "sim visuelle générale" non biaisée. On pourra re-cartographier avec notre ArcFace v2 en phase 4 pour comparer.

**Entrées** :
- Supabase : liste de tous les designs uniques du catalogue (clé = `eurio_id` canonique, ou `(design_hash)` si on groupe les réémissions annuelles)
- Images Numista obverse + reverse (fetch via URLs déjà stockées)

**Sortie** : table Supabase `coin_confusion_map` (nouvelle migration) :
```
coin_confusion_map
├── id (PK)
├── eurio_id (FK coins.eurio_id)
├── nearest_neighbor_eurio_id (FK coins.eurio_id)
├── nearest_similarity (float)  -- cosine sim avec le voisin le plus proche
├── top_k_neighbors (jsonb)     -- top 5 voisins avec similarités
├── zone (enum: 'green' | 'orange' | 'red')
├── computed_at (timestamp)
└── encoder_version (text)       -- 'dinov2-vits14' pour traçabilité
```

**Seuils de zone** (à calibrer empiriquement sur le catalogue actuel, valeurs de départ) :
- `green` : nearest_similarity < 0.70 (voisin le plus proche lointain → Numista + aug suffit)
- `orange` : 0.70 ≤ nearest_similarity < 0.85 (enrichissement recommandé)
- `red` : nearest_similarity ≥ 0.85 (enrichissement obligatoire, paires quasi-jumelles)

Les seuils seront ajustés après première run en regardant la distribution réelle.

**Prise en compte obverse/reverse** : chaque pièce a 2 faces souvent très différentes. On calcule la similarité par face séparément, puis on retient le **max des deux** (la face la plus confuse définit la zone de la pièce). Alternative : moyenne des deux.

### 2. Migration Supabase

`supabase/migrations/YYYYMMDD_coin_confusion_map.sql` :
- Crée la table `coin_confusion_map`
- Index sur `zone` (pour filtrage rapide admin)
- Index sur `(eurio_id, encoder_version)` (unique)
- Regénère les types TS (`go-task supabase:types` si la commande existe, sinon `pnpm supabase:types`)

### 3. Commande go-task

`go-task ml:confusion-map` dans `Taskfile.yml` :
- Lance `python ml/scripts/confusion_map.py --encoder dinov2-vits14 --write-supabase`
- Flag `--dry-run` pour preview sans écrire
- Flag `--eurio-ids` pour re-cartographier un subset

### 4. Nouvelle vue admin : `ConfusionMapPage.vue`

Emplacement : `admin/packages/web/src/features/confusion/pages/ConfusionMapPage.vue` (nouveau feature module).

Contenu :
- **Header** : bouton "Recalculer la cartographie" (appelle la task via backend local, désactivé en prod Vercel)
- **Résumé chiffré** : nb coins en zone verte / orange / rouge, % de couverture du catalogue
- **Histogramme de distribution** des `nearest_similarity` (visualise où sont les seuils)
- **Liste paginée des top 100 paires les plus confondues**, chaque ligne :
  - Image obverse A + image obverse B côte à côte
  - `eurio_id` A, `eurio_id` B, similarité, zone résultante
  - Lien vers `CoinDetailPage` pour chacun
- **Filtres** : par pays / par commemorative-ness / par zone
- **Fallback local-only** : si backend ML pas dispo (prod Vercel), la page affiche uniquement les données lues depuis Supabase (pas le bouton recalcul)

### 5. Badge zone sur `CoinsPage.vue` existante

Modifications minimales :
- Ajout d'une colonne/badge `zone` à côté du statut "trained" existant (🟢 🟠 🔴 avec tooltip "Voisin le + proche : {nearest_eurio_id} @ {similarity}")
- Nouveau filtre dans la barre de filtres : `zone = verte | orange | rouge | non-cartographié`
- Tri possible par `nearest_similarity` (descendant = les plus à risque en haut)

### 6. Section zone sur `CoinDetailPage.vue` existante

Ajout d'une section "Cartographie de confusion" :
- Badge zone de la pièce
- Voisin le plus proche : thumbnail + eurio_id + similarité
- Top 5 voisins avec mini-thumbnails
- Texte explicatif selon la zone :
  - 🟢 : *"Cette pièce est visuellement isolée. Entraînement direct possible avec Numista + augmentation."*
  - 🟠 : *"Voisin proche détecté. Enrichissement recommandé avant entraînement."*
  - 🔴 : *"Paire quasi-jumelle détectée. Enrichissement obligatoire — l'entraînement sans photos additionnelles produira des collisions."*

**Pas encore** de bouton "Enrichir" à cette phase (c'est la phase 3). Pour la phase 1, on se contente d'afficher l'info.

## Non-livrables (explicites)

- Pas de changement au pipeline d'entraînement
- Pas de nouvelles augmentations
- Pas de scraping eBay
- Pas de modification de la loss ArcFace

## Métriques de sortie

- % de coins en zone verte / orange / rouge (snapshot à conserver)
- Top 20 paires les plus confuses (screenshot pour historisation)
- Distribution complète des `nearest_similarity` (histogramme)

Ces chiffres deviennent la **baseline** de comparaison pour toutes les phases suivantes.

## Critères de passage à la phase suivante

- `coin_confusion_map` populée pour 100% des designs actifs du catalogue
- `ConfusionMapPage` accessible et fonctionnelle
- Badges zone visibles sur `CoinsPage` et `CoinDetailPage`
- Baseline chiffrée consignée (dans ce doc ou un log)

## Risques / points d'attention

- **Seuils de zone arbitraires** : les valeurs 0.70 / 0.85 sont des points de départ. Il faudra probablement calibrer après première run en regardant les paires réellement confuses à l'œil.
- **DINOv2 pas parfait pour les pièces** : c'est un encodeur générique entraîné sur images naturelles. Il pourrait sous-estimer la similarité entre deux pièces (qui se ressemblent toutes "un peu" côté distribution des features). Plan B si résultats décevants : CLIP, ou entraîner un ArcFace v0 rapide sur l'intégralité des Numista pour cartographier.
- **Avers/revers** : bien gérer le fait qu'une pièce a 2 faces. Une approche simpliste (une seule face) donnerait une carte fausse.
- **Réémissions annuelles** : une pièce 1€ France 2002 et 1€ France 2019 peuvent avoir le même design (similarité ~1.0) — il faut les grouper par `design_id` ou équivalent avant de cartographier, sinon le catalogue est pollué de "doublons" qui ne sont pas des vraies collisions.
