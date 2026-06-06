# Cockpit cohorte — HANDOFF de DEBUG (jobs & scrape pas fonctionnels)

> Passation pour une **nouvelle session**. La reconstruction du cockpit
> `/lab/cohorts/<id>` (pilote mix-zone-17 `b0299ca0252b`) est **livrée et validée
> visuellement par le PO** (frise flow, légende, compteurs honnêtes, grammaire
> d'actions, lanes — voir [REBUILD-ANALYSIS.md](./REBUILD-ANALYSIS.md) + 5 commits
> `85bf851`→`e65b4de`). MAIS en usage réel, **3 comportements sont cassés ou
> trompeurs** (jobs recrop bloqués, scrape sans trace, libellés contradictoires).
> Mission : **comprendre TOUTE la mécanique endpoints↔UI du cockpit, puis
> débugger**. Posture PO : vérifier en base/logs, pas au jugé.

---

## 0. PROMPT à coller pour démarrer la nouvelle session

```
On débugge le cockpit cohorte Eurio (/lab/cohorts/b0299ca0252b). La
reconstruction est livrée (5 commits, branche sources-jo-wikipedia) et le PO
valide le rendu, MAIS 3 choses sont cassées/trompeuses en usage réel. Lis
d'abord, dans l'ordre :
  - docs/cohort-pipeline/COCKPIT-DEBUG-HANDOFF.md  (CE doc : bugs + inventaire endpoints + plan)
  - docs/cohort-pipeline/REBUILD-ANALYSIS.md       (le modèle d'état + l'UX, contexte)
  - la mémoire : project_cockpit_rebuild, project_cohort_training_pipeline,
    project_coin_census_detector, feedback_chunk_audit_flow

NE PATCHE RIEN avant d'avoir : (1) reproduit chaque bug §2 en base/logs,
(2) cartographié l'inventaire endpoints §3 contre le code réel (working tree),
(3) confirmé QUELS endpoints existent, marchent, sont mal placés ou manquants.
Le backend FastAPI + le dev server admin (:5173) doivent être up (le PO les
lance). Restitue : findings + plan de fix par bug, demande arbitrages, PUIS
implémente par chunks avec audit visuel (le PO valide chunk par chunk).
Bugs prioritaires : BUG-1 recrop zombie persisté (jobs running éternels),
BUG-3 scrape sans trace in-row + runs failed silencieux, BUG-2 (quick win)
libellés be-2007 contradictoires.
```

---

## 1. État de la reconstruction (ce qui MARCHE — ne pas casser)

5 commits sur `sources-jo-wikipedia` (`git log --oneline cc28269..HEAD`) :
- `85bf851` C1+C2 — modèle d'état (`image_state_events`/`image_state_current`/`cohort_jobs`) + `emit_state_event` + fix 506 orphelins.
- `5e5f031` C3+F1 — `_coin_tail` lit `image_state_current`, ruban/phrase honnêtes.
- `473fb48` F2+F6 — grammaire d'actions (1 primaire/pièce) + lanes honnêtes (`by_lane_lot`).
- `dbf3db3` F3/F4/F5 — frise flow (`CohortFlowHeader.vue`) + ligne-exemple + jobs in-row.
- `e65b4de` B1 — badge « 0 attribué » vs « jamais scrapé ».

**Validé PO (à préserver)** : la frise flow, la légende « comment lire une ligne »,
les compteurs honnêtes (en review vivant, validés, non routés), la grammaire
d'actions, la distinction lanes. Le **modèle d'état est sain** (drift `--verify`=0).

---

## 2. LES BUGS (reproduits en base — partir de ces faits)

### BUG-1 — Recrop : jobs « running » ÉTERNELS (zombie persisté) ⚠️ grave
**Symptôme PO** : 2 premières lignes du tableau (`ad-2014`, `at-2002`) affichent
`recrop 0/2` et `recrop 0/30` avec spinner, **figées depuis ~20 min**, rien ne bouge.

**Preuve base** (`cohort_jobs`) :
```
id        kind         eurio_id           status   n_total n_done n_produced started_at           finished_at error
cd6b452c  recrop_zero  at-2002-…-1st-map  running  30      0      0          2026-06-06 19:20:17  NULL        NULL
304782b3  recrop_zero  ad-2014-…-1st-type running  2       0      0          2026-06-06 19:17:35  NULL        NULL
```
`SELECT … FROM image_assets WHERE run_id LIKE 'recrop-zero-%'` → **0 ligne**.

