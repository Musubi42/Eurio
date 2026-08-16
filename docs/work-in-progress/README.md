# Work in progress — chantiers à reprendre et clore

## 🎯 Focus actuel (2026-08-16) — par où commencer

> **Un agent qui arrive lit CE bloc, pas tout le reste.**

**Point de reprise : [`HANDOFF-2026-08-16.md`](./HANDOFF-2026-08-16.md).** Le Lab
est redevenu utilisable de bout en bout (cohorte → bake → entraînement), mais
l'entraînement ne tourne que dans un **mode compute explicite** : la place des
`training_runs` sous Direction A est **la décision qui bloque la suite**, et elle
est posée avec ses trois options dans ce handoff.

**Avant de toucher au code, charge les skills du repo** (`.claude/skills/`,
indexées dans `CLAUDE.md`) : le devShell pose le flip Direction A — une écriture
locale échoue par défaut, et c'est le piège n°1 du dépôt.

<details>
<summary>Focus précédent (2026-08-14) — remise au propre du dépôt</summary>

**En cours : [`repo-refactor/`](./repo-refactor/) — remise au propre du dépôt.**
Sa section « Déjà établi » contient des faits vérifiés qui ont coûté cher à découvrir
(provenance du dataset, rôle de `best.pt`, quelles bases existent vraiment).
**Lis-la avant de lancer la moindre exploration.** État du système :
[`../architecture/README.md`](../architecture/README.md) · décisions :
[`../adr/README.md`](../adr/README.md).

**Chantier au front avant cette pause : [`scan-quality/`](./scan-quality/)** — tout
l'outillage est livré, il manque les **sessions de scan physiques** (corpus à 73 frames,
il en faut 400+). Voir `session-protocol-mix-owned-42.md`.

<details>
<summary>Focus précédent (2026-06-30) — conservé pour mémoire</summary>

1. **Model B est quasi clos.** Le canonique = SQLite sur VPS derrière l'API ;
   compute Mac/PC sur réplique locale ; images dans MinIO. **R1 (front fusionné)** et
   **R2 (réplique←VPS)** livrés + QA navigateur validée le 2026-06-30. Reste **R3**
   (finitions training `--push`, différé) et **R4** (débit review).
   → **Seul doc à lire : [`model-b/README.md`](./model-b/README.md)** (état + cible +
   roadmap + mode opératoire serveur + briefs R3/R4). Les docs de raisonnement sont
   dans `model-b/_archive/`.

2. **Objectif live : valider l'entraînement dans le lab.** But = lancer un **smoke
   training** (≈2 images/classe) sur Mac pour vérifier toute la plomberie post-Model-B
   (pull réplique VPS + images MinIO + écriture manifest + run), puis lancer la **run
   complète sur PC** ensuite. Pipeline : voir [`training-pipeline/`](./training-pipeline/)
   (sprints livrés) ; chemin de données amont = `model-b/README.md` §Données.

Le reste ci-dessous = catalogue des autres chantiers, à reprendre au besoin.

</details>

</details>

---

> Chantiers démarrés selon le workflow « doc d'abord, puis implémentation »,
> mais **pas encore 100 % finis** (arrêtés en cours, évolués, ou idées en suspens).
>
> Delta **doc ↔ code mesuré via graphify le 2026-06-07** (graphe de la codebase).
> Le `%` reflète ce que le code montre réellement, pas ce que la doc prétend.
>
> **Boucle cible** : reprendre → finir le reste listé ci-dessous → déplacer vers `docs/archive/`.

## Pour une session Claude Code autonome

Tu peux exécuter ces missions **seule**, en bouclant :

1. **Choisis une mission** dans la table ci-dessous (le `% réel` te dit la proximité de la clôture).
2. **Comprends le gap** : l'entrée détaillée liste le reste-à-faire. Confirme-le sur le code avec **graphify**
   (`graphify query "comment marche X"`, `graphify explain "Symbole"`, `graphify path "A" "B"`) — le graphe code+docs
   est dans `graphify-out/` (régénère avec `/graphify .` après un gros changement). Tu vois la big picture sans tout relire.
3. **Implémente** la brique manquante. Tu as les outils : `go-task` (build/install/test/snapshot), sous-agents
   (fan-out lecture/vérif), MCP (Supabase, MinIO), le skill `frontend-design` pour l'UI admin.
