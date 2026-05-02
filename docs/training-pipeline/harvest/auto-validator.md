# Auto-validateur de photos scrapées

> Pipeline qui prend une photo candidate (eBay, etc.) + un label
> proposé (déduit du contexte de la source) et décide :
> auto-accept / review queue / reject.
>
> Sans cet outil, le scraping massif est inexploitable parce que le
> bruit (faux labels, photos multi-pièces, stock dupliqué) pollue le
> training set. Avec, on peut **se faire plaisir** sur le scraping
> et limiter la review humaine aux cas ambigus.

## Principe : multi-signal

Aucun signal pris isolément n'est fiable. La règle :

> **Une photo est auto-acceptée seulement si deux signaux
> indépendants convergent vers le même label.**

Les deux signaux sont :

1. **Signal texte** — extraction du label depuis le titre +
   description du listing source (sans LLM, par regex/règles
   structurées : pays, année, dénomination, nom commémo).
2. **Signal image** — DINOv2 (ou foundation choisi en phase 1)
   produit l'embedding de la photo candidate ; cosine similarity vs
   les ancres canoniques Numista de toutes les pièces du catalogue ;
   on regarde le top-k.

## Pipeline

```
photo candidate + métadonnées listing
            │
            ▼
┌──────────────────────────────┐
│ 1. Pré-traitement            │
│  - détection cercle (OpenCV) │
│  - crop pièce isolée         │
│  - rejet si multi-pièces     │
│  - rejet si pas de cercle    │
│  - dédup pHash vs canonique  │
└──────────────────────────────┘
            │
            ├──► (rejeté: stock dup / no coin) → ❌
            ▼
┌──────────────────────────────┐
│ 2. Signal texte              │
│  parse titre + description   │
│  → label_text ∈ {coin, ∅}    │
└──────────────────────────────┘
            │
            ▼
┌──────────────────────────────┐
│ 3. Signal image (DINOv2)     │
│  embedding photo candidate   │
│  cosine vs N ancres Numista  │
│  → label_img (top-1)         │
│  → score_img                 │
│  → spread (top1-top2)        │
└──────────────────────────────┘
            │
            ▼
┌──────────────────────────────┐
│ 4. Décision                  │
│  voir matrice ci-dessous     │
└──────────────────────────────┘
            │
            ├──► auto-accept   → training set
            ├──► review queue  → admin UI
            └──► reject        → log
```

## Matrice de décision

| Signal texte | Signal image (top-1) | Score image | Spread top1-top2 | Action |
|---|---|---|---|---|
| `kniefall` | `kniefall` | > τ_high (≈ 0.85) | > δ (≈ 0.05) | ✅ auto-accept |
| `kniefall` | `kniefall` | τ_low–τ_high (≈ 0.70–0.85) | quelconque | ⚠️ review |
| `kniefall` | `kniefall` | > τ_high | < δ (collé top2) | ⚠️ review |
| `kniefall` | autre | quelconque | quelconque | ⚠️ review |
| `kniefall` | aucun candidat > τ_low | — | — | ❌ reject |
| `∅` (texte ambigu) | une classe | > τ_very_high (≈ 0.92) | > δ_strong (≈ 0.10) | ⚠️ review |
| `∅` | une classe | < τ_very_high | quelconque | ❌ reject |
| `kniefall` | `france-2016-rugby` | > τ_high | quelconque | ❌ reject (signaux contradictoires) |

Les seuils `τ_low`, `τ_high`, `τ_very_high`, `δ`, `δ_strong` sont
**à calibrer en phase 2** sur un set hand-labelé (objectif : 200
paires, 1h de boulot humain).

## Calibration des seuils

1. Constituer un **set de calibration** : 200 photos eBay déjà
   hand-labelées (accept/reject) couvrant les 7 classes de
   `mix-zone-7-cls` ou la cohort active.
2. Faire tourner le pipeline sans seuil de décision → obtenir
   `(score_img, spread, label_text, ground_truth)` pour chaque.
3. Tracer les courbes precision/recall en fonction de τ.
4. Choisir `τ_high` tel que **precision auto-accept > 99%** sur le
   set (faux positifs très coûteux : photo mal labelée pollue
   directement le training).
