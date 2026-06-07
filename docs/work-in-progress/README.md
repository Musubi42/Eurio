# Work in progress — chantiers à reprendre et clore

> Chantiers démarrés selon le workflow « doc d'abord, puis implémentation »,
> mais **pas encore 100 % finis** (arrêtés en cours, évolués, ou idées en suspens).
>
> Delta **doc ↔ code mesuré via graphify le 2026-06-07** (graphe de la codebase).
> Le `%` reflète ce que le code montre réellement, pas ce que la doc prétend.
>
> **Boucle cible** : reprendre → finir le reste listé ci-dessous → déplacer vers `docs/archive/`.

| Chantier | % réel | En une phrase |
|---|---|---|
| [lab-prod-refacto](./lab-prod-refacto/) | ~95 % | 4 phases closes, reste du cleanup cosmétique |
| [coin-richness](./coin-richness/) | ~85 % | presque fini, reste run eBay sur cohorte + scale 524 |
| [data-harmonization](./data-harmonization/) | ~85 % | tout livré sauf le Chunk 5 (migration identité) |
| [lab-streamline](./lab-streamline/) | ~85 % | reste eBay-standards + gros run PC 16 classes |
| [cohort-capture-flow](./cohort-capture-flow/) | ~85 % | flow live, reste vérifier les chemins post-rename |
| [best-frame-capture](./best-frame-capture/) | ~80 % | chunks 1-6 livrés (README périmé), reste chunk 7 |
| [design-groups-standards](./design-groups-standards/) | ~80 % | pilote BE live, reste le rollout autres pays |
| [harmonisation-images](./harmonisation-images/) | ~60 % | code prêt mais migration jamais lancée |
| [crop-forensics](./crop-forensics/) | ~55 % | sujet actif, reste l'auto-rejet (S7) |
| [crop-quality-overhaul](./crop-quality-overhaul/) | algo livré | reste sessions Android + tooling review manuel |
| [referential-fixes](./referential-fixes/) | discovery livré | reste Apply backend + UI admin |
| [cohort-pipeline](./cohort-pipeline/) | ~40 % | rebuild cockpit pas commencé, design seulement |
| [parity](./parity/) | ~30 % | QA dump fait, parité Maestro↔Playwright différée |

---

## lab-prod-refacto — ~95 % ✅ quasi clos
4 phases fonctionnellement closes (2026-05-02) : `promote_iteration.py`, `promote_prod_assets.py`,
`build_cohort_bundle.py`, `equivalence.py` live ; patch destructif retiré.
**Reste (cosmétique) :** retirer `_mirror_iter_outputs` de `iteration_runner.py` une fois les consommateurs migrés ·
sortir `cohort_meta.json` du bundle quand Android ne le lit plus · table `model_promotions` Supabase ·
colonnes `r_at_*_eq` sur `benchmark_runs` · confirmer la règle d'équivalence côté Android (cohort-test).

## coin-richness — ~85 %
Prep (P.*) + V.1-V.2 livrées (9 tables, scripts, page CoinDetail live).
**Reste :** V.3 (eBay discovery+prix sur cohorte 19) · V.4 (tour visuel 19 pages + GO/NO-GO scale 524) ·
Phase F (scale 524 coins, ~2000 calls Numista, multi-session) · archiver 4 scripts legacy P.9 ·
8 fichiers Vue lisent encore Supabase. ⚠️ source `wikipedia` seedée sans adapter `ml/sources/wikipedia/`.

## data-harmonization — ~85 %
⚠️ **`architecture.md` = design canonique verrouillé**, consulter même en cours.
Chunks 0-4 livrés. **Reste (Chunk 5, non démarré) :** driver migration d'identité (journal `eurio_id_migrations`
→ propager renames vers image_assets/cohort/bench) · re-pin bench gold · replay BE 2017 gold (~28 entrées) ·
re-juger 17 gold 2017 · i18n 147 coins générés · supprimer `batch_match_numista.py` · virer `training.db` fantôme.

## lab-streamline — ~85 %
README/BACKLOG synchros au code (CohortDrawer*.vue, triage-stats cohort_id live).
**Reste :** 05-ebay-standards (standards non scrapables, `v_ebay_freshness_groups` filtre `is_commemorative=1`) ·
chunk 06 gros run PC 16 classes ArcFace (non lancé) · lot-crop full park (414 img/1619 crops, 1 listing fait) ·
migration `coin_confusion_map` vers eurio.db (différée).