4. **Vérifie** (tests `ml/tests/`, `go-task` cibles, ou le skill `/verify`) puis **mets à jour cette entrée** :
   barre ce qui est fait, signale ce qui a encore drifté. Quand un chantier atteint 100 %, `git mv` vers `docs/archive/`.

> ⚠️ Avant d'agir sur une entrée : **re-vérifie le gap sur le code** (la doc peut avoir re-drifté depuis le 2026-06-07).
> Le `%` et le reste-à-faire sont une boussole, pas une vérité gravée.

| Chantier | % réel | En une phrase |
|---|---|---|
| ~~lab-prod-refacto~~ ([archivé](../archive/lab-prod-refacto/)) | ✅ clos | mirror `ml/output/` retiré + 4 sites repointés `prod/current` (2026-06-14, 36 tests verts) — archivé |
| ~~referential-fixes~~ ([archivé](../archive/referential-fixes/)) | ✅ clos | 9/9 cas DÉJÀ corrects en DB (re-bootstrap P.6), 0 apply — archivé 2026-06-14 |
| [cohort-pipeline](./cohort-pipeline/) | ~88 % | rebuild cockpit SHIPPÉ (B1-B5 fixés), reste validation PO lane UX + smoke run |
| [coin-richness](./coin-richness/) | ~85 % | presque fini, reste run eBay sur cohorte + scale 524 |
| [data-harmonization](./data-harmonization/) | ~85 % | tout livré sauf le Chunk 5 (migration identité) |
| [lab-streamline](./lab-streamline/) | ~85 % | reste eBay-standards + gros run PC 16 classes |
| [cohort-capture-flow](./cohort-capture-flow/) | ~85 % | flow live, reste vérifier les chemins post-rename |
| [best-frame-capture](./best-frame-capture/) | ~95 % | chunks 1-7 livrés (tooling Python + parité 2026-06-11), reste le premier bench 50 sessions sur device |
| [design-groups-standards](./design-groups-standards/) | ~80 % | pilote BE live, reste le rollout autres pays |
| [training-pipeline](./training-pipeline/) | ~80 % | sprints ✅ + harvest exécuté (docs corrigées 2026-06-11), reste user-harvest in-app |
| [parity](./parity/) | ~75 % | capture Maestro+proto+viewer LIVE, reste flows nouvelles scènes + pont interpréteur |
| [harmonisation-images](./harmonisation-images/) | ~85 % | canoniques READ migrés MinIO+CDN (3824, 2026-06-14) ; reste WRITE path enrichissement + 546 legacy |
| [crop-rim-overfit](./crop-rim-overfit/) | 🆕 kickoff | run eBay → crop sur-ajuste le cercle interne (EMU 2009 €-globe) → ~100 faux négatifs ; handoff prêt, stratégies A→D |
| [crop-forensics](./crop-forensics/) | ~55 % | sujet actif, reste l'auto-rejet (S7) |
| [crop-quality-overhaul](./crop-quality-overhaul/) | algo livré | reste sessions Android + tooling review manuel |
| [ai-first-test-suite](./ai-first-test-suite.md) | 0 % | kickoff prêt, pas démarré — gros levier qualité |

---

