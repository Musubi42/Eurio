# Modèle B — Analyse as-built vs DESIGN (GAP-ANALYSIS)

> **But** : cartographier ce qui EXISTE réellement dans le code vs ce que veut
> [`DESIGN.md`](./DESIGN.md), pour que les prochains workflows attaquent la
> migration Modèle B **chunk par chunk** sans re-scouter. Produit par un audit
> multi-agent (9 dimensions, chaque constat re-vérifié contre le code).
>
> **Date** : 2026-06-29. **Branche** : `sources-jo-wikipedia`.
>
> **Comment l'utiliser** : §5 = plan de chunks ordonné (le backlog). §6 = les
> fichiers à toucher par chunk. §3 = le détail par dimension. §4 = les
> décisions PO à trancher AVANT de coder certains chunks.
>
> ⚠️ **Correction de statut** : `DESIGN.md` et la mémoire disent « non démarré ».
> **C'est faux.** Les chunks C1→C4 du DESIGN sont **déjà codés** (run-batch, SDK
> client, serve-API, infra Docker) — en partie par le chantier
> *data-layer-unification* et *auth-redesign*, sans que le DESIGN le reflète. Le
> travail restant réel = **déployer C4, faire C5, et surtout C6** (câbler le
> compute), puis C7/C8.

---

## 0. TL;DR (8 lignes)

1. Le **tuyau serveur du Modèle B existe et est testé** : `ml/client/` (runbatch
   + replica + http) + `POST /ingest/run` + `ml/serving/server_serve.py` lean +
   `infra/eurio-api/` (Docker/Traefik/OIDC). Chunks C1–C3 ✅, C4 ✅ **en code**.
2. **Mais C4 n'est pas déployé** (`infra/eurio-api/data/` absent → conteneur
   jamais lancé, DB canonique VPS non seedée).
3. **C6 est à zéro** : aucun module de calcul (scraping/recrop/DINO/training)
   n'utilise `push_run`/`pull_replica` — tous écrivent `Store(local)` en direct.
   **C'est le verrou** : tant que C6 n'existe pas, le Modèle B n'a aucun effet.
4. **Deux `eurio.db` divergent déjà** : la DB Mac (`ml/state/eurio.db`, via lease)
   accumule le calcul ; la DB VPS (`/var/lib/eurio/eurio.db`, via `server_serve`)
   accumule l'interactif (review/edits). Aucune réconciliation. **Risque central.**
5. **C5 (VITE_ML_API) non fait** : `http://127.0.0.1:8042` hardcodé dans 11
   fichiers studio-local + 2 strings brutes dans des templates.
6. **Auth incohérente** : `/ingest/run` est encore sous `require_token` (legacy
   `api_tokens`) alors que tout le reste est passé à `require_principal` (PAT).
7. **Bug runtime trouvé** : `lab_routes.py:2061` lance `scripts/recrop_cohort_census.py`
   qui a été archivé → l'endpoint `/lab/.../recrop-zero` est cassé (hotfix indépendant).
8. **Dette doc/code** : `bootstrap_canonical.py` mort, `deployment-topology.md §cap B`
   + `C4-HANDOFF-SERVER.md` + `client/__init__.py` périmés.

---

## 1. Architecture as-built (la réalité actuelle)

```
        ┌──────────────────────── VPS (always-on, no-GPU) ────────────────────────┐
        │  ml/serving/server_serve.py  (app LEAN, image sans torch/cv2)            │
        │    • /healthz + auth OIDC/PAT (require_principal)                        │
        │    • POST /ingest/run  ⚠ require_token (legacy api_tokens, PAS PAT)      │
        │    • routers montés : users, tokens, review(read), confusion, audit,    │
        │      coin_series, stats, sources(read), review_queue(read lean)         │
        │    • _CANDIDATES best-effort : coins, sets, operations, referential,    │
        │      peer_arbitration ; SKIPPÉS sur lean (cv2) : review_queue(legacy),  │
        │      coin_assets                                                         │
        │    ÉCRIT ───────────────►  DB-VPS : /var/lib/eurio/eurio.db  (bind-mount)│
        │  infra/eurio-api/ : Dockerfile + compose (Traefik, SOPS) ── PAS déployé  │
        │  MinIO : images + bucket eurio-db (copie Mac) + backups                  │
        └──────────────────────────────────────────────────────────────────────────┘
                 ▲ interactif (thin-client Bearer PAT, partiel)        ▲ run-batch (INEXISTANT côté compute)
                 │                                                     │
   ┌─────────────┴───────────── Mac (M4) / PC (1080Ti) ───────────────┴───────────┐
   │  ml/serving/server.py  (app FULL, localhost:8042)  ── go-task ml:api          │
   │    ÉCRIT ──────────►  DB-Mac : ml/state/eurio.db                              │
   │    coordonné à MinIO par store/lease.py  (go-task ml:db:acquire/release/sync) │
   │  compute : sources/*/cli.py, vision/recrop_zero, scripts/backfill_dino,       │
   │            training/* → TOUS ouvrent Store(ml/state/eurio.db) EN DIRECT       │
   │  ml/client/ : runbatch + replica + http  ──► PRÊT mais JAMAIS appelé par le   │
   │            compute (seul ingest_routes côté serveur l'importe)                │
   └────────────────────────────────────────────────────────────────────────────────┘
```