## cohort-capture-flow — ~85 %
Flow selection→CSV→adb push→sync (`sync_eval_real`) live dans `lab_routes.py` + `Taskfile.yml`.
**Reste :** vérifier que les chemins `ml/datasets/` collent au layout actuel post-rename eurio_id ·
nettoyer les TODO résolus de `session-kickoff.md` · confirmer le freeze auto `cohort.status` vs `CohortDetailPage.vue`.

## best-frame-capture — ~80 %
Chunks 1-6 livrés (ScanReducer 6 états, BestFrameSelector, CameraLockController, scorer, archive).
⚠️ README périmé (table « À écrire » alors que tout est codé).
**Reste :** vérifier chunk 7 (bench protocol + replay JSONL — fichiers présents, complétude à confirmer) ·
mettre à jour la table de statut du README · confirmer la table Room `coin_captures`.

## design-groups-standards — ~80 %
Doc fidèle au code (FK scalaire `coins.design_group_id` `schema.sql:935`, tooling `obverse_groups.py` + tests live).
Pilote BE (chunks 1-5) livré.
**Reste :** Chunk 6 rollout autres pays · gate parseur derive-then-diff · validation vision LLM par pays.

## harmonisation-images — ~60 %
Chunks 1-4/9 codés (cascade.py, local_cache.py, storage_status) mais **la migration n'a jamais tourné** (MinIO vide).
**Reste :** Bloc A (activer module NixOS `eurio-vps.nix` + rclone/pCloud + timer backup) ·
Bloc B (rsync Mac→VPS puis `migrate_to_minio`) · Chunk 5 (cache training pré-fetch, pas de code) ·
Chunk 6 (publication Supabase, routes renvoient encore FileResponse) · Chunk 8 (cleanup/rollback) · test E2E cascade.
⚠️ `TODO-handover.md` référence l'ancien chemin `~/dev/eurio/`.

## crop-forensics — ~55 % (sujet actif)
S1-S6 livrés/réfutés (composite score, sort buttons, scripts `ml/scripts/crop_exp/`).
**Reste :** S7 `auto_reject_reason` backend (2 seuils) · S8 score_v2 sort par défaut (optionnel) · S9 area_ratio adaptatif (pausé).

## crop-quality-overhaul — algo livré, sessions restantes
`detect_bbox_refine` shippé (crop eBay ~92 %). _(NB : le doc pointe `ml/sources/_base/steps/` mais le code vit dans `ml/scan/crop_detectors.py` — chemin périmé.)_
**Reste :** Session A (parité crop scan Android) · Session B (tooling review manuel pour la traîne).
⚠️ doublonne avec `operations/crop-bimetal-harden-session.md` — fusionner avant de lancer.

## referential-fixes — discovery livré, apply en attente
`discover_referential_fixes.py` + `referential_fix_apply.py` (logique `_mutate_db`) + `referential_fix_proposals.json` existent.
**Reste :** câbler l'endpoint apply dans l'UI admin · appliquer les 9 cas · confirmer cleanup Supabase + Storage.

## cohort-pipeline — ~40 % (rebuild pas commencé)
Tables `cohort_jobs`/`image_state_events` + `recrop-zero` live, mais le rebuild cockpit (`REBUILD-HANDOFF`) **n'a pas démarré**.
**Reste :** audit cycle de vie image en base (repro B1-B4) avant tout patch · modèle d'état SQLite explicite ·
redesign UX cockpit (frontend-design) · fixes B1-B5 · valider WS5 ccproxy · câbler census `nms_only`.

## parity — ~30 % (différé)
QA dump + buildType Android `src/qa` faits, tooling `admin/packages/parity/` scaffoldé (flows yaml, capture).
**Reste :** vérif device du build QA Android · pont interpréteur Maestro→Playwright (différé) · validation flow parité cross-platform.

---

> **Non déplacés (volontaire) :** `docs/sources-refacto/` (index vivant multi-sessions, déplacer casserait les cross-liens),
> `docs/training-pipeline/` (sprints 1-5 livrés mais dossier vivant : harvest/ + journal/ actifs — split différé).
> Références/ADRs gardés en place : `adr/`, `app-implem-phases/`, `research/`, `mission/`, `design/_shared/`.
