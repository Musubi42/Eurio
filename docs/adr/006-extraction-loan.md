# ADR-006 — `loan/` extrait dans son propre dépôt

**Date :** 2026-08-14
**Statut :** 🟡 Proposée — principe validé par le PO, dépôt cible non créé

## Contexte

**Ce que fait `loan`** (à graver, l'information n'existait nulle part) : emprunter des
pièces physiques à des amis et connaissances pour les photographier et enrichir le
dataset — puisqu'il est impossible de posséder les milliers de pièces euro existantes.

Le lien avec Eurio est **au niveau de la donnée** : la page admin d'Eurio liste les pièces
avec des filtres (possédée / non possédée / **prêtée** / non prêtée). C'est `loan` qui
alimente l'axe « prêtée », et qui évite de demander à un ami une pièce déjà détenue —
nuance retenue par le PO : un second exemplaire garde de la valeur si l'état d'usure diffère.

État du couplage, vérifié :

- **Un seul lien de code** : `loan/src/app/globals.css:2` → `@import "../../../shared/tokens.css"`.
- Aucun import de code Eurio. `node_modules` et lockfile propres, **hors du workspace pnpm**.
  Sa propre doc l'affirme : *« le code dans `loan/src/` n'importe jamais rien »*.
- Aucun code Eurio ne référence `loan/` : seulement 4 tâches wrapper dans `Taskfile.yml`
  (`loan:build-catalog`, `loan:dev`, `loan:env-check`, `loan:deploy`).
- Les données transitent par **Supabase** : `loan/scripts/build-catalog.ts` lit
  `coins` + `coin_market_prices` avec `SUPABASE_SERVICE_ROLE_KEY` et produit
  `loan/public/catalog.json` (gitignoré).

⚠️ **Divergence de schéma déjà présente** : `loan` lit la table **`coins`** (schéma v1 :
`face_value`, `images`) tandis que `ml/export/build_app_core.py` lit **`coin`** (schéma v2 :
`face_value_cents`, `shared_reverse_id`). Les deux consommateurs ont déjà dérivé.

## Décision

Extraire `loan/` dans son propre dépôt, sous un dossier parent commun avec Eurio.

Deux ruptures à traiter :
1. **La ligne de CSS** — vendorer `tokens.css`, ou consommer le futur package
   `@eurio/tokens` ([ADR-007](./007-pas-de-split-eurio-avant-artefacts.md)).
2. **L'alimentation en données** — basculer de Supabase vers **MinIO**, conformément à la
   cible « la donnée va sur MinIO ».

## Alternatives considérées

| Option | Verdict |
|---|---|
| Garder `loan` dans le monorepo | Pollue chaque recherche, indexation et `grep` ; produit distinct, cycle de vie distinct |
| Extraire en gardant l'alimentation Supabase | Rate l'occasion : garde un consommateur du `service_role` et fige la divergence v1/v2 |
| **Extraire + alimentation MinIO** | Détache, débranche du Supabase mourant, supprime un usage du `service_role` |

## Conséquences

- Trois gains d'un seul geste : dépôt propre, un consommateur de `service_role` en moins,
  et un pas vers le retrait de Supabase.
- Les 1147 images non trackées de `loan/` sortent du périmètre d'indexation d'Eurio.
- **Question ouverte** : `loan` doit-il lire le **même artefact `app_core`** que l'app
  Android (et donc passer au schéma v2), ou garder son propre `catalog.json` publié pour
  lui ? La première option supprime la divergence, la seconde coûte moins tout de suite.
- Le dossier parent n'est pas encore nommé.
