# Plan — Harmonisation des données Eurio

> Découpage en chunks du chantier décrit dans `architecture.md`.
> Règle de travail : un chunk = 30 min – 3 h, livré puis **rétro avant le
> suivant**. Pas d'enchaînement sans « go ».

## Chunk 0 — Fondations ✅ (livré 2026-05-22)

Pas de changement de sémantique de données — renommage + docs.

- [x] Backup `eurio.db` daté (`ml/state/training.db.bak-20260522-2310`).
- [x] Renommage `training.db` → `eurio.db` : fichier + 38 fichiers code/config
      (`*.py`, `Taskfile.yml`, `rsync-from-mac.sh`), env var
      `EURIO_TRAINING_DB` → `EURIO_DB`, `.gitignore`.
- [x] `eurio.db` retiré du tracking git (binaire, désormais ignoré).
- [x] Docs `architecture.md` + `plan.md` + kickoff déplacé dans
      `docs/data-harmonization/`.

## Chunk 1 — Schéma SQLite canonique

### 1a — Conception du schéma ✅ (livré 2026-05-22)

- [x] Spec `schema-design.md` rédigée, **auditée par un expert DB**, finalisée :
      `referential_catalog`, `coins` (refonte), `design_groups`,
      `coin_national_variants`, `coin_cross_refs`, `coin_observations`,
      `coin_canonical_images`, `cohort_members`, `eurio_id_migrations`,
      `image_assets.origin`, vue QA `v_orphan_eurio_refs`.
- [x] Séquence de migration one-shot guardée définie (rebuild `coins`).

### 1b — Implémentation schéma + migration ✅ (livré 2026-05-22)

- [x] DDL des nouvelles tables dans `schema.sql` + colonnes canoniques de
      `coins` + vue QA `v_orphan_eurio_refs`.
- [x] `Store._bootstrap` : `_ensure_column` des colonnes nouvelles + index —
      **pas de rebuild de `coins`** (migration non destructive, ALTER seulement,
      cf. `schema-design.md` §Ajustements Chunk 1b).
- [x] Script `scripts/migrate_canonical_schema.py` (+ go-task) : backfill des
      colonnes depuis `raw_payload_json`, remplissage des tables filles,
      backfill `cohort_members` (tolère les orphelins), `image_assets.origin`.
- [x] Dry-run, backup auto, idempotent. **Appliqué** : 2628 coins backfillées,
      3233 cross-refs + 3606 observations + 877 images décomposées, 24
      cohort_members, 1961 `origin='collected'`. `foreign_key_check` CLEAN.
      Zéro régression (78 tests coins/store/ebay verts ; 19 échecs pré-existants
      indépendants).

> La règle de dérivation du slug `eurio_id` est traitée au Chunk 2 (génération).

## Chunk 2 — Génération `numista_catalog → coins`, retrait du matcher flou

- Ingestion : catalogue source référentielle → table `numista_catalog`.
- Génération directe 1:1 `numista_catalog → coins` sur `numista_id`.
- Retrait de `batch_match_numista.py` (matcher flou) et de la couche
  d'arbitrage devenue inutile.
- **Fix BE 2017** : `be-2017-2eur-…-ghent-university` (numista 124813) +
  création de `be-2017-2eur-…-university-of-liege` (numista 108778).

## Chunk 3 — Couche cycle de vie

- Colonne `status` matérialisée sur `coins` (`referenced` / `trained`).
- Commande idempotente de recalcul, déclenchée sur événement (fin de run, sync).
- Condition calculée « éligible cohorte » (assez d'images).

## Chunk 4 — Projections descendantes rebranchées sur `eurio.db`

- `sync_to_supabase` lit `eurio.db` au lieu du JSON.
- `export_catalog_snapshot` inchangé en aval mais cohérent avec le nouveau
  `coins` ; embarque le `status`.
- `eurio_referential.json` devient un export généré optionnel.
- Détection de dérive : commande comparant Supabase / snapshot au canonique.

## Chunk 5 — Migration d'identité + ré-épinglage des dérivés

- Journal de migration `eurio_id` (rename / split / merge).
- Ré-épinglage gold du bench + cohortes ; rejeu BE 2017 du gold (~28 entrées
  2017, cf. studio bench chunk 3).
- Re-bench.
