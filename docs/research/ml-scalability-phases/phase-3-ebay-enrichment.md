# Phase 3 — Enrichissement eBay semi-automatique

> **Objectif** : apporter de vraies photos "in the wild" aux designs en zone orange et rouge, via un pipeline qui mutualise le scraping eBay **déjà prévu pour les prix de marché**. Une fiche eBay validée par un humain produit 2 features : un prix consolidé + une photo d'entraînement.

## Pourquoi cette phase après l'augmentation

- La phase 2 (augmentation 2D/2.5D avancée) pousse au maximum ce qu'on peut extraire d'**une seule** image Numista par design.
- Il reste des paires irréductibles : designs visuellement trop proches dont la distinction dépend de détails subtils (un visage, un motif central) qui ne peuvent pas être appris de façon robuste avec des variantes synthétiques d'une seule image.
- Pour ces paires, de vraies photos d'angles/conditions variés sont obligatoires.
- eBay est la seule source scalable à coût zéro : ~3000 pièces euro, beaucoup listées (pas toutes), avec des photos de vendeurs qui sont **exactement** la distribution cible (angles bizarres, mauvaise lumière, pièces sales).

## Dépendances

- Phase 1 livrée (cartographie pour prioriser le scraping sur zones orange/rouge)
- Phase 2 livrée et un modèle ArcFace v2 entraîné avec nouvelles augmentations (pour l'auto-filtrage)
- Mémoire projet : [`project_ebay_api_strategy`](`../../../` — voir MEMORY.md) — Browse API + velocity weighting déjà défini pour les prix

## Principe de fonctionnement

```
eBay Browse API
      │
      ├─── Cherche par "eurio_id → query string" (généré heuristiquement)
      │
      ▼
Fiches brutes (titre + images + prix)
      │
      ▼
Auto-filtrage par embedding
  (cosine sim avec centroïde Numista v2)
      │
      ├── sim > 0.6    → Auto-validée  → Insérée direct en training set
      ├── 0.3 < sim < 0.6 → À valider humain → LabelingQueuePage
      └── sim < 0.3    → Auto-rejetée → Archivée (inspection possible)
      │
      ▼
  Humain valide la queue (30 min pour ~3000 candidats)
      │
      ▼
   Dataset enrichi + prix consolidés
```

L'auto-filtrage par le modèle v2 de phase 2 élimine ~80% du bruit (mauvaise pièce, lot, photo floue de face arrière seulement, etc.) sans intervention humaine. L'humain se concentre sur la zone grise.

## Livrables

### 1. Migration Supabase

`supabase/migrations/YYYYMMDD_ebay_enrichment.sql` :

```
ebay_listings
├── id (PK)
├── ebay_item_id (text, unique)
├── eurio_id_guess (FK coins.eurio_id, nullable) -- match heuristique au scraping
├── eurio_id_validated (FK coins.eurio_id, nullable) -- après validation humaine
├── title_raw (text)
├── price_eur (numeric)
├── sold_at (timestamp, nullable) -- pour Browse API on a listed_at, sold via Marketplace Insights
├── images (jsonb)               -- array d'URLs
├── fetched_at (timestamp)
├── sim_to_centroid (float, nullable)  -- cosine similarity avec Numista v2
├── auto_status (enum: 'auto_validated' | 'needs_review' | 'auto_rejected')
├── human_status (enum: 'validated' | 'rejected' | 'uncertain' | null)
├── human_validated_at (timestamp, nullable)
└── used_in_training_at (timestamp, nullable)
```

Note : cette table sert à la fois pour le pricing et pour les photos. Les deux features lisent depuis la même source validée.

### 2. Pipeline de fetch `ml/scripts/ebay_fetch.py`

Arguments :
- `--zones orange,red` : scraping ciblé (par défaut : orange+red uniquement, pas green)
- `--max-per-coin 20` : plafond de listings par design
- `--dry-run` : preview sans écrire

Fonctionnement :
1. Lit les `eurio_id` à enrichir depuis Supabase (filtrage par zone via `coin_confusion_map`)
2. Pour chaque coin, construit une requête eBay Browse API (composition : `face_value + country + year range + commemorative_theme`)
3. Fetch les listings, télécharge les images
4. Embed chaque image avec le modèle ArcFace v2 (backend ML local)
5. Calcule `sim_to_centroid` par rapport au centroïde Numista du coin
6. Classe en `auto_validated` / `needs_review` / `auto_rejected` selon les seuils
7. Insère dans `ebay_listings`

**Rate limiting** : respecter les limites eBay Browse API (voir mémoire `project_ebay_api_strategy`). Fetch par batch, reprise possible.

### 3. Nouvelle vue admin : `LabelingQueuePage.vue`

Emplacement : `admin/packages/web/src/features/labeling/pages/LabelingQueuePage.vue`.

**UX type Tinder** pour validation à la chaîne :
- Grande image eBay au centre
- À droite : image Numista de référence du `eurio_id_guess`
- Titre raw eBay en dessous
- Similarité affichée
- Boutons + raccourcis clavier :
  - `✓` (flèche droite ou `v`) → validé, devient photo d'entraînement
  - `✗` (flèche gauche ou `x`) → rejeté (mauvaise pièce, photo inutilisable)
  - `?` (flèche haut ou `u`) → uncertain, reviens plus tard
  - `→` (flèche bas ou `s`) → skip sans statut
  - `e` → **edit guess** : menu qui permet de re-assigner à un autre `eurio_id` (cas fréquent : le vendeur liste "2€ Allemagne" alors que c'est 2€ Autriche)
- Pagination : batch de 100, préchargement des images suivantes pour fluidité
- Stats en header : `X / Y validés aujourd'hui`, cadence (items/min)

**Filtres** :
- Par zone (rouge d'abord)
- Par `eurio_id` spécifique (pour enrichir un coin ciblé depuis `CoinDetailPage`)
- Par similarity range

### 4. Enrichissement `CoinDetailPage.vue`

Ajout d'une section "Enrichissement photos" sur chaque coin zone orange/rouge :
- Stats : `{N} photos eBay auto-validées`, `{M} à valider`, `{K} photos humaines validées`
- Galerie des photos validées (vignettes)
- Bouton **"Enrichir depuis eBay"** : trigger un fetch ciblé sur ce coin (max 20 listings), insertion immédiate dans `ebay_listings`
- Bouton **"Revoir la queue pour ce coin"** : ouvre `LabelingQueuePage` préfiltrée sur cet `eurio_id`
- Bouton **"Entraîner"** : disponible si `nb_photos_validees ≥ min_required_for_zone` (3 pour rouge, 2 pour orange, 1 pour verte). Sinon grisé avec tooltip explicatif.

### 5. Intégration training

Modification de `ml/training/dataset.py` (ou équivalent) pour qu'il lise depuis :
- **Images Numista** (source primaire, toujours présente)
- **Photos validées eBay** (si `ebay_listings.human_status = 'validated'` ou `auto_status = 'auto_validated'`)

Chaque source garde un flag pour distinguer "scan studio" vs "in the wild", utile pour phase 4 (sub-center).

### 6. Commandes go-task

- `go-task ml:ebay-fetch ZONES=orange,red` : lance le fetch
- `go-task ml:ebay-stats` : affiche stats de la queue (combien à valider)

## Non-livrables (explicites)

- Pas de sub-center ArcFace (phase 4)
- Pas de banc d'éval in-the-wild formel (phase 4)
- Pas de 3D (phase 5)
- Pas d'amélioration du pipeline d'augmentation (phase 2)

## Estimation du travail humain

Base d'estimation (à ajuster selon la réalité post-fetch) :
- ~3000 pièces catalogue, dont ~15% zone rouge (450 coins) et ~25% zone orange (750 coins)
- Budget de 20 listings/coin → 24 000 listings fetchés max
- Auto-validation ~50% → 12 000 gardées direct
- Auto-rejet ~30% → 7 200 écartées
- À valider humain ~20% → ~4 800 items
- Cadence réaliste UI bien faite : 60-100 items/min → **~60-80 min de travail humain total**, réparti en plusieurs sessions

C'est une borne haute. En pratique, on peut s'arrêter dès qu'on a 3-5 photos validées par coin zone rouge, donc moins.

## Métriques de sortie

- `nb_coins_enrichis` (≥ 3 photos validées) par zone
- `nb_photos_auto_validées` vs `nb_photos_human_validées` vs `nb_rejetées`
- Temps médian humain par item
- Re-run cartographie avec modèle v3 (entraîné Numista + eBay) → nouvelle distribution des zones

## Critères de passage à la phase suivante

- ≥ 80% des coins zone rouge ont ≥ 3 photos validées
- ≥ 60% des coins zone orange ont ≥ 2 photos validées
- Modèle v3 entraîné sur dataset enrichi
- Réduction mesurée des paires en zone rouge après re-cartographie

## Risques / points d'attention

- **Qualité du match heuristique eurio_id_guess** : la requête de recherche eBay construite automatiquement peut être approximative. On compense par l'auto-filtrage (une mauvaise pièce aura une similarité faible) + re-assignation manuelle en queue.
- **Biais geographic** : eBay.fr vs .de vs .com renvoient des distributions différentes. Utiliser eBay Global / multi-marketplace Browse API pour couverture large.
- **Lots vs pièces seules** : beaucoup de listings sont des "lots de 50 pièces". La similarité sera faible (photo encombrée), donc auto-rejet. OK par défaut.
- **Droits sur images** : les photos des vendeurs sont protégées. Usage strictement interne pour training (pas de republication) → fair use / research usage. À valider avec légal si l'app se monétise.
- **Travail humain qui dérive** : risque de fatigue → labelisation bâclée. Mitigé par sessions courtes + UI rapide + quality checks aléatoires (re-show d'items déjà validés pour vérifier cohérence).
- **Coûts Supabase storage** : stocker les images eBay (jusqu'à plusieurs dizaines de milliers) peut faire exploser les 1 GB du free tier (voir mémoire `reference_supabase_free_tier`). Alternative : stocker les URLs seulement, télécharger on-demand pour training. Préférable.