**En clair** : on est en **Modèle A** (eurio.db = fichier, canonique dans MinIO,
seul writer = le Mac via lease manuel) **PLUS** un embryon de Modèle B déployable
mais inerte. La data-layer-unification a fait écrire l'API VPS dans **sa propre**
`eurio.db` bind-mount — d'où **deux bases canoniques de facto** qui divergent.

---

## 2. Ce qui est DÉJÀ fait vers le Modèle B (non reflété dans DESIGN.md)

| Chunk DESIGN | État réel | Preuve |
|---|---|---|
| **C1 run-batch** | ✅ codé + testé | `ml/client/runbatch.py` (`export_run`/`ingest_run`/`push_run`/`batch_sha`), table `ingested_runs` (`state/schema.sql:1728`), `tests/test_runbatch.py` + `test_model_b_c2_c3.py` |
| **C2 auth bearer** | ✅ codé, ⚠ superseded | `ml/serving/auth.py` (`require_token`, `api_tokens`) — mais auth-redesign a livré **PAT** (`require_principal`, `pat_tokens`, `create-pat`, `grant-owner`). Le bearer machine est **legacy**. |
| **C3 SDK client** | ✅ codé + testé | `ml/client/http.py` (urllib, `EURIO_API_URL`+`EURIO_API_TOKEN`), `ml/client/replica.py` (`pull_replica` MinIO→`eurio.replica.db`, sans lease) |
| **C4 serve-API + infra** | ✅ **codé**, ❌ **pas déployé** | `ml/serving/server_serve.py` (lean, `require_principal`, ingest core) ; `infra/eurio-api/{Dockerfile,docker-compose.yml,entrypoint.sh}` (Traefik, OIDC, SOPS). `data/` absent = jamais lancé. |
| **Thin-client classe A** | 🟡 partiel | Portés vers `eurioApi` (Bearer PAT, `eurio-api.musubi.dev`) : **coins** (CRUD complet), **peer_arbitration**, **operations**, **audit**, **review LECTURES**. Lean `serving/review_queue/` (read-only) monté. |

> Autrement dit : la moitié « plomberie + interactif lecture » du Modèle B est
> faite. Ce qui manque, c'est **le déploiement**, **la config front**, et **la
> bascule du calcul lourd** (C6) — le cœur de la promesse.

---

## 3. Delta par dimension