5. Choisir `τ_low` tel que **recall review queue > 95%** (on n'aime
   pas rejeter des photos valides en silence).
6. Documenter les seuils dans `ml/config/harvest_validator.json`
   versionné.

Recalibrer périodiquement quand le foundation model change ou
quand de nouvelles classes sont ajoutées.

## Failure modes connus

### Standards quasi-jumeaux

Symptôme attendu : les obverses standards UE (carte d'Europe + pays)
se ressemblent beaucoup. DINOv2 va probablement classer un BE-2007
comme proche d'AT-2002 et d'ES-1999.

**Mitigation phase 2** : auto-validateur restreint aux
**commémoratives** (designs uniques par construction). Les standards
ne passent pas par le pipeline auto en phase 2.

**Mitigation phase 3** : pour les standards, exiger **trois signaux
convergents** au lieu de deux — texte + image + métadonnée du listing
(ex: pays du seller, année dans le titre). Et seuils plus stricts.

### Photos multi-pièces

eBay vendeurs qui shootent un lot de 10 pièces.

**Mitigation** : OpenCV détecte plusieurs cercles → soit on rejette,
soit on crop chaque cercle et on les valide individuellement. À
décider en phase 2 selon volume observé.

### Obverse vs reverse

Le matcher Eurio est **obverse-only**. Les eBay listings shootent
souvent les deux faces (parfois une seule).

**Mitigation** : classifier binaire face/pile en amont. Plusieurs
options :
- Mini-modèle dédié (mais coûteux à entraîner).
- DINOv2 contre les **deux** ancres canoniques (obverse + reverse) ;
  on ne valide que si la photo est plus proche de l'obverse que du
  reverse de la même pièce, et plus proche de l'obverse de la pièce
  cible que de toutes les autres.
- Heuristique : pour les standards UE, l'obverse a la carte d'Europe
  → détection facile.

À trancher en phase 2 selon les premiers vrais cas observés.

### Stock photos dupliquées

Vendeurs qui réutilisent l'image Numista officielle.

**Mitigation** : pHash perceptuel calculé contre la photo canonique
de chaque pièce. Si distance < seuil → rejet (apporte zéro valeur
d'augmentation).

### Wrong year, même design

Pour les commémoratives qui réutilisent un thème (rare en euros).
Pour les standards UE : le design obverse change parfois (Belgique
ancien/nouveau Roi, Espagne ancien/nouveau Roi). À traiter comme
**deux classes distinctes** dans le catalogue.

### Sur-représentation des communes

eBay a 100x plus de photos de FR-2002 standard que de pièces rares.
Le training set risque d'être déséquilibré.

**Mitigation** : cap par classe (ex: max 50 photos auto-validées par
pièce avant que le scraping arrête de la cibler). Forcer la
diversification vers les classes sous-représentées.

## Métriques de qualité du validateur lui-même

À chaque batch de scraping, on tracke :

- **Taux d'auto-accept** (% candidats → training set sans humain)
- **Taux de review** (% candidats → file admin)
- **Taux de reject** (% candidats jetés)
- **Precision spot-check** : sur 50 auto-accept tirés aléatoirement,
  combien sont vraiment bons quand un humain re-vérifie ? Cible : 99%+.
- **Recall sur set de validation** : sur les vraies photos (set de
  calibration), combien sont auto-accept ?
- **Drift** : recalcul des seuils si la precision baisse > 2 points.

Ces métriques alimentent un dashboard dans l'admin lab (cf.
[`human-review.md`](./human-review.md)).

## Ce qu'on ne fait PAS

- **Pas d'appel LLM** dans le pipeline d'auto-validation. Le signal
  texte est règles + regex. Un LLM rajouterait latence + coût + non-
  déterminisme pour un gain marginal sur des titres eBay structurés.
- **Pas de seuil unique global**. Les seuils sont par classe ou par
  groupe de classes (commémo vs standard) si nécessaire.
- **Pas de feedback automatique** depuis le model trained vers le
  validateur. Le validateur reste **indépendant** de l'embedder en
  cours d'entraînement, sinon on a une boucle de pollution. Il
  s'appuie sur le foundation pré-entraîné (DINOv2 fixe).
