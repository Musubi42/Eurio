# Suivi des travaux — Refacto `ml/`

> Fichier vivant. Décisions dans [`adr.md`](./adr.md), vision dans [`README.md`](./README.md),
> cadrage de session dans [`kickoff.md`](./kickoff.md). À annoter au fil de l'eau : statut, ce qui s'est
> bien/mal passé, problèmes rencontrés. Statuts : ⬜ à faire · 🟡 en cours · ✅ fait · ⚠️ fait avec réserve.

## 🔄 Reprendre dans une nouvelle session

**État au 2026-06-07** : chunks **1 à 4 livrés** (l'exigence n°1 du chantier — *les jobs survivent au
`--reload` de l'API* — est **résolue** : training, iteration/Lab complet, scrape, recrop cohorte et bake
d'augmentation tournent tous en subprocess détachés). Reste : **5 (split Store)** → 6 (libSQL) → 7
(restructure) → 8 (purge scripts).

**Prompt de redémarrage (à coller)** :
> Lis `docs/refacto-ml/suivi.md` (état du chantier refacto ML) + `adr.md`. Les chunks 1-4 sont livrés
> (rail `jobs/` + tout le Lab détaché + bake augmentation détaché). On reprend au **chunk 5 : split de
> `ml/state/store.py` (2705 lignes) en `ml/store/connection.py` + modules de requêtes par domaine**, en
> gardant `eurio.db` unique et `from state import Store` fonctionnel. Doctrine : chunks 30 min-3 h livrés
> + audit, vérifier sur le code, pas de dette (R0). Commence par me proposer le découpage de Store avant de coder.

**Point d'entrée chunk 5** : `ml/state/store.py` = god-node (176 edges, 2705 l). Contient (a) la classe
`Store` (connexion WAL/autocommit + `_bootstrap` qui `executescript` `schema.sql` + ~100 méthodes par
domaine) et (b) des fonctions module-level (`cohort_job_*`). Découpe candidate : `store/connection.py`
(plumbing + bootstrap) + mixins/modules `store/{training,cohort,sources,review,canonical,jobs}.py`.
**Contrainte dure** : `from state import Store` est importé partout → garder l'API publique de `Store`
identique (mixins composés, ou `state/__init__` ré-exporte depuis `store/`) ; la migration des imports
`state→store` est reportée au chunk 7 (restructure). À trancher en début de chunk 5.

## Ordre des chunks

L'ordre validé (jobs → store → libSQL → restructure → purge) est conservé ; « jobs » est affiné en 4
sous-chunks pour garder une cadence d'audit (poser le rail, puis migrer un runner à la fois).

| # | Chunk | Statut | Notes / problèmes |
|---|---|---|---|
| 1 | **Rail `jobs/`** — table générique `jobs` (additive), lanceur détaché (`start_new_session`+pid+log), reaper boot générique, tests, câblage startup. Aucun runner migré. | ✅ | `ml/jobs/{db,runner,reaper,__init__}.py` + table `jobs` dans `schema.sql` + hook `_jobs_startup` dans `server.py`. 7 tests verts, cohorte non régressé. `launch` prend un `cmd_builder(job_id)` (le child reçoit toujours son id). `job_latest` départage par `rowid DESC` (datetime résolution seconde). |
| 2 | **Détacher tout le Lab → `jobs/`** (fusion ex-2+3). Découverte : DEUX orchestrateurs in-process (`TrainingRunner._execute` + `IterationRunner._run_full_chain`), tous deux meurent au reload. Décision PO : détacher **les deux**. Stagé : 2a extraction `TrainingPipeline` · 2b-1 training legacy détaché · 2b-2 iteration détaché. | ✅ | **2a** extraction `TrainingPipeline` (hooks). **2b-1** `run_pipeline.py` détaché + lectures fichier/pid/table + bug zombie-stop corrigé. **2b-2** `run_iteration.py` détaché (chaîne stage→train→bench→verdict hors API), `launch_*`→`jobs.launch`, `is_busy`/`stop`/`recover_on_boot`/`tail_logs` rebranchés job/pid/fichier, `_launch_training`→`TrainingPipeline` synchrone ; `jobs.stop_process_group`+`proc_dead` factorisés dans le rail ; machinerie in-process supprimée (`_start_run_inprocess`/`_active`/`stop_active` morts retirés). **Tout le Lab survit au reload.** 64 tests verts (+5 iteration détaché), 1 échec pré-existant non lié. |
| 3 | _(fusionné dans #2)_ | ✅ | Scrape eBay déjà détaché via `source_runs`+thread sources (réconcilié in-row, survit au reload — cf. `_reconcile_scrape_jobs`). Rien à migrer ; le sujet réel était le Lab (training+iteration), traité en #2. |
| 4 | **Bake d'augmentation détaché** (« Générer » standalone). Découverte : le bake par itération était déjà détaché (2b-2) ; restait le standalone **3 endpoints** synchrones-dans-la-requête (`/bake`, `/augmentations/regenerate`, `/preview-iteration`). Décision PO : détacher le littéral (frontend inclus). | ✅ | `training/run_augmentation.py` détaché via rail (clear+generate, progress n_done/n_total). Les 3 endpoints → **202 `{job_id}`** + endpoint statut `…/augmentations/job`. `generate_for_iteration` a un `on_progress` optionnel. **Fix correctness** : `job_by_param` filtre désormais par `kind` (un même `iteration_id` porte chaîne `iteration` ET bake `augmentation`) — `IterationRunner._active_job`/`tail_logs` filtrent `kind='iteration'`. Front : `useLabApi` poll jusqu'à `done` → l'`isPending` des mutations couvre le bake (**spinner inchangé, zéro changement de composant**). Garde anti-double-bake (PID vivant). 65 tests back verts (+1 kind-filter), typecheck front = 0 nouvelle erreur (7 pré-existantes). |
| 5 | **Split `Store`** → `store/connection.py` + modules par domaine. | ✅ | Prépare le swap driver du chunk 6. **5a** scaffold `ml/store/` plat + shim `state/store.py`. **5b** `_domains.py` carvé en 8 modules mixins (runs/staging/augmentation/benchmark/cohorts/iterations/dino/listing_signals), chacun = ses rows + converter + `*Mixin`. `Store(StoreBase, RunsMixin, …)`. 1068 passed / 20 failed (= baseline, 0 régression). |
| 6 | **Cross-machine eurio.db** : ~~libSQL~~ → **lease MinIO**. | 🟡 | libSQL abandonné (client Python sans row_factory/create_function/executescript — cf. ADR D4 révisé). **6a livré** (`store/lease.py` + `go-task ml:db:{status,acquire,release,steal}` + 13 tests, FakeS3 IfNoneMatch). **6b livré** (doc VPS `chunk6-vps-minio.md`). **6c livré** (hook startup `server.py` qui avertit, non bloquant). **Reste : exécution côté VPS** (provisioning MinIO via la doc) puis 1ᵉʳ acquire/release réel Mac↔PC. |
| 7 | **Restructure `ml/` plat** : sources/vision/training/review/serving/shared ; absorbe scan/eval/foundation/augmentations ; api→serving ; fix imports + Taskfile + tests. | ⬜ | Le gros morceau ; ne déplace que le legacy (jobs/ et store/ déjà à leur place). |
| 8 | **Purge `scripts/`** : one-time → archive/suppression, ne garder que les scripts opérables. | ⬜ | — |

## Invariants à ne pas casser (R0)
- Un seul `eurio.db` (SQLite-only), connexion WAL + `isolation_level=None` autocommit.
- `review_queue` UNIQUE(image_asset_id) → UPSERT, jamais 2e INSERT (cf. `feedback_store_autocommit_unique`).
- Le recrop cohorte multi-pièces saute le lot (garde `recrop_ebay_refine`) — ne pas régresser.
- `serving/` reste mince : enqueue + read status, zéro métier.

## Findings clés (à retenir pour la suite)
- **Le pattern de référence du rail est le recrop cohorte** : `start_new_session=True` + `pid` en table +
  reaper boot `os.kill(pid,0)`. Tout le reste s'y rallie. Le rail générique vit dans `ml/jobs/`.
- **`eurio.db` est bi-writer** (Mac écrit cohort/référentiel, PC écrit `runs/epochs/steps` via `training_runner`)
  mais sur **tables disjointes** et en **séquentiel temporel** → justifie libSQL (sérialise les écritures côté primaire).
- **Le scrape eBay survivait déjà au reload** (thread sources + `source_runs` réconcilié in-row, `_reconcile_scrape_jobs`).
- **`training.db` est un vestige** (backups figés mai, plus ouvert) — candidat suppression au chunk 8.
- **Liaison run/job/iteration↔job via `params` JSON** (`jobs.job_by_param(conn, key, value, kind=…)`). Le
  filtre `kind` est **obligatoire** : un même `iteration_id` est porté par la chaîne `iteration` ET le bake `augmentation`.
- **Lecture d'état des jobs détachés** : table (`training_runs`/`experiment_iterations`) + row `jobs` (pid/status) +
  **fichier de log** (`state/job_logs/<kind>-<job_id>.log`, tail). Plus aucun buffer mémoire dans l'API.
- **Stop d'un job détaché** = `jobs.stop_process_group(pid)` (SIGTERM→SIGKILL au **groupe**, le child est leader de session).
- **Admin Vue exempté de proto-first** (`feedback_proto_first`) → édition directe OK (fait au chunk 4).
- **`scripts/` = 106 fichiers**, beaucoup one-time → purge au chunk 8.

## Bugs & dette à traiter (fin de refacto, sauf mention)
- 🐛 **CORRIGÉ (chunk 2b-1)** — *Détection zombie au stop* : `os.kill(pid,0)` voit un enfant zombie « vivant »
  → faux timeout → SIGKILL `PermissionError`. Fix : `jobs.proc_dead()` via `waitpid(WNOHANG)`-reap + fallback `kill(0)`.
- ⚠️ **`datetime.utcnow()` deprecated** dans `ml/training/pipeline.py` (copié verbatim de l'ancien code) →
  `DeprecationWarning`. Migrer vers `datetime.now(timezone.utc)` en passant (chunk cleanup ou 7).
- ⚠️ **7 erreurs TypeScript pré-existantes** (`admin/packages/web`, `vue-tsc --noEmit`) **hors périmètre refacto**,
  à nettoyer en fin : conversions `Coin[]` (`useStagedCoins.ts:45`, `useArbitrage.ts:85`, `CuratedMembersPicker.vue:50`,
  `useCriteriaPreview.ts:86`), `Json` deep-instantiation (`AuditPage.vue:29` ×2), `computed` inutilisé (`PerConditionTable.vue:2`).
  *Baseline confirmée par stash : aucune n'est due à la refacto.*
- ⚠️ **Test pré-existant rouge** : `ml/tests/test_lab_api.py::test_create_cohort_rejects_empty_ids` (validation
  cohorte vide, renvoie 200 au lieu de 400) — **non lié à la refacto** (échoue aussi sur `main`/base). À investiguer en passant.
- 🧹 **Types front orphelins** : `BakeResult` + `RegenerateAugmentationsResult` (`admin/.../lab/types.ts`) plus
  utilisés après chunk 4 — laissés (retrait cascaderait sur `BakeReport`). Retirer au passage si on touche ce fichier.
- 🧹 **`PipelineHooks` sans consommateur prod** : extraits au chunk 2a, plus utilisés qu'en tests (le détaché n'a
  pas de hook). Extension-point propre + testé → gardé sciemment ; supprimer si jamais inutile au chunk 7.
- ❓ **`cohort_jobs` vs table `jobs` générique** : coexistent. À fondre (vue/spécialisation) ou garder séparé — à
  trancher quand le recrop cohorte sera (ou non) rallié au rail. Question ouverte de l'ADR.
- 🧹 **Stop du training `/runs`** : pas de route stop (n'a jamais existé) ; `TrainingRunner.stop_active` retiré comme
  code mort. Mécanisme prêt (`jobs.stop_process_group`) si on veut ajouter le bouton (~10 l de route).
- 🎨 **Progression bake augmentation** : `n_done/n_total` exposés par `…/augmentations/job` mais l'UI ne montre
  qu'un spinner. Barre de progression possible (nice-to-have).

## Journal
- **2026-06-08** — **Chunk 6 (Mac/PC + doc VPS) livré ; libSQL abandonné**. Vérif du client
  Python libSQL → `row_factory`/`create_function`(phash)/`executescript` non implémentés ⇒ swap
  driver = shim fragile (dette R0). Bascule actée sur **lease MinIO** (ADR D4 révisé). **6a** :
  `store/lease.py` (acquire/release/status/steal, verrou atomique `PutObject(IfNoneMatch='*')`,
  pull/push sha-vérifié, suppression -wal/-shm anti-corruption, marqueur local) + `go-task
  ml:db:{status,acquire,release,steal}` + 13 tests (FakeS3 en mémoire). **6b** : doc handoff VPS
  `chunk6-vps-minio.md` (créer bucket `eurio-db`, versioning, vérif conditional-writes, policy,
  seed). **6c** : hook `_db_lease_startup` dans `server.py` — **avertit** seulement (verrou tiers /
  divergence locale), best-effort (silencieux si MinIO injoignable), jamais d'acquire auto.
  Décisions PO : tout **manuel**, **steal manuel** (pas de heartbeat). `store/connection.py` reste
  `sqlite3` pur (zéro perte de compat). Tests : **1081 passed / 20 failed = baseline, 0 régression**.
  **Reste** : exécuter le provisioning côté VPS (session Claude dédiée via la doc) puis 1ᵉʳ
  acquire/release réel. Prochain chunk repo : **7 (restructure plate)**.
- **2026-06-08** — **Chunk 5b livré → chunk 5 clos**. `store/_domains.py` (transitoire) carvé en
  **8 modules par domaine**, chacun co-localisant ses dataclasses + son converter `_row_to_*` + son
  mixin : `runs.py` (RunsMixin + Run/Step/Epoch/ClassMetricRow), `staging.py` (StagingMixin, pas de row),
  `augmentation.py` (recipes+aug_runs), `benchmark.py`, `cohorts.py`, `iterations.py` (iteration+aug_vs_real
  +live_test), `dino.py`, `listing_signals.py`. `store/__init__.py` compose
  `class Store(StoreBase, RunsMixin, StagingMixin, AugmentationMixin, BenchmarkMixin, CohortsMixin,
  IterationsMixin, DinoMixin, ListingSignalsMixin)`. **Carving ast-based depuis l'original git** (ranges
  par méthode/dataclass, zéro retranscription) ; imports par module dérivés des tokens réellement
  utilisés (scan AST : **0 import inutile**). MRO vérifiée (aucun shadowing inter-mixin), identité `Store`
  préservée sur les 3 styles d'import. **Tests : 1068 passed / 20 failed = baseline à l'identique, 0
  régression.** Tailles : connection 555 l, runs 428, iterations 417, benchmark 272, augmentation 244,
  dino 190, listing_signals 184, cohorts 157, staging 148, events 110, __init__ 70, cohort_jobs 68,
  common 40 (le god-node de 2705 l est dissous). Prochain : **chunk 6 (libSQL)** — le swap driver se
  localise dans `store/connection.py`.
- **2026-06-08** — **Chunk 5a livré** : `Store` scindé en package plat `ml/store/`
  (`connection.py` = socle `StoreBase` plumbing+bootstrap+`_register_phash_udfs` ; `common.py` =
  `ClassRef`+`_dump_refs/_load_refs/_optional_column` ; `events.py` = `emit_state_event` ;
  `cohort_jobs.py` = `cohort_job_*` ; `_domains.py` transitoire = rows+converters+`_DomainsMixin`
  (toutes les méthodes métier) ; `__init__.py` = `class Store(StoreBase, _DomainsMixin)`).
  **Carving programmatique** (script ast/line-range, zéro retranscription manuelle). `state/store.py`
  devient un shim `from store import *` (+ ré-export explicite de `_register_phash_udfs`/`StoreBase`/
  `_SCHEMA_PATH`). API publique de `Store` identique (`Store` est le **même objet** via les 3 styles
  d'import : `from state import` / `from state.store import` / `from store import`). `pyproject.toml` :
  `store*`+`jobs*` ajoutés à `packages.find.include` (jobs* était omis). **Tests : 1068 passed / 20
  failed** = baseline pré-split à l'identique (sous-ensemble des 20 failing : 19 failed/110 passed
  AVANT==APRÈS) ; les 20 sont pré-existants (live-DB `test_wipe_referential`, `ModuleNotFoundError:
  evaluate_real_photos` dans `test_benchmark`, détection `test_normalize_listing`, le `test_create_cohort_rejects_empty_ids` déjà connu). `state/schema.sql` reste sous `state/` (réf. via chemin relatif depuis `store/connection.py`), migration des imports `state→store` reportée au chunk 7. En attente d'audit avant **5b**.
- **2026-06-07** — ADR acté, suivi créé. Démarrage chunk 1.
- **2026-06-07** — Chunk 1 livré : rail `jobs/` posé (table additive, lanceur détaché, reaper, 7 tests verts), zéro runner migré, zéro régression. En attente d'audit avant chunk 2.
- **2026-06-07** — Chunk 2 cadré : 2 orchestrateurs in-process découverts (training + iteration), décision PO = détacher les deux. Stagé 2a/2b. **2a livré** (extraction `TrainingPipeline` behavior-preserving, 53 tests verts).
- **2026-06-07** — **2b-1 livré** : training legacy `/runs` détaché (survit au reload), lectures fichier/pid/table, bug zombie-stop corrigé. 59 tests verts.
- **2026-06-07** — **2b-2 livré** : chaîne iteration entièrement détachée (`run_iteration.py`), `jobs.stop_process_group`/`proc_dead` factorisés, machinerie in-process supprimée (zéro dualité). **Chunk 2 clos** — tout le Lab survit au reload. 64 tests verts.
- **2026-06-07** — **Chunk 4 livré** (cross-stack) : bake d'augmentation standalone détaché (3 endpoints → 202+job, statut, `run_augmentation.py`), `job_by_param` filtré par kind, front en poll-until-done (spinner inchangé). 65 tests back + typecheck front clean. Prochain : chunk 5 (split Store, chemin critique libSQL).
- **2026-06-07** — **Handoff context-window** : exigence n°1 résolue (chunks 1-4, tous les jobs survivent au reload).
  Suivi enrichi (reprise + findings + bugs/dette + point d'entrée chunk 5). Rien en cours, working tree propre côté
  refacto (à committer si voulu). Reprendre au chunk 5 via le prompt en tête de fichier.
