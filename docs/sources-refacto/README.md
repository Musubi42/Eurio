[//]: # (Sources refacto — index)

# Refacto sources

> Statut : **analyse + plan, aucun code livré.** Document écrit
> 2026-05-02 après alignement produit sur la collecte multi-sources.
>
> Objectif : transformer la chaîne d'ingestion d'un assemblage ad-hoc
> par source en un **contrat modulaire uniforme**, alimentant deux
> nouvelles tables dédiées (`image_assets`, `coin_market_quotes`)
> séparées du référentiel canonique.

## Pourquoi ce refacto existe

Aujourd'hui chaque source (Numista, eBay, LMDLP, MdP, BCE) a son propre
module dans `ml/referential/` ou `ml/market/`, son propre format de
sortie, et écrit dans des tables et fichiers hétérogènes. Conséquences :

1. **Photos sous-exploitées** — la majorité des `eurio_id` n'a qu'une
   paire obverse/reverse Numista canonique. Les photos in-hand (eBay,
   Catawiki) qui correspondent à la distribution réelle du scan en
   prod ne sont pas capturées.
2. **Prix consolidés trop tôt** — un seul P50 par pièce écrase la
   distinction entre marché actif (eBay), cotation marchand (LMDLP),
   enchères (Catawiki). On ne peut pas comparer ses propres prix à un
   concurrent spécifique.
3. **Pas de visibilité par source** — la page admin `/sources` montre
   un statut, mais pas les données récoltées, l'historique des runs,
   ni la couverture détaillée.
4. **Onboarding nouvelle source coûteux** — chaque ajout réinvente
   quota guard, dédup, run logging, intégration admin.

L'objectif n'est pas de réécrire ce qui marche — il est de poser un
**contrat modulaire** que toute source ancienne et nouvelle respecte,
et deux **tables d'atterrissage** séparées du référentiel canonique.

## Cible en une phrase

**Toute source produit, via un module `ml/sources/<source>/`, des rows
dans `image_assets` et/ou `coin_market_quotes`, dédupées par
`(source, source_ref)`, sans jamais agréger entre sources. La page
admin expose une carte + une page détail uniformes pour chacune.**

## Comment lire ce dossier

| Si tu veux… | Lis… |
|---|---|
| Comprendre l'état actuel par source | [`analysis.md`](./analysis.md) |
| Voir le schéma DB cible (DDL) | [`schema.md`](./schema.md) |
| Écrire un nouveau module source | [`module-contract.md`](./module-contract.md) |
| Comprendre le filtrage qualité photos | [`quality-pipeline.md`](./quality-pipeline.md) |
| Designer la page admin détail | [`admin-ux.md`](./admin-ux.md) |
| Implémenter la phase 1 (fondations) | [`phase-1-foundations.md`](./phase-1-foundations.md) |
| Implémenter la phase 2 (nouvelles sources) | [`phase-2-new-sources.md`](./phase-2-new-sources.md) |
| Implémenter la phase 3 (qualité) | [`phase-3-quality-pipeline.md`](./phase-3-quality-pipeline.md) |
| Implémenter la phase 4 (admin UX) | [`phase-4-admin-ux.md`](./phase-4-admin-ux.md) |
| Voir les questions non résolues | [`open-problems.md`](./open-problems.md) |
| Suivre l'avancement | [`progress.md`](./progress.md) |

## Phases

| # | Titre | Périmètre court | Bloque les suivantes ? | Statut |
|---|---|---|---|---|
| 1 | [Fondations](./phase-1-foundations.md) | Tables, base modulaire, refacto eBay vers nouveau contrat | **Oui** — toutes les phases en dépendent | 🔲 |
| 2 | [Nouvelles sources](./phase-2-new-sources.md) | Catawiki, NumisCorner, CGB | Non | 🔲 |
| 3 | [Pipeline qualité photos](./phase-3-quality-pipeline.md) | Score + flag `training_eligible`, intégration dataset prepare | Non, parallélisable à phase 2 | 🔲 |
| 4 | [Admin UX](./phase-4-admin-ux.md) | Page détail `/sources/:id`, cards enrichies | Non | 🔲 |

**Phase 1 est urgente** parce qu'elle pose le contrat. Tant qu'elle
n'est pas faite, ajouter une nouvelle source ou enrichir l'admin
revient à empiler de la dette.

## Décisions actées (2026-05-02)

- 2 nouvelles tables : `image_assets` + `coin_market_quotes`,
  séparées du référentiel canonique.
- **Pas de cross-source averaging.** Chaque source garde ses propres
  prix et ses propres images.
- **Dédup intra-source uniquement** via `(source, source_ref)`.
  Deux annonces eBay distinctes pour la même pièce = deux rows
  distinctes, deux images distinctes consommées par le training.
- **Stockage images local** au début (`ml/datasets/sources/<source>/...`),
  champ `storage_path` pourra pointer S3 plus tard.
- **`condition`** stockée brute (string libre source) + colonne
  `condition_normalized` enum optionnelle.
- **Images Catawiki/eBay** : téléchargement local, `license` tagué,
  flag `redistributable = false` pour ne jamais sortir du training.
- **Résolution `listing → eurio_id`** : problème documenté à part
  (cf. [`open-problems.md`](./open-problems.md)), pas dans cette refacto.
- **Pipeline qualité photos** avec `quality_score` + `training_eligible`,
  un seul filtre stable conditionne l'entrée dans un dataset lab.
- **Convention modulaire** `ml/sources/<source>/` + go-task uniformes
  `ml:src:<source>:{run,dry,limit,status}`.
- **Page détail `/sources/:id`** avec onglets Runs / Données /
  Couverture / Commandes.
- **Nouvelles sources prioritaires** : Catawiki, NumisCorner, CGB.
- **Capture images eBay** au passage des runs prix existants.

## Hors-scope explicite

- **Résolution automatique listing → eurio_id robuste** — voir
  `open-problems.md`. On code la résolution naïve actuelle, on
  documente le problème.
- **Migration des données existantes** — les images Numista déjà
  fetched restent dans `coin_images` canonique. On ne backfille pas
  `image_assets` avec l'historique.
- **eBay sold listings (Marketplace Insights API)** — payant, à
  traiter quand l'accès sera disponible.
- **Refonte du label space** — orthogonal au refacto `lab-prod-refacto`,
  qui reste prioritaire pour le training.
- **Distribution des images Catawiki/eBay hors training** — flag
  `redistributable = false` interdit toute sortie hors lab.

## Lien avec les autres refactos

- **`docs/lab-prod-refacto/`** (label space + isolation lab/prod) :
  orthogonal. Cette refacto alimente les datasets via les nouvelles
  tables, mais ne touche pas au label space ni à la promotion.
- **`docs/training-pipeline/refacto/`** (UX du lab) : orthogonal aussi.

Si un agent doit choisir : `lab-prod-refacto/phase-1` (label space)
reste prioritaire sur tout. Cette refacto-ci passe ensuite.

## Workflow agent

Un agent qui démarre une phase doit :

1. Lire [`analysis.md`](./analysis.md) (état actuel par source).
2. Lire [`schema.md`](./schema.md) et [`module-contract.md`](./module-contract.md).
3. Lire la phase qu'il implémente.
4. À la fin de la session, **append** une entrée datée dans
   [`progress.md`](./progress.md).
