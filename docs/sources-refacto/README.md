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
| **Voir les choix figés (à lire en premier)** | [`decisions.md`](./decisions.md) |
| Comprendre l'état actuel par source | [`analysis.md`](./analysis.md) |
| Voir le schéma DB cible (DDL) | [`schema.md`](./schema.md) |
| Écrire un nouveau module source | [`module-contract.md`](./module-contract.md) |
| Comprendre le filtrage qualité photos | [`quality-pipeline.md`](./quality-pipeline.md) |
| Designer la review queue humaine | [`review-queue.md`](./review-queue.md) |
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
| 1 | [Fondations](./phase-1-foundations.md) | Tables, base modulaire, refacto eBay, **review queue V0** | **Oui** — toutes les phases en dépendent | 🔲 |
| 2 | [Nouvelles sources](./phase-2-new-sources.md) | Catawiki, NumisCorner, CGB | Non | 🔲 |
| 3 | [Pipeline qualité photos](./phase-3-quality-pipeline.md) | Score + flag `training_eligible`, intégration dataset prepare | Non, parallélisable à phase 2 | 🔲 |
| 4 | [Admin UX](./phase-4-admin-ux.md) | Page détail `/sources/:id`, cards enrichies | Non | 🔲 |

**Phase 1 est urgente** parce qu'elle pose le contrat. Tant qu'elle
n'est pas faite, ajouter une nouvelle source ou enrichir l'admin
revient à empiler de la dette.

## Décisions actées

Le détail figé se trouve dans [`decisions.md`](./decisions.md). Vue
résumée :

- **D-01** Label space = `eurio_id` (pas `design_group`).
- **D-02** `eurio_id` nullable post-fetch ; résolution 3 niveaux
  (`auto_name` v1, `auto_dino` futur, `manual` toujours dispo).
- **D-03** Multi-coin lots : on capture, on splitte en N crops, pas
  de quote pour les lots.
- **D-04** Quotes non résolues stockées dans `pending_quotes`,
  promues vers `coin_market_quotes` à la résolution image.
- **D-05** Quotas + runs en SQLite (`ml/state/training.db`), pas de
  fichiers JSON.
- **D-06** Mac (dev) ↔ PC (training) : pas de DB partagée, sync
  via export.
- **D-07** Dédup pHash, propagation auto de label.
- **D-08** Anti-leakage DinoV2 : bench protégé.
- **D-09** Review queue minimale dès phase 1.
- **D-10** Filtre `redistributable=false` codé dès phase 3.
- **D-11** `face='obverse'` only pour le training.
- **D-12** Schéma split `source_images` (raw) + `image_assets`
  (crops).

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