## lab-prod-refacto — ~97 % ✅ quasi clos (re-vérifié 2026-06-11)
4 phases fonctionnellement closes (2026-05-02) : `promote_iteration.py`, `promote_prod_assets.py`,
`build_cohort_bundle.py`, `equivalence.py` live ; patch destructif retiré.
**Fait 2026-06-11 :** ~~cohort_meta.json~~ retiré (Android lit `bundle_meta.json`, tests verts) ·
~~équivalence Android~~ confirmée live (EquivalenceMap.kt + isCorrectEq + JSONL) ·
`model_promotions` et `r_at_*_eq` reclassés **optionnels par design** (promoted_from.json / JSON reports suffisent).
**✅ FAIT 2026-06-14 (décision PO : tous les sites → prod/current promu).**
`_mirror_iter_outputs` retiré de `iteration_runner.py` (+ docstring `_export_tflite` corrigé). Les **4 consommateurs** du
mirror repointés vers `ml/prod/current/` : `server.py` (5 read-sites, constantes `PROD_TFLITE_DIR`/`PROD_EMBEDDINGS_DIR`,
`OUTPUT_DIR` supprimé ; `/export/deploy` & `/export/upload-model` doc'és comme doublons des scripts promote),
`lab_routes.py` (`_TFLITE_PATH`), `bootstrap/seed_supabase.py` (`EMBEDDINGS_DEFAULT`), `training/eval/evaluate_real_photos.py`
(`DEFAULT_CENTROIDS` — au passage fix d'un bug pré-existant : pointait vers `ml/training/output/` mort). Tous les read-sites
guardent par `.exists()`. **Comportement attendu : monitoring/deploy affichent vide tant qu'aucune `promote_iteration`
n'a peuplé `prod/current/`** — c'est l'état prod-promu-seulement voulu. Validé : `py_compile` + imports OK + 36 tests verts
(promote 11, iteration/cohort/resolver 25). `build_cohort_bundle.py` était déjà migré (lit `prod/current` ou `lab/iterations` via `--source`). **À archiver.**

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

## best-frame-capture — ~95 % (chunk 7 livré 2026-06-11)
Chunks 1-6 livrés (ScanReducer 6 états, BestFrameSelector, CameraLockController, scorer, archive ;
table Room `coin_captures` confirmée). Chunk 7 **complet** : côté Android (BenchRecorder/BenchEvent/
BenchProtocol + `/dev/bench` + `android:bench:pull`) et côté Python (package `ml/bench/` : session_io,
replay avec ports exacts des triggers + sélecteur D8, CLIs annotate/calibrate/compare,
`ml/vision/frame_scorer.py` parité scorer). Parité Kotlin↔Python verrouillée par test sur la session
device committée (≤1e-3, 31 tests verts). Go-task `ml:bench:{replay,annotate,calibrate,compare}`.
**Reste (exécution) :** le premier bench complet — 50 sessions protocole guidé sur device
(`recordFramesEnabled` on), annotation, calibration, rapport dans `results/`. C'est de la manip
device + 25 min d'annotation, pas du code.

## design-groups-standards — ~80 %
Doc fidèle au code (FK scalaire `coins.design_group_id` `schema.sql:935`, tooling `obverse_groups.py` + tests live).
Pilote BE (chunks 1-5) livré.
**Reste :** Chunk 6 rollout autres pays · gate parseur derive-then-diff · validation vision LLM par pays.

## harmonisation-images — ~70 % (vérifié code 2026-06-07)
⚠️ Le « MinIO vide / migration jamais lancée » des docs est **faux**. Réalité : **write-through MinIO LIVE** — `ml/storage/` (client S3, `local_cache` read/write-through, `cascade`) câblé dans `download.py` + `detect_crop.py` + `crop_edit.py` + `review_queue_routes.py`. **`image_assets` 100 % sur clés S3** (3524/3524), source_images 4626/5425 sur S3. La stratégie a **pivoté** : batch-migration → write-through (donc `migrate_to_minio.py` est DEPRECATED à dessein).
**Images canoniques — ✅ READ migré vers MinIO 2026-06-14 (décision PO : home = MinIO `numista-canonical`, abandon Supabase `coin-images`).**
- **Upload livré** : `ml/scripts/upload_canonicals_to_minio.py` (idempotent, pré-liste le bucket en set) → **3824 webp** dans `numista-canonical`, clé `{eurio_id}/{role}_{src}.webp`, cache-control immutable. Vérifié : bucket = 3824 objets, CDN sert 200 `image/webp`.
- **Redirect livré** : `referential_routes.py::_serve_canonical` renvoie `RedirectResponse(public_url(key))` (302) **avec fallback FileResponse FS** quand la clé n'est pas confirmée dans le bucket, et dégradation propre si MinIO est down (set vide → tout FS). Aucune régression (FS-présent ⟹ uploadé). Validé end-to-end (302 live + 3 cas unitaires).
- ⚠️ **Reste (follow-up, pas de régression entre-temps) : le chemin d'ÉCRITURE enrichissement** (`ml/referential/coin_image_storage.py`) pousse encore vers **Supabase `coin-images`** — à repointer vers MinIO + write-through pour que les futurs canoniques atterrissent dans le bucket et soient servis par le CDN (sinon ils tombent sur le fallback FS). Convention de clé périmée du doc chunk-3 (`numista/<numista_id>/<face>.jpg`) à corriger en `{eurio_id}/{role}_{src}.webp`. `scripts/migrate_to_minio.py` reste DEPRECATED.
- **546 source_images legacy** (BCE 475 + JO 71) avec chemins FS absolus → backfill ciblé vers `enrichment-raws`
- Backup NixOS/pCloud : **0 % codé** (rien dans `ml/storage/`)

## crop-forensics — ~55 % (sujet actif)
S1-S6 livrés/réfutés (composite score, sort buttons, scripts `ml/scripts/crop_exp/`).
**Reste :** S7 `auto_reject_reason` backend (2 seuils) · S8 score_v2 sort par défaut (optionnel) · S9 area_ratio adaptatif (pausé).
⚠️ **Re-vérifié 2026-06-14 : S7 est gelé, pas juste « à faire ».** Les 2 seuils S7 dépendent de `bg_uniformity` (S4) et `inner_feature_score` (S5/S6), qui ont **tous été réfutés** sur les bench. Implémenter l'auto-reject sur ces signaux morts = faux positifs garantis (dette). S7 attend un **nouveau signal discriminant** avant d'avoir un sens. Ne pas coder en l'état.

## crop-quality-overhaul — algo livré, sessions restantes
`detect_bbox_refine` shippé (crop eBay ~92 %). _(NB : le doc pointe `ml/sources/_base/steps/` mais le code vit dans `ml/scan/crop_detectors.py` — chemin périmé.)_
**Reste :** Session A (parité crop scan Android) · Session B (tooling review manuel pour la traîne).
⚠️ doublonne avec `operations/crop-bimetal-harden-session.md` — fusionner avant de lancer.

## referential-fixes — ✅ 100 % RÉSOLU (audit 2026-06-14)
Backend + UI étaient déjà complets (`referential_fix_apply.py`, `referential_routes.py`, `FixesPage.vue`).
**Mais l'audit lecture-seule du 2026-06-14 a montré que les 9 cas sont DÉJÀ corrects en DB** : `discover_referential_fixes`
(lecture seule, 0 appel Numista) retourne **0 proposals** car `referential_catalog` a été wipé+re-bootstrapé au P.6
coin-richness (2026-05-26), qui a cette fois créé N rows par (country, year) avec les bons `numista_id`. Les 9 erreurs
de linkage (es-2012, fr-2014, be-2015, de-2015, lt-2015, lv-2016, fr-2018, lv-2018, es-2018) ont donc été corrigées par
le re-bootstrap lui-même — le bouton apply-fix n'a jamais servi et n'est plus nécessaire. Toutes les rows ont leurs
images `numista_api` (+ `bce_official` quand pertinent). **Action : `git mv` ce dossier vers `docs/archive/`.**
_Résidu hors-scope : `referential_catalog` reste vide ; ré-activer le discover pour de futurs cas = re-peupler cette table depuis Numista (autre chantier)._

## cohort-pipeline — ~88 % (vérifié code 2026-06-07)
⚠️ Le `REBUILD-HANDOFF` (« rebuild pas démarré, B1-B5 ouverts ») était un **snapshot du vendredi soir, immédiatement périmé** : 7 commits du week-end ont shippé le rebuild. Réalité : cockpit reconstruit et fonctionnel — **36 fichiers / 9287 lignes** dans `admin/.../features/lab/` (`CohortDetailPage` + `CohortFlowHeader` + 5 drawers), **modèle d'état explicite shippé** (`image_state_events`/`image_state_current`/`cohort_jobs` + `emit_state_event`, commit `85bf851`), `lab_routes.py` 3212 lignes. **B1-B5 ont chacun un commit de fix** (`c69ff22` recrop subprocess, `2a14596` attribution class-level, `dbf3db3` flow header).
**Reste réellement :**
- **Validation PO du lane UX (B3)** : `CohortDrawerCrop.vue` existe mais aucun commit « validé PO » ; sémantique manual/auto/ccproxy à confirmer en usage réel
- **Smoke run end-to-end** mix-zone-17 avec le cockpit reconstruit (pas re-validé en UI)
- Tweaks en cours sur `CohortDrawerEbay.vue` (modifié `M` dans le git status actuel)
- Theme-matcher standards (cause racine B1) : mitigé par l'attribution class-level, qualité upstream reste un point faible

## parity — ~75 % (vérifié code 2026-06-07)
⚠️ « différé » sous-compte massivement. Réalité : pipeline de capture **fonctionnel et déjà exécuté** — **16 flows Maestro** réels (`admin/packages/parity/flows/`, statut `COMPLETED` les 16-17 avril, screenshots déposés), capture proto **automatisée** (`capture/proto.ts` + Playwright, 27 PNG), deeplinks Android live (`app-android/src/qa/` : `eurio://parity/seed`, `eurio://scene/`), **viewer web** `ParityPage.vue` (284L) routé `/parity`. go-task `parity:capture-*` enregistrés.
**Reste réellement :**
- **Flows manquants** pour les scènes post-shift design (~10 : onboarding ×5, coin-detail, vault-catalog-country, profile-unlock) — 16 flows vs ~26 scènes
- **Pont Maestro↔Playwright** (rejouer les *steps* yaml comme assertions Playwright, pas juste screenshot) = la vraie partie différée
- Screenshots Android **périmés** (dernier run 2026-04-17, l'app a bcp changé depuis) → re-run Maestro

---

## training-pipeline — sprints livrés, harvest à démarrer
Sprints 1-5 livrés (2026-04-29/30, code dans `ml/training/`, table README corrigée). `journal/` = logs de runs actifs.
**Reste :**
- **`harvest/` — vision LARGEMENT EXÉCUTÉE (~80 %), docs corrigées 2026-06-11.** Réalité du code : phase 1 DINOv2 ✅ (`ml/training/foundation/encoder.py`, dinov2_vits14), phase 2 auto-validateur ✅ (`ml/training/foundation/auto_validate.py` + `thresholds` + `ml/review/review_lanes.py`), phase 3 sources étendues ✅ (`ml/sources/ebay` ~80k + bce/lmdlp/jo/pricing), phase 5 review humaine ✅ (review_queue + **lot-review live** + `claude_review`). ~~Réécrire les docs harvest/~~ → fait : chemins post-refacto corrigés dans README + phase-1, entrée datée dans harvest/progress.md.
  - **Phase 4 — user-harvest in-app** (seul vrai manque) : l'utilisateur scanne → confirme/corrige la pièce → on récupère **une photo unique, label sûr** pour le training. Gated sur l'app Android.
  - **Cloud fallback** : Numista API pour identifier une pièce inconnue (partiel — source `numista` existe déjà).
- Device walkthrough des sprints 4-5 jamais loggé (premières métriques device end-to-end TBD)
- Routes `/benchmark` FastAPI pas encore purgées (fusion prévue dans `experiment_iterations`)
- `iteration-detail-page-design.md` : gaps UX ouverts (monitor training invisible G-001, collapse §0 G-002, recipe affichée en UUID)

## ai-first-test-suite — kickoff prêt, 0 %
Doc de cadrage solide (pourquoi, catégories A-F, dashboard, 7 questions à trancher). **Très pertinent** : la review auto-validation 2026-05-05 a saigné ~70 % de faux positifs faute de tests vérifiables.
**Reste (par ordre du doc) :**
- Trancher les 7 questions (front tool, fixtures DB, marqueurs pytest, couverture cible, auto vs main, CI gates, rétro-compat 308 tests)
- §A wiring tests (endpoint backend ↔ composable front) sur le périmètre `auto-validation` d'abord (ROI immédiat)
- Puis §B contract tests par étape pipeline, §D smoke, §E front (vitest, 0 test admin aujourd'hui)
- Dashboard `docs/test-status.md` régénéré + workflow `go-task test:snapshot`/`test:diff`

---

> **Sources (parking lot)** — `docs/sources-refacto/` a été **archivé** (chantier multi-sessions livré : pipeline 6 étapes, orchestrateur, eBay). ⚠️ _Les statuts « pas démarré » de ces docs ont drifté — vérifier le code avant de croire un doc._ Réalité : **lot-review = LIVE et actif** (`/review-queue/lots`, `LotReviewDetailPage.vue` 1353 lignes, 30 routes, édité aujourd'hui), **auto-validation = faite** (`ml/foundation/`). Fils encore réellement ouverts, à juger : `ebay-multi-marketplace` cutover V2, `sdk-kickoff` (ReferentialSourceAdapter, différé post-cohorte 19), Dino×texte combiné (chunk 9). Détail : `docs/archive/sources-refacto/`.
>
> **Références/ADRs gardés en place :** `adr/`, `app-implem-phases/`, `research/`, `mission/`, `design/_shared/`, `tracks.md`, `roadmap.md`, `tech-stack.md`, `cross-platform-setup.md`, `DECISIONS.md`.
