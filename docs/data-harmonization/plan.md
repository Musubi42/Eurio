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

## Chunk 2 — Réconciliation `referential_catalog ↔ coins`

### 2a — Ingestion + audit ✅ (livré 2026-05-23)

- [x] `scripts/ingest_referential_catalog.py` (+ go-task) : `coin_catalog.json`
      → table `referential_catalog` (688 types Numista : 625 commémo, 63 circ).
- [x] `scripts/audit_referential.py` (+ go-task) : audit **lecture seule**
      `referential_catalog ↔ coins`.

**Résultat de l'audit (2 € commémoratives)** — le diagnostic du kickoff,
quantifié : le référentiel est **159 commémoratives en retard** sur le
re-scrape Numista. 625 types Numista vs 466 pièces `coins`. 132 groupes
(pays, année) en écart, tous dans le sens Numista > coins. 0 orphelin,
0 pièce sans `numista_id`. **BE 2017 = 1 cas parmi 159** (Numista 2, coins 1).

### 2b — Génération des pièces manquantes + cas BE 2017 ✅ (livré 2026-05-23)

- [x] `scripts/generate_missing_coins.py` (+ go-task) : génère une pièce
      canonique pour chaque type Numista 2 € commémo absent de `coins`
      (slug via `compute_eurio_id` / `slugify`), images dans
      `coin_canonical_images`. Backup auto, idempotent.
- [x] **148 commémo générées** (sur 159). Les **11 restantes** sont des
      *doublons de variante* : Numista a 2 type-ids pour une même pièce déjà
      présente (ex. 131881/131882 Saint-Jacques-de-Compostelle) → détectés
      en collision, **non générés** (relève du référentiel V2 Type/Variant).
- [x] **Cas BE 2017 réglé** : la pièce `…-ghent-university` (numista 108778 =
      Liège) renommée en `…-of-the-university-of-liege` (ses tables filles
      re-pointées) ; le type Ghent (124813) créé par la génération en
      `…-of-the-university-of-ghent`. 3 lignes au journal `eurio_id_migrations`
      (retire + 2 split, `needs_rematch`). `foreign_key_check` CLEAN.
- [x] Audit post-génération : `count_mismatch` 132 → **11** (les variantes).
      Zéro régression (101 tests verts, 1 échec pré-existant).

**Worklist BE 2017** (kickoff) :
- [x] `groups.json` du studio bench régénéré (`scripts/regen_bench_groups.py`
      + go-task).
- [x] **i18n + aliases de `…-of-ghent` patchés** (`scripts/patch_be2017_ghent_i18n.py`).
      Au passage, découverte : les 4 « aliases » de Liège étaient en fait
      `gent/ghent/gand/gante` (héritées de l'ancien slug) — migrées vers le
      coin Ghent où elles ont du sens. Le matcher distingue maintenant
      Gand/Liège.
- [x] **Studio bench — affichage des raisons** : sous chaque filtre du funnel,
      la ventilation par motif ; sur chaque carte annonce, une ligne
      « Filtre 1 — <motif> » / « Match → <tokens> » / « Contradiction : … »
      (la donnée existait déjà dans `accept.reason` / `matcher.matched`,
      pas affichée).
- [ ] Ré-juger les 17 entrées gold / 13 labels 2017 (`needs_rematch`) — tâche
      **humaine** dans le studio bench. Puis `ingest` + `replay`.
- [ ] **i18n manquant pour les 147 autres pièces générées au Chunk 2b** —
      session multi-agent dédiée (la stratégie i18n du repo l'autorise via
      LLM source='llm_v1' + scrape Numista FR/EN).
- [ ] Retrait de `batch_match_numista.py` (matcher flou désormais inutile).

> La génération **complète** depuis Numista (éclatement par millésime des
> pièces de circulation — 1 type Numista = N années ; doublons de variante)
> est gated sur un scrape de l'endpoint Numista « issues » et le référentiel
> V2 : chantiers distincts, hors de ce plan d'harmonisation.

## Chunk 3 — Couche cycle de vie ✅ (livré 2026-05-23)

- [x] `scripts/port_design_groups.py` (+ go-task) : rapatrie les
      `design_groups` Supabase → `eurio.db` (18 groupes, 115 affectations
      `coins.design_group_id` ; 21 orphelins logués). Prérequis du recalcul —
      et harmonisation : `design_groups` rentre dans le store canonique.
- [x] `scripts/recompute_coin_status.py` (+ go-task) : recalcul **total et
      idempotent** de `coins.status`. Une pièce est `trained` si elle est
      classe d'un run réussi, en direct (`class_kind='eurio_id'`) ou via son
      `design_group`. Peut promouvoir *et* rétrograder. → **68 pièces
      `trained`** (19 en direct + 49 via design_group), 2708 `referenced`.
- [x] Vue `v_coin_training_readiness` : base de la « condition d'éligibilité
      cohorte » (nb d'images d'entraînement par pièce ; seuil au consommateur).
- [x] `foreign_key_check` CLEAN, idempotent, zéro régression.

> Wiring « recalcul en fin de run » : la commande est idempotente et appelable
> partout ; l'accrocher à la complétion d'un run dans `training_runner` est un
> ajout d'une ligne, à faire quand on touchera ce flux.

## Chunk 4 — Projections descendantes ✅ (livré 2026-05-23)

- [x] `export/sync_to_supabase.py` réécrit : lit `eurio.db` (au lieu de
      `eurio_referential.json` périmé). Flatten coins + tables filles →
      `coins`/`source_observations`/`coin_market_prices`. Upsert idempotent,
      jamais de delete. `--verify` post-sync spot-check 5 coins.
- [x] `scripts/detect_supabase_drift.py` (+ go-task) : compare lecture seule
      eurio.db ↔ Supabase, remonte 3 buckets (`supabase_only`, `eurio_only`,
      `field_drift`).
- [x] Matcher flou retiré (`batch_match_numista.py` + go-tasks), `sync` ne
      pousse plus `matching_decisions`/`review_queue` (artefacts historiques
      figés côté Supabase).
- [x] **Vérifié** : sync OK (coins 2776, observations 3963, market_prices 624),
      0 dérive de valeur, 460 orphelines Supabase pré-Chunk 2 (slug drift,
      sans risque — l'architecture pose `sync` upsert-only).
- [ ] `export_catalog_snapshot` : lit déjà Supabase qui est maintenant à jour →
      pas de refonte nécessaire ce chunk.
- [ ] Cleanup des 460 orphelines Supabase : optionnel, à décider plus tard.

> `eurio_referential.json` n'est plus la vérité. Si on veut le garder comme
> export portable (architecture), c'est un `SELECT → JSON` à écrire un jour.

## Chunk 5 — Migration d'identité + ré-épinglage des dérivés

- Journal de migration `eurio_id` (rename / split / merge).
- Ré-épinglage gold du bench + cohortes ; rejeu BE 2017 du gold (~28 entrées
  2017, cf. studio bench chunk 3).
- Re-bench.
