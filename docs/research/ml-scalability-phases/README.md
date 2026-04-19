# ML Scalability Phases — Reconnaissance de pièces euro à l'échelle

> Plan de travail pour passer du pipeline de reconnaissance actuel (7 designs, R@1=100% en labo) à un système qui tient **300-500 designs** dans des conditions réelles (pièces sales, éclairage quelconque, tilt, usure).
>
> Session de brainstorming : 2026-04-17. Prompt d'origine : [`../prompt-embedding-scalability.md`](../prompt-embedding-scalability.md).

## Problème de fond

Le pipeline actuel (MobileNetV3-Small + ArcFace 256-dim + cosine matching) est sain **sur le papier**. Le blocage n'est pas l'architecture, c'est **la donnée** :

- On a **1 seule image Numista par design** (scan studio : éclairage parfait, pièce propre, bien droite).
- On ne peut pas acheter les ~3000 pièces du référentiel pour photographier les rares.
- La distribution cible à l'inférence est l'opposé exact du training : pièces sales, mal éclairées, tiltées, usées.

À 7 classes, l'écart inter-classes est énorme → ça marche. À 500 classes avec des commémoratives visuellement proches, le modèle va apprendre à reconnaître la **signature Numista** plutôt que des features invariantes.

## Stratégie en 5 phases

Chaque phase est un lot cohérent qui produit :
- un **artefact ML** (script, modèle, banc d'éval) côté `ml/`
- une **surface admin** (vue, badge, queue) côté `admin/packages/web/`
- des **métriques** re-mesurables pour décider si on passe à la phase suivante

| Phase | Nom | Doc | Précondition |
|---|---|---|---|
| 1 | Cartographie de confusion | [phase-1-cartographie.md](phase-1-cartographie.md) | Catalogue actuel (~3000 coins, dont ~500 designs) avec images Numista |
| 2 | Augmentation 2D avancée + re-lighting 2.5D | [phase-2-augmentation.md](phase-2-augmentation.md) | Phase 1 (pour cibler les zones orange/rouge en priorité) |
| 3 | Enrichissement eBay semi-automatique | [phase-3-ebay-enrichment.md](phase-3-ebay-enrichment.md) | Phase 1 (pour prioriser) + modèle v1 entraîné (pour filtrer) |
| 4 | Sub-center ArcFace + banc d'éval honnête | [phase-4-subcenter-evalbench.md](phase-4-subcenter-evalbench.md) | Phase 3 (sub-center exige de la vraie variation intra-classe) |
| 5 | Rendu 3D ciblé (optionnel) | [phase-5-3d-rendering.md](phase-5-3d-rendering.md) | Phase 4 conclut qu'il reste des paires irréductibles |

## Décisions actées dans ce brainstorm (2026-04-17)

| # | Décision | Rationale |
|---|---|---|
| 1 | **Rester en 256-dim** pour l'embedding ArcFace. Pas de passage à 512. | 500 classes ≈ 9 bits ; 256 dims L2-normalisés ont une capacité qui se compte en millions. 512 ne servirait qu'à doubler taille/latence. |
| 2 | **Le problème est la donnée, pas l'architecture.** Toute l'énergie va d'abord à enrichir le dataset et évaluer honnêtement, pas à changer la loss ou le backbone. | Un meilleur modèle sur de la mauvaise donnée overfitte plus vite. |
| 3 | **Approche pilotée par la confusion.** On ne collecte pas aveuglément : on cartographie d'abord les paires à risque, on cible l'enrichissement dessus. | Borne le travail humain (~30 min au lieu de plusieurs jours) et concentre l'effort où il compte. |
| 4 | **Dual-use eBay** : la même passe de scraping sert pour les **prix de marché** ET pour les **photos d'entraînement**. | eBay est déjà dans le roadmap pour la cotation. Une seule fiche validée par un humain alimente les deux features. |
| 5 | **Sub-center ArcFace activé en phase 4**, pas avant. | Sub-center accommode la variation intra-classe *quand elle existe* dans le dataset. Avec 1 seule image Numista + augmentations synthétiques, les k sous-centres convergent ou splittent sur du bruit. |
| 6 | **Tout passe par le panel admin.** Cartographie, queue de labeling, enrichissement, entraînement ciblé = surfaces Vue dans `admin/packages/web/`. | Le panel est déjà le cockpit (coins, training). On centralise, pas de CLI à mémoriser. |
| 7 | **3D est phase 5 optionnelle.** On n'y va que si les niveaux 1 + 2 d'augmentation 2D/2.5D ne suffisent pas sur une zone rouge précise. | Le rendu 3D a un coût pipeline non négligeable (Blender, normal maps propres, materials métalliques). Les pièces sont quasi-planes, donc l'ROI du vrai 3D est limité. |

## Ce qui n'est pas dans ce plan

- **Changement de backbone** (MobileNetV3-Large, EfficientNet, ViT mobile) — hors scope tant que la donnée est le goulot.
- **Hierarchical matching** (pays → design) — rejeté : erreurs en cascade, fragilité, perte de l'end-to-end.
- **Triplet loss / Siamese** — déjà évalué et dépriorisé (voir `docs/research/arcface-few-shot.md`).
- **Cloud matching** — hors scope : contrainte offline-first.

## Métriques globales à surveiller

Ces métriques sont re-mesurées à la fin de chaque phase pour comparer.

- **R@1 / R@3** globaux (train set clean)
- **R@1 / R@3 par zone** (verte / orange / rouge définies en phase 1)
- **R@1 / R@3 sur banc in-the-wild** (défini en phase 4)
- **Distribution des spreads top1-top2** (histogramme ; une bosse vers 0 = collision)
- **Top 20 paires les plus confondues** (comparable avant/après chaque phase)
- **Couverture dataset** : nb images réelles par design (vs augmentées)

## Liens utiles

- Pipeline détection+reco actuel : [`../detection-pipeline-unified.md`](../detection-pipeline-unified.md)
- Recherche ArcFace few-shot antérieure : [`../arcface-few-shot.md`](../arcface-few-shot.md)
- Embedding vs classification : [`../embedding-vs-classification.md`](../embedding-vs-classification.md)
- Stratégie eBay (prix) : [`../ebay-api-strategy.md`](../ebay-api-strategy.md)
- Architecture référentiel : [`../data-referential-architecture.md`](../data-referential-architecture.md)