### 3.1 `server-role-gating` — gating serve/full (effort S)
- **Design veut** : `EURIO_SERVER_ROLE=serve|full` DANS `server.py`, un fichier deux comportements.
- **As-built** : approche **différente** — un fichier parallèle `server_serve.py` (lean) + `server.py` (full). Pas de var de rôle. Montage best-effort via `try/except Exception` sur `_CANDIDATES`.
- **Gap** : déviation non documentée comme officielle ; `except Exception` (au lieu de `ImportError`) **masque silencieusement** les erreurs de wiring ; risque de **drift** server.py↔server_serve.py (un router ajouté côté full n'arrive jamais au VPS).
- **Chunks** : doc-hygiène (acter l'approche parallèle), resserrer le `except`, smoke-test « routers montés », éventuel `serving/_router_registry.py` partagé.

### 3.2 `db-location-writer` — où vit eurio.db + writer unique (effort L) 🔴
- **Design veut** : un seul writer = l'API VPS ; lease = secours post-C8 seulement.
- **As-built** : **DEUX DB** — `ml/state/eurio.db` (Mac, lease manuel actif, `go-task ml:db:acquire/release/sync`) et `/var/lib/eurio/eurio.db` (VPS, `server_serve`). Aucune réconciliation.
- **Gap / risque** : **divergence silencieuse** — le Mac accumule les runs calcul, le VPS accumule les décisions review/edits ; une « vue complète » nécessite de fusionner. **Risque de perte de données au cutover** sans réconciliation explicite.
- **Décision PO bloquante** : cf. §4.1.

### 3.3 `serve-api-deploy-auth` — Docker/Traefik/auth (effort S)
- **Design veut** : conteneur `server_serve`, Traefik `eurio-api.musubi.dev`, bearer simple, seed MinIO au 1er boot.
- **As-built** : infra livrée (mieux que prévu : OIDC+PAT via auth-redesign, SOPS au lieu de Docker secrets files). **Pas déployé** (`data/` absent).
- **Gap** : `bootstrap_canonical.py` mort ; **`C4-HANDOFF-SERVER.md` fortement périmé** (prescrit secrets-files, seed MinIO, `add-token` legacy → un re-déploiement suivi à la lettre **échouera**) ; `infra/eurio-api/README.md` y renvoie.
- **Chunks** : nettoyer dead code, réécrire le handoff en runbook réel, déployer.

### 3.4 `run-batch-reconcile` — export_run / /ingest/run (effort M)
- **Design veut** : compute → `push_run` → `POST /ingest/run` (1 tx idempotente, auth machine).
- **As-built** : serveur **complet et testé** ; **côté compute = zéro** appel.
- **Gap** : (1) **auth split** — `/ingest/run` sous `require_token` (legacy `api_tokens`) ; le scope `ingest:run` existe dans `ROLE_SCOPES` mais **n'est pas câblé** ; un PAT `eurio_…` ne passe donc pas. (2) Aucun runner ne pousse.
- **Chunks** : `C3.5-ingest-auth` (migrer vers `require_scope("ingest:run")`), puis C6.

### 3.5 `read-replica-compute` — réplique RO locale (effort L)
- **Design veut** : compute lit `eurio.replica.db` (pull MinIO sans lease), ne touche jamais le canonique.
- **As-built** : `pull_replica()` existe mais **`eurio.replica.db` n'est jamais créée** ; tout le compute lit/écrit `state/eurio.db` (lease) en RW.
- **Gap** : claim DESIGN « prepare_dataset + train_embedder déjà read-only » **partiellement faux** — `train_embedder.py:163` ouvre un `Store` **RW** dans `_resolve_recipe`. `class_resolver` est `mode=ro` mais pointe sur la DB lease, pas la réplique. Pas de `go-task` pour pull la réplique.
- **Chunks** : `go-task ml:db:pull-replica`, wiring read-path par domaine, qualifier le claim read-only training.

### 3.6 `heavy-compute-inventory` — surface de migration classe B (effort L)
- **Modules qui écrivent `Store(local)` en direct** : `sources/cli.py` + `sources/{ebay,jo,bce,lmdlp}/*`, `vision/recrop_zero.py`, `scripts/backfill_dino_predictions.py`, `scripts/recrop_zero_score_guided.py`, `training/{train_embedder,run_iteration,run_augmentation,iteration_augmentations,run_pipeline}.py`.
- **Sous-gaps** :
  - **B1 scraping** : structurellement simple — `export_run()` couvre déjà les tables du pipeline 9-steps.
  - **B2 recrop_zero** : `run_id` synthétique (`recrop-zero-{eurio_id}`) **absent de `source_runs`** → `export_run()` ne peut pas l'ancrer (violation FK potentielle). Choix A (stub `source_runs`) vs B (endpoint dédié).
  - **B3 dino/backfill** : pas de `run_id` → opérations globales ; à faire post-C8 sur réplique, ou API server-side. Décision PO.
  - **C7 training metadata** : tables `training_*`/`experiment_iterations` absentes de `_TABLE_ORDER` d'`export_run`.
- 🐛 **BUG RUNTIME** : `lab_routes.py:2061` spawn `scripts/recrop_cohort_census.py` **archivé** (`ml/archive/scripts/`) → endpoint `POST /lab/cohorts/{id}/coins/{eurio_id}/recrop-zero` **cassé**. ✅ **Corrigé (H1, 2026-06-29)** : script restauré dans `ml/scripts/` (`git mv`). Le scan a confirmé qu'aucun autre script archivé par `7b2cbbb` n'était encore référencé par du code live.

### 3.7 `interactive-thin-client` — classe A (effort M)
- **Déjà thin-client (`eurioApi`)** : coins, peer_arbitration, operations, audit, review-reads.
- **Encore sur `localhost:8042` (ML_API)** : **sets** (tout le CRUD), **lab/cohort** (et `lab_routes` **absent** de `server_serve`), **review writes** (decide/skip/reject), **referential** (sert aussi `ml/canonical_images/` locaux), **coin_assets/crop** (exclu lean par cv2). Confusion map = **split** (compute local / lectures VPS) — légitime.
- **Gap notable** : `lab_routes` est **structurellement Mac** (IterationRunner subprocess, datasets locaux, adb push) → le porter au VPS tel quel OOM/sans-effet. Décision PO (§4.3).

### 3.8 `admin-ml-api-config` — VITE_ML_API (effort M)
- **As-built** : `VITE_ML_API` inexistant ; `ML_API='http://127.0.0.1:8042'` hardcodé dans `useTrainingApi.ts` + **11 déclarations locales** redondantes + **2 strings brutes** dans `CoinArbitragePage.vue:130` & `NumistaReviewPage.vue:149` (`:src` images, invisibles à un grep `const ML_API`).
- **Chunks** : déclarer `VITE_ML_API` (env.d.ts + .env.example), consolider les 11, corriger les 2 raw strings.

### 3.9 `repo-seam-structure` — couture client/serveur (effort L)
- **Design veut** : `ml/{serving,store,state}` = serveur (writer unique) ; `ml/client/` = porte workstation→serveur ; tout le compute via réplique + `push_run`.
- **As-built** : `ml/client/` existe et est propre, mais **le seam n'est pas franchi** — le compute ouvre `Store(local)` partout. `go-task ml:api` lance `server.py` (full), pas `server_serve`. Aucune tâche `pull_replica`/`push_run`.
- **Verrou** : **C6 est le point de bascule** ; tant qu'il n'existe pas, la couture est théorique.

---

## 4. Risques transverses & décisions PO à trancher

### 4.1 Divergence des deux `eurio.db` (à réconcilier au cutover C8)
Le Mac (DB lease) et le VPS (DB bind-mount) accumulent des écritures **disjointes**
sans réconciliation.

> **Décision PO 2026-06-29** : la divergence est **acceptée** — pas de perte de
> données réelle (chaque côté conserve ses écritures, tables disjointes). Elle
> **ne bloque donc PAS** les chunks code (H*, A1, C5, C6). On continue le
> développement sur le Mac (cf. §7). La réconciliation Mac↔VPS est repoussée au
> **moment du cutover C8** uniquement.

Restera à cadrer **au C8** (pas avant) :
- Le canonique VPS a-t-il été seedé (`go-task ml:db:release` récent ? objet `eurio-db/eurio.db` présent dans MinIO ?).
- Comment réconcilier les deltas Mac (runs calcul) → VPS ? `push_run` rétroactif vs dump+restore.

### 4.2 Auth `/ingest/run` (legacy vs PAT)
Le seul mécanisme post-auth-redesign pour Mac/PC est le **PAT** ; or `/ingest/run`
exige un `api_token` legacy. **Décision** : migrer `ingest_routes` vers
`require_scope("ingest:run")` **maintenant** (recommandé, 30 min, débloque C6 au PAT)
ou garder un `api_token` machine jusqu'à C8.

### 4.3 `lab_routes` : classe A (VPS) ou local-only ?
Les opérations captures/csv/sync/adb sont **Mac par nature**. Option (a) : garder
le lab **local-only** (front conserve ML_API, `lab` = classe B/locale) — **ne bloque
pas le Modèle B**. Option (b) : split metadata→VPS / filesystem→local (refacto L).
**Reco : (a)** pour ne pas bloquer.

### 4.4 Périmètre `VITE_ML_API`
Le compute reste Mac/PC → `ML_API` localhost est **correct** pour training/bench/aug.
Ne migrer vers le VPS que les endpoints **classe A**. Risque : les 2 endpoints
image-serving (`:src` sur ML_API) nécessiteraient CORS+HTTPS si pointés VPS.

### 4.5 Hygiène (dette qui coûtera une session de debug)
`bootstrap_canonical.py` (mort), `C4-HANDOFF-SERVER.md` + `deployment-topology.md §cap B`
+ `client/__init__.py` (périmés), `except Exception` trop large dans `_CANDIDATES`.

---

## 5. Plan de chunks ordonné

> Numérotation alignée sur les phases DESIGN (C…) + préfixes H (hygiène), A (auth),
> TC (thin-client), C6 (compute). « Dép » = doit être fait avant.

| Chunk | Titre | Dép | Effort | Pourquoi / note |
|---|---|---|---|---|
| ~~H1~~ ✅ | Hotfix `lab_routes:2061` → `recrop_cohort_census.py` archivé | — | S | **FAIT 2026-06-29** : `git mv archive/scripts → scripts/`. Endpoint recrop-zero rétabli. |
| **H2** | Doc-hygiène : `deployment-topology §cap B` (C1–C4 ✅), réécrire `C4-HANDOFF-SERVER.md` en runbook, fix `client/__init__.py` | — | S | Évite un échec de re-déploiement et la confusion de statut |
| **H3** | Dead code : supprimer/archiver `bootstrap_canonical.py` ; resserrer `except` `_CANDIDATES` + smoke-test routers | H2 | S | Réduit la dette, fiabilise le boot lean |
| **A1** | `ingest_routes` : `require_token` → `require_scope("ingest:run")` + test | — | S | Aligne l'auth, débloque C6 au PAT (cf. §4.2) |
| **C5** | `VITE_ML_API` : déclarer + consolider 11 const + 2 raw strings | — | M | Front configurable (cf. §4.4) |
| **C4-deploy** | Déployer le conteneur VPS (seed MinIO, `/healthz`, `/ingest/run`) | H2,H3 ; **§4.1 tranché** | M | ⚠ Déployer avant C6 = risque split-brain (cf. §4.1) |
| **TC1** | Sets CRUD front → `eurioApi` | C4-deploy | S | `sets_routes` déjà dans `_CANDIDATES` ; swap client TS |
| **TC2** | Review writes (decide/skip/reject) dans lean `serving/review_queue/` + front | C4-deploy | M | Permet la review multi-device sans Mac (cf. §4.3) |
| **TC3** | Referential reads front → `eurioApi` | C4-deploy | S | Lectures seules ; images locales restent ML_API |
| **C6-task** | `go-task ml:db:pull-replica` (rafraîchit `eurio.replica.db`) | A1 | S | Ergonomie pré-requise au wiring compute |
| **C6a** | Scraping `sources/cli.py` → `pull_replica` + `push_run` | A1,C6-task | M | 1er runner ; valider parité comptages vs Modèle A |
| **C6b** | `recrop_zero` + `backfill_dino` → `push_run` (run_id stub : cf. §3.6 B2/B3) | C6a | L | Décisions PO sur l'ancrage `run_id` |
| **C6c** | Training metadata : étendre `export_run` `_TABLE_ORDER` **ou** `/ingest/training-run` ; read-path RO | C6a | L | Qualifier read-only `train_embedder` |
| **C7** | `POST /lab/iterations` garde-fou 409 (training en cours) | C6c | M | Orchestration server-side |
| **C8** | Cutover : VPS canonique par défaut, lease→urgence, backup périodique VPS→MinIO, réconcilier deltas, MAJ `deployment-topology` A→B | **C6 complet**, §4.1 | L | Le cutover ne se déclenche qu'après C6 |

**Lecture rapide** : H1/H2/H3/A1/C5 sont des **petits chunks parallélisables** sans
dépendance forte (gains immédiats + dette réduite). **C6 est le morceau central**
et conditionne C8. **C4-deploy** est tentant tôt mais expose au split-brain tant
que §4.1 n'est pas tranché.

---

## 6. Pointeurs fichiers par chunk

- **H1** : `ml/serving/lab_routes.py:2061` ; `ml/archive/scripts/recrop_cohort_census.py` → restaurer dans `ml/scripts/` ou corriger le chemin.
- **H2** : `docs/operations/deployment-topology.md` (§cap B), `docs/work-in-progress/model-b/C4-HANDOFF-SERVER.md`, `infra/eurio-api/README.md`, `ml/client/__init__.py` (docstring).
- **H3** : `ml/serving/bootstrap_canonical.py` (suppr/archive) ; `ml/serving/server_serve.py` (`_CANDIDATES` `except`, smoke-test).
- **A1** : `ml/serving/ingest_routes.py` (l.30,38), `ml/serving/auth_principal.py` (`require_scope`, `ingest:run`), `ml/tests/test_model_b_c2_c3.py`.
- **C5** : `admin/packages/studio-local/src/features/training/composables/useTrainingApi.ts:12`, `.env.example`, `env.d.ts`, +11 fichiers (`CropRecoveryPage.vue`, `RawGalleryPage.vue`, `CoveragePage.vue`, `DenomGoldValidatePage.vue`, `FragmentAuditPage.vue`, `useCoinsReview*`, `useLabApi.ts`, `useSetsApi.ts`, …), +2 raw strings (`CoinArbitragePage.vue:130`, `NumistaReviewPage.vue:149`).
- **C4-deploy** : `infra/eurio-api/{docker-compose.yml,entrypoint.sh}`, `secrets/dev.env` (SOPS), MinIO bucket `eurio-db` ; prérequis `go-task ml:db:release` depuis Mac.
- **TC1** : `admin/packages/studio-local/src/features/sets/composables/useSetsApi.ts` ; serveur : `ml/serving/sets_routes.py` (déjà `_CANDIDATES`).
- **TC2** : `ml/serving/review_queue/router.py` (ajouter POST decide/skip/reject), `admin/packages/studio-local/src/features/review/composables/useReviewApi.ts`.
- **TC3** : `admin/packages/studio-local/src/features/referential/composables/useReferentialApi.ts:4,59` ; serveur : `ml/serving/referential_routes.py`.
- **C6-task / C6a** : `ml/Taskfile.yml` (nouvelle tâche), `ml/sources/cli.py:168`, `ml/client/{replica,runbatch}.py`.
- **C6b** : `ml/vision/recrop_zero.py`, `ml/scripts/{recrop_zero_score_guided,backfill_dino_predictions}.py`, `ml/client/runbatch.py` (`source_runs` stub ou endpoint).
- **C6c** : `ml/training/{train_embedder.py:163,run_iteration.py,run_pipeline.py,iteration_augmentations.py}`, `ml/client/runbatch.py` (`_TABLE_ORDER`), `ml/serving/ingest_routes.py`.
- **C7** : `ml/serving/lab_routes.py` (POST iterations), `ml/store/` (statut itération).
- **C8** : `ml/store/lease.py`, `infra/backup/eurio-backup.sh`, `docs/operations/deployment-topology.md`, `ml/client/replica.py`.

---

## 7. Où tourne le travail (Mac vs VPS)

La quasi-totalité du Modèle B restant est **du code** → on développe **ici, sur le
Mac**, dans le repo, commit + push (codeberg `origin` + github backup). Le VPS
pull. Seules **2 opérations** doivent s'exécuter physiquement sur le VPS :

| Chunk | Où | Pourquoi |
|---|---|---|
| H1, H2, H3, A1, C5, TC1–TC3, C6a–C6c, C6-task, C7 | **Mac** (code) | Édition de code/tests, commit/push |
| **C4-deploy** | **VPS** (ops) | `sops exec-env … docker compose up -d --build`, seed, `/healthz` |
| **C8 cutover** | **VPS** (ops) + Mac (réconcile) | Bascule writer + backup + réconciliation deltas |

> Conséquence : on **continue ici** pour tout le développement. Les sessions VPS
> sont courtes et ponctuelles (déploiement/cutover), déclenchées une fois le code
> poussé. La divergence des DB (§4.1) étant actée comme sans perte, rien
> n'oblige à se mettre sur le VPS avant C4-deploy.

---

> **Méthode pour la suite** : chaque chunk = une mission workflow ou une session
> chunkée (30 min–3 h, livrée + auditée avant d'enchaîner, cf. doctrine
> `feedback_chunk_audit_flow`). Vérifier sur le code, pas sur cette doc, qui est
> un instantané du 2026-06-29. Trancher §4 avant les chunks marqués « §4… ».