**Lecture** : le job est INSERT `running` (endpoint `recrop_zero_coin`, le thread
démarre), `progress_cb` n'a JAMAIS avancé `n_done` au-delà de 0, et `cohort_job_finish`
n'a JAMAIS tourné (`finished_at`/`error` NULL). Donc le **thread daemon est mort ou
hung dès le 1ᵉʳ raw**, et **rien ne reape les jobs orphelins** → on a remplacé le
zombie *mémoire* (B2 d'origine) par un zombie *persisté*. Le front affiche le job
`running` indéfiniment (`useCohortJobsQuery` poll 3s tant que `running`).

**Hypothèses à trancher (par les LOGS du thread + un test synchrone)** :
1. `normalize_listing(bgr, census=True)` charge DINOv2 + la probe fragment (`load_face_probe`, encoder MPS) **dans un thread daemon** → deadlock torch/MPS hors main-thread (très probable sur Mac). Le CLI `recrop_cohort_census.py` marche car il tourne en **main thread**.
2. Le process FastAPI a redémarré (`--reload`) → le thread daemon est mort, le job persisté reste `running` (aucun reaping).
3. `local_path("enrichment-raws", …)` (fetch MinIO) hang.

**Ce qu'il faut** :
- Reproduire : appeler `scan.recrop_zero.recrop_zero_for_coin(conn, 'ad-2014-…', run_id='t', commit=False)` **en synchrone** (script) + timer par raw → voir si ça hang et OÙ (ajouter des logs / py-spy sur le thread).
- Décider l'exécution des jobs : un **thread daemon** n'est pas robuste (MPS/torch, perdu au reload). Options : (a) exécuter le census/DINO dans un **subprocess** dédié (comme le training_runner ?), (b) une vraie **queue de jobs** persistée + worker, (c) au minimum un **reaping** : au boot + périodiquement, marquer `failed` les `cohort_jobs.status='running'` dont le thread n'existe plus / `started_at` trop vieux (heartbeat). Voir comment `training_runner.py` lance ses subprocess (PYTHONPATH, modèle hors main-thread) — c'est le précédent qui marche.
- Purger les 2 jobs zombies actuels : `UPDATE cohort_jobs SET status='failed', error='thread mort (debug)' WHERE status='running'` (après backup).

Endpoints concernés : `POST /lab/cohorts/{id}/coins/{eurio_id}/recrop-zero` +
le thread `_runner` dans `ml/api/lab_routes.py` (~l.1772) ; lecture front
`GET /lab/cohorts/{id}/jobs` (`cohort_jobs_list`).

### BUG-2 — be-2007 : libellés contradictoires (quick win, front pur)
**Symptôme** : la ligne be-2007 montre EN MÊME TEMPS le badge orange « 0 ATTRIBUÉ »
(correct, B1), la phrase « aucun listing scrapé », et le muet « pas encore scrapé ».
Les deux derniers **contredisent** le badge.

**Cause** : dans `CohortDrawerEbay.vue`, la phrase funnel (`v-else` → « aucun listing
scrapé ») et le muet `v-else-if="c.scrapable"` → « pas encore scrapé » ne tiennent
pas compte de `c.group_scraped`. Quand `group_scraped && n_source_images==0`, ils
devraient dire « groupe scrapé, 0 pour ce millésime — récupérable via review lots »
(cohérent avec le badge), PAS « pas encore scrapé ».

**Fix** (≈10 lignes front) : router ces deux états sur `group_scraped`. Trivial,
à faire tôt.

### BUG-3 — Scrape : badge global éphémère, aucune trace in-row, runs failed silencieux
**Symptôme PO** : clic « Scraper » sur be-2007 → un badge apparaît EN HAUT (compteurs
découverte), puis **disparaît** « comme si fini », et la ligne be-2007 ne change pas ;
refresh → rien ; le bouton est « vierge » (juste l'id du run `f5b36b`).

**Preuve base** (`source_runs`) :
```
f5b36b84  ebay  success  price_aggregate  +3 raws  +2 crops   19:51→19:54   ← scrape be-2007 : a RÉUSSI
0d84b7a6  ebay  failed   discover         0        0          19:25→19:25   ← un autre run a ÉCHOUÉ (silencieux)
```
Le scrape be-2007 a bien tourné (+3 raws / +2 crops) mais **attribués aux sœurs**
(B1, 1-year era) → 0 pour be-2007 → la ligne reste « 0 attribué ». **Comportement
correct**, mais l'UI ne l'explique pas et n'a aucune trace persistée.

**Causes** :
1. Le badge run-live (`useEbayRunningRunsQuery` → `GET /sources/ebay/runs?status=running`)
   est **global** (pas cohort-scopé), poll 3s, et disparaît dès que le run finit →
   « clignote » sans laisser de trace. Pas relié à la pièce concernée.
2. Le **scrape n'écrit PAS `cohort_jobs`** (contrairement au recrop) → aucune trace
   in-row, aucun « X attribués / 0 à cette pièce ». C'était le seul morceau noté
   « différé » du rebuild (cf. REBUILD-ANALYSIS §UX, point B1/scrape).
3. Les runs **failed** (ex `0d84b7a6` failed à `discover`) ne remontent nulle part
   dans le cockpit.

**Ce qu'il faut** (décider avec le PO) : câbler `POST /sources/ebay/runs` pour
écrire un `cohort_jobs` (`kind='scrape_ebay'`, `target_eurio_id`, `n_total`,
`n_produced`, `n_attributed_target`, `status`, `error`) à l'avancement + fin →
barre/note in-row comme le recrop, et surfacer les runs failed. ⚠️ eBay est
**user-owned** (le scrape consomme le quota, le PO le lance manuellement) — ne PAS
auto-déclencher de scrape.

---

## 3. INVENTAIRE COMPLET des endpoints du cockpit (à valider contre le code)

> Page = `admin/.../features/lab/pages/CohortDetailPage.vue` + ses tiroirs + la
> frise. Préfixes de montage : `lab_routes.py` → **/lab**, `review_queue_routes.py`
> → **/review-queue**, `sources_routes.py` → **/sources** (vérifier dans `server.py`).
> Front : composables `features/lab/composables/{useLabApi,useLabQueries}.ts` +
> `features/review/composables/useReviewApi.ts` (triage). Statut : ✅ marche /
> ⚠ suspect / ❌ bug confirmé.

| Méthode · Path | Backend (fichier:fn) | Consommé par (composable → composant) | Renvoie | Statut |
|---|---|---|---|---|
| GET `/lab/cohorts/{id}` | lab_routes `get_cohort` | useCohortQuery → CohortDetailPage | CohortSummary | ✅ |
| GET `/lab/cohorts/{id}/progress` | lab_routes (`_cohort_progress`) | useCohortProgressQuery (poll 5s) → C1/C2 + **frise étape 2** | {c1,c2} captures | ✅ |
| GET `/lab/cohorts/{id}/funnel-status` | lab_routes `_cohort_funnel_status` | useCohortFunnelStatusQuery → **frise (F3)** + §C3 (CohortDrawerEbay) | per_coin (state_counts, n_in_review, n_orphaned, group_scraped…), head.groups, rescued_to_sisters, quota | ✅ (cœur honnête) |
| GET `/lab/cohorts/{id}/dedup-status` | lab_routes | useCohortDedupStatusQuery → §C3 bloc dédup | compteurs dédup | ✅ |
| GET `/lab/cohorts/{id}/discard-summary` | lab_routes `_cohort_discard_summary` | useDiscardSummaryQuery → §C3 rejets | rescue/noise/ambiguous | ✅ |
| GET `/lab/cohorts/{id}/jobs` | lab_routes `cohort_jobs_list` | **useCohortJobsQuery (poll 3s si running)** → §C3 recrop in-row (F5) | {jobs:[CohortJob]} | ⚠ OK en lecture, mais alimenté par des jobs **zombies** (BUG-1) |
| POST `/lab/cohorts/{id}/coins/{eurio_id}/recrop-zero` | lab_routes `recrop_zero_coin` + thread `_runner` | useRecropZeroCoinMutation → bouton Recropper | {status, run_id, job_id, n_total} | ❌ **BUG-1** (thread hang, job jamais fini) |
| GET `/lab/cohorts/{id}/coins/{eurio_id}/recrop-zero/status` | lab_routes `recrop_zero_status` (lit cohort_jobs) | **PLUS consommé par le front** (remplacé par /jobs) | dernier job recrop du coin | ⚠ **mort / mal placé** — à retirer ou ré-assumer |
| GET `/lab/cohorts/{id}/rescue-candidates` | lab_routes | useRescueCandidatesQuery → §C5 Rescue | candidats rescue | ✅ |
| POST `/sources/discarded/{id}/rescue` | sources_routes | rescueDiscard → §C5 | row source_image créée | ✅ |
| GET `/review-queue/triage-stats?cohort_id={id}` | review_queue_routes `queue_triage_stats` | useCohortTriageStatsQuery → §C4 (CohortDrawerCrop) | by_lane, **by_lane_lot**, n_lot_crops, n_rejected, n_skipped | ✅ (F6) |
| POST `/sources/ebay/runs` (body cohort_id ou target_eurio_id) | sources_routes (scrape orchestrator) | triggerCohortEbayScrape / triggerCoinEbayScrape → boutons Scraper | {run_id, …} | ⚠ marche (run success) mais **aucune trace cohort_jobs** (BUG-3) |
| GET `/sources/ebay/runs?status=running&limit=5` | sources_routes | useEbayRunningRunsQuery (poll 3s) → **badge live GLOBAL** §C3 | runs en cours | ⚠ global non-scopé, clignote (BUG-3) |
| GET `/lab/cohorts/{id}/iterations`, `/trajectory`, `/sensitivity`, `/runner/status`, `/runner/runtime-info` | lab_routes | queries dédiées → bas de page (itérations, trajectoire, runner) | … | ✅ (hors périmètre debug, ne pas casser) |

**Liens (pas de la donnée)** : §C4 → `/review/manual?cohort=…&lane=…`, `/review/auto-accept`,
`/review/ccproxy`, `/review/recover`, `?mode=lot` ; §C3 → `/crop-bench?cohort=…`,
`/bench/runs/<run>?eurio_id=<coin>#filter|#crop`. À vérifier que ces routes/params
existent côté pages review/bench (le cockpit délègue, ne réimplémente pas).

**Questions d'architecture à répondre (demande explicite du PO)** :
1. **Tous les endpoints nécessaires existent-ils ?** → oui pour la lecture (funnel,
   jobs, triage, progress). **Manquant** : scrape → cohort_jobs (BUG-3).
2. **Des endpoints utilisés au mauvais endroit ?** → `recrop-zero/status` n'est plus
   appelé (mort) ; le badge live utilise le **global** `/sources/ebay/runs` au lieu
   d'un statut cohort-scopé. À nettoyer/ré-router.
3. **Le mécanisme de jobs background (thread daemon) est-il viable ?** → NON tel quel
   (BUG-1). Décider subprocess vs queue vs reaping (cf. `training_runner.py`).

---

## 4. PLAN de debug proposé (à valider par le PO avant de coder)

1. **BUG-1 (le bloquant)** : reproduire `recrop_zero_for_coin` en synchrone (timer/logs) →
   localiser le hang (DINO/MPS hors main-thread très probable). Décider le modèle
   d'exécution (subprocess façon training_runner + reaping des jobs orphelins).
   Purger les 2 zombies actuels.
2. **BUG-2 (quick win)** : réconcilier les libellés be-2007 sur `group_scraped` (front).
3. **BUG-3** : câbler `scrape → cohort_jobs` (target_eurio_id + n_attributed_target),
   trace in-row + runs failed visibles, remplacer/compléter le badge global.
4. **Nettoyage endpoints** : retirer `recrop-zero/status` mort (ou le ré-assumer),
   décider le badge live cohort-scopé.

Chacun = un chunk auditable (le PO valide visuellement, cf. feedback_chunk_audit_flow).
Backups DB avant toute migration/purge (`ml/state/eurio.db.bak-*`).

## 5. Pointeurs techniques
- Jobs/recrop : `ml/api/lab_routes.py` (`recrop_zero_coin`, `_runner`, `_open_recrop_conn`,
  `cohort_jobs_list`, `recrop_zero_status`) ; `ml/scan/recrop_zero.py` (`recrop_zero_for_coin`,
  `progress_cb`) ; `ml/state/store.py` (`cohort_job_start/progress/finish`).
- Census/DINO chargé par recrop : `ml/scan/normalize_snap.py` (`normalize_listing(census=True)`),
  `ml/scan/census.py` (`load_face_probe`, encoder). Précédent qui marche en subprocess :
  `ml/api/training_runner.py` (`_run_subprocess`, PYTHONPATH).
- Scrape : `ml/api/sources_routes.py` (`POST /sources/ebay/runs`), orchestrateur
  `ml/sources/_base/orchestrator.py`, `ml/sources/ebay/*`.
- Front : `admin/.../features/lab/components/{CohortDrawerEbay,CohortFlowHeader,CohortDrawerCrop}.vue`,
  `composables/{useLabApi,useLabQueries}.ts`, `features/review/composables/useReviewApi.ts`,
  `features/lab/types.ts`.
- État (sain, ne pas casser) : `image_state_events`/`image_state_current`/`cohort_jobs`
  dans `schema.sql` ; vérif drift : `PYTHONPATH=ml ml/.venv/bin/python ml/scripts/backfill_image_state.py --verify`.
