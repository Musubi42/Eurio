# HANDOFF — Hardening Eurio (reprise en session fraîche)

> **Point d'entrée unique.** Lis-le en entier avant d'agir. Épinglé au SHA `b03c86c`
> (`sources-jo-wikipedia`, tail Direction A livré+déployé sauf add-crop) — si `HEAD` a avancé,
> re-vérifie avant de suivre (leçon #6).

---

## 0. TL;DR — où on en est (2026-07-06)

- **État machine** : Model A actif. Branche `sources-jo-wikipedia`, `HEAD` avancé de 3 commits
  depuis `6b93aab` (voir ci-dessous). Suite verte sur le périmètre touché.
- **🎯 CHANTIER §2 EN COURS — approche PO = « C3 front-reroute + gardes »** (PAS les /ingest
  par-writer du plan initial : l'audit précis a montré que les writers de décision ont DÉJÀ
  leurs jumeaux canoniques sur le VPS + que le front route DÉJÀ la plupart via `eurioApi` →
  /ingest par-writer aurait dupliqué `funnel_writes.py`, R0). Détail corrigé en §2.
- **Fait cette session (2 chunks committés + vérifiés)** :
  - `8dc06b3` **C3 hot-path** : `decideLot` (front) reroutée `ML_API`→`eurioApi` (dernier gap
    décision) + **garde DRY** = 1 exception handler `sqlite3.OperationalError` dans `server.py`
    (write canonique local sous le flip → 503 `canonical_readonly` actionnable, pas 500 opaque).
  - `ce3a802` **B2a** : gardes `resolve_db_readonly()` sur `apply_manual_crop`+`delete_crop`
    (compute local + forward VPS, skip write local sous le flip) — clôt le live-repro manual-crop.
- **Tail QUASI FINI + DÉPLOYÉ VPS (2026-07-06)** — flip validé sur PC par le PO (scan intrus +
  fast-dino OK). Commits `f36a22a` (stragglers → jumeaux lean VPS + front eurioApi) + `b03c86c`
  (B2b détect → `/ingest/detections`). **VPS rebuild + vérifié live** : les 4 jumeaux review
  (correct-listing/requalify-lot/requalify-single/move-lane) + `/ingest/detections` montés
  (401 sans auth, pas 404) ; healthz 200. Suite ML **1404 verts / 0 rouge**.
- **Effet : le flip est LIVABLE pour tout le lab SAUF add-crop** (toutes décisions review/funnel/
  lot + reassign + requalify/lane/correct → VPS ; recrop/delete/scan-face/détect/**sync-crops** OK
  sous le flip). **SEUL RESTANT = add-crop** (`create_manual_crop`) : refuse proprement en 503 sous
  le flip (handler DRY), forward correct = chunk dédié (cf. §2). Outil de rattrapage rare.
- **Flip `flake.nix` = working-tree Mac, NON committé** (laissé au PO pour éviter de perturber sa
  session PC active + conflits de merge inter-machines ; réversible : `git checkout flake.nix`).
- **Backups pré-flip faits** (Mac+VPS, `integrity=ok`) — cf. §3. Rien perdu, réplique jamais écrite.

---

## 1. Fait & vérifié cette session (compressé)

| Chantier | État | Commits clés | Vérif |
|---|---|---|---|
| **Harmonisation Mac↔PC↔VPS** | ✅ | `c351113`→`1449a1d` | vignettes canoniques eurio_id, best-of live-tests, device auto (CUDA PC/MPS Mac/CPU VPS), route canonique live 302→200 |
| **F05-B** (bugs prod tests) | ✅ | `117ad75` (wipe non-destructif, 9+ tables FK→coins), `771821c` (seed source_registry bootstrap) | B2 déjà fixé ; tests wipe verts |
| **F05-A/C** (réparation tests) | ✅ | thème `fix(tests):` | imports `training.*`, stub YOLO, fixture M:N, re-route `referential.scrape_lmdlp` |
| **F02 C3/C2/C5** (décommission Supabase, **C1=Option A**) | ✅ code | `c9481c8` | zone_resolver→SQLite ; confusion-map→eurio.db (Direction A, `store/confusion.py`+`/ingest/confusion-map`+client, guard `--reload` refait) ; export routé + Option A doc |
| **Split bookkeeping** (précond flip) | ✅ | `1a43426`, `7f3f3e0` (migration) | cohort_jobs/scans/results → `store.local_state_store()` (eurio.local.db writable) ; 3 FK cross-DB retirées ; 2-conn (pas d'ATTACH) ; simulation flip OK |
| **Flip 1a** | ⏪ tenté + **rollback** | `af27126` (activé), `6b93aab` (désactivé) | **prouvé sain** (split écrit local, lecture réplique ro, write canonique refusé bruyamment) — MAIS révèle §2 |

Détail par fiche : `README.md` (index 58 findings) + `01-…md` (F01 sync) + `02-…md` (Supabase) +
`05-…md` (tests). Mémoires : `project_hardening_review_2026_07`, `project_sync_direction_a_single_writer`,
`project_catalog_delivery_strategy`.

---

## 2. 🎯 CHANTIER ACTIF — compléter le routage Direction A des writers canoniques

### ⚠️ Le plan initial était FAUX — audit précis (2026-07-06) qui le corrige

Le HANDOFF disait « créer un `/ingest/*` par writer (reassign, lot-decide, review-queue…) ».
**L'audit précis montre que c'est redondant** : les writers de **décision** ont DÉJÀ leurs
jumeaux canoniques montés **inconditionnellement** sur le VPS (`serving/funnel_writes.py`,
`serving/review_queue/writes.py`, `serving/lab_read`), **chemins publics identiques** aux routes
locales lourdes. Et le **front route DÉJÀ** la plupart des writes canoniques via le client
`eurioApi` (→ `eurio-api.musubi.dev`), distinct de `ml-api.ts` (→ `:8042` local). Construire des
`/ingest` par-writer aurait **dupliqué `funnel_writes.py`** (R0). → **PO a tranché : approche
« C3 front-reroute + gardes »** (`AskUserQuestion` 2026-07-06).

Les writers tombent en **3 buckets réels** :

| Bucket | Writers | Fix réel | État |
|---|---|---|---|
| **B1 — décisions avec jumeau VPS** (`decisions.py apply_*`, `review_queue/writes.py`) : reassign, accept/reopen/training-eligible, lot-decide, decide/skip/reject/restore | le **front** appelle le jumeau VPS via `eurioApi` (chemin identique) | ✅ **FAIT** (`8dc06b3` lot-decide + single/funnel déjà OK) |
| **B1bis — stragglers SANS jumeau** (requalify-lot/single, correct-listing, move-lane) | extraire primitive SQL-pure → jumeau lean `review_writes` → front `eurioApi` (comme decide/lot) | ✅ **FAIT + DÉPLOYÉ** (`f36a22a`) — batch requalify (maintenance, no-front) reste 503-sous-flip, assumé |
| **B2 — writers cv2 lourds** : recrop, delete, scan-face, lot **detect**, **sync-crops**, add-crop | garde `resolve_db_readonly()` + forward `/ingest` (compute local → push VPS) | ✅ **FAIT** recrop/delete (`ce3a802`) + scan-face (`11dd11b`) + **detect** (`b03c86c`, `/ingest/detections` déployé) ; sync-crops OK par composition. 🟡 **add-crop RESTE** |
| **B3 — filet de sécurité** : tout write canonique local résiduel sous le flip | 1 exception handler DRY → 503 `canonical_readonly` | ✅ **FAIT** (`8dc06b3`, `server.py`) |

### RESTE — le vrai backlog (réduit à 1 writer + 2 items de fond)

1. **add-crop (`serving/crop_edit.create_manual_crop`) — SEUL writer non fonctionnel sous le flip.**
   Crée un NOUVEAU crop + row review. **Fail-clean 503** aujourd'hui (handler DRY) → SÛR mais pas
   fonctionnel. Forward CORRECT = chunk dédié : (a) `/ingest/crops/add` (`store.crops.apply_ingest_add_crop`
   = INSERT image_assets via `upsert_image_asset` cv2-free + INSERT review_queue) ; (b) **remonter
   AUSSI les prédictions Dino** (`push_dino_predictions`, endpoint `/ingest/dino` existe) car
   `compute_lane` en dépend ; (c) **recomputer la lane côté VPS** (vérifier `review.review_lanes`
   cv2-free) — un forward qui miscompute la lane review serait pire qu'un 503 (R0). Utilisé par
   l'add-crop manuel ET la branche CREATE de sync-crops (rattrapage rare de pièces ratées).
2. **C6 (event-log)** : `emit_state_event`/`emit_field_event` écrivent ENCORE le canonique
   `image_state_events`+`image_state_current`. Pas bloquant (gardes + handler couvrent le readonly),
   mais poids mort sous Direction A → retrait C6 à cadrer (cf. `migration-direction-a.md`).
3. **Commit du flip** : `flake.nix` (`${flipHook}` dans mac+pc shells) est en working-tree, NON
   committé (choix : ne pas perturber la session PC active du PO + éviter conflits de merge). Le PO
   le committe quand il veut Direction A durable multi-machines.

### Le pattern (déjà rôdé, pour le RESTE)

- **Décisions SQL-pures** → primitive `store/decisions.py` (DecisionError) + jumeau lean
  `review_queue/writes.py` (chemin identique, `_commit`) + heavy delegate + front `eurioApi` +
  **deploy VPS**. Exemples faits : decide/lot/requalify/correct/lane.
- **Writers cv2** → garde `resolve_db_readonly()` (skip local) + forward `/ingest/*`
  (`store.crops.apply_ingest_*` cv2-free + `client.ingest.push_*` gated `sync_enabled()`) +
  **deploy VPS**. Exemples faits : recrop/delete/scan-face/detect.

### Preuve que le flip marche + comment re-flipper

Le flip est **prouvé sain** (2026-07-05) : `EURIO_DB_PATH=replica` + `READONLY=1` → `CANONICAL_DB`=réplique,
`Store` ro, write canonique → `OperationalError`, **bookkeeping cohort_* écrit bien `eurio.local.db`**
(20 jobs migrés visibles). Le patch est **prêt** : `flipHook` est **défini** dans `flake.nix` (juste
retiré des shells). **Re-flipper** = remettre `${flipHook}` dans `macShell` ET `pcShell` (PAS
`vpsShell`) → `direnv reload`. Réversible pareil (le retirer). Runbook complet : `01-…md §6`.

---

## 3. Backups pré-flip (2026-07-05, `integrity=ok`)

`~/Documents/Musubi42/eurio-db-backups/pre-flip-20260705-213136/` :
- `eurio.db` 98M (Mac canonique) · `eurio.local.db` 1.1M (bookkeeping) · `eurio.replica.db` 104M
- `vps-eurio.db` 113M (VPS canonique rapatrié)

VPS aussi : `/opt/eurio/infra/eurio-api/data/backups/eurio.db.pre-flip-*` (container). **Restore** =
`sqlite3` `.backup` inverse ou `cp`. Le flip ne change que la SOURCE de lecture → rien à restaurer
sauf incident.

---

## 4. Reste après le re-flip (backlog)

- **Re-validation globale F01→F08** (ensemble, après re-flip).
- **F02 résidus** (fiche `02-…md`) : **C4 coins_review = DÉCISION PO** (modèle données feature
  n'existe plus dans eurio.db, superseded review-funnel → porter+réconcilier front `variant_canonical_*`
  OU retirer la feature legacy ; garde dépendance `service_role`) · **C2** : déployer VPS
  `/ingest/confusion-map` · **C5** : créer clé Supabase scopée (dashboard) · **C6** : purger
  `VITE_SUPABASE_*` du SOPS.
- **Fiches non démarrées** : F03 (Android caméra/bind), F04 (front health-checks), F06 (duplication
  app_core 3-langages), F07 (atomicité `lab_routes` autocommit), F08 (garde-fous R7). Cf. `README.md`.
- **F05 #8** : couverture front `studio-local` (vitest, dette LOW).

---

## 5. Comment reprendre (démarrage session fraîche)

1. **Synchroniser** : `git pull` sur Mac (si besoin), **PC** (`ssh -A pc … git pull github` — codeberg
   https échoue en non-interactif) et **VPS** (`ssh -A serverOimNixDontpanic 'cd /opt/eurio && git pull'`).
   ⚠️ **PC** : au premier usage du split, supprimer tout `ml/state/eurio.local.db` antérieur au
   changement FK (schéma stale ; état local régénérable ; le script de migration le détecte et le
   signale) puis lancer `./.venv/bin/python -m scripts.migrate_bookkeeping_to_local`.
2. **Attaquer §2** : refaire l'audit précis des writers canoniques (grep worklist), puis router
   chunk par chunk (garde `resolve_db_readonly` + endpoint `/ingest` + forward client), déployer VPS,
   re-flipper, re-tester le lab-live (walkthrough §6 de `01-…md`).
3. **Puis** re-validation globale + backlog §4.

**Prompt de reprise suggéré** : « Reprends le hardening Eurio au chantier "compléter le routage
Direction A des writers canoniques" (HANDOFF §2). Model A actif, tout poussé `HEAD` à jour, suite 0
rouge. Objectif : router chaque writer canonique du lab (garde readonly + forward /ingest) pour que
le flip 1a soit livable, puis re-flip + re-validation globale. Commence par l'audit précis des
writers (worklist HANDOFF §2). »

---

## 6. Leçons transverses (à ne pas refaire)

- **#1 séquencement** : `READONLY=1` avant d'avoir routé/fermé TOUS les writers → throws (bruyant,
  sûr) ou no-op (silencieux, mortel). Le flip est le SEUL test qui prouve la complétude du routage
  Direction A — on ne peut pas le savoir sans flipper + exercer le lab (vécu cette session).
- **#3 VPS lean** : `referential`/`review_queue`/`coin_assets` **skippés** sur le VPS (PIL/cv2
  absents) → toute mutation canonique routée doit passer par `ingest_routes.py` (toujours monté).
  Vérif runtime : `ssh serverOimNixDontpanic 'docker exec eurio-api python -c "from serving.server_serve import app; [print(sorted(r.methods), r.path) for r in app.routes if getattr(r,\"path\",\"\").startswith(\"/ingest\")]"'`.
- **#4 sous-agents** : F05/F02 délégués à des worktrees isolés (ne pas pousser) → **review + re-vérif
  dans le checkout principal** (le worktree n'a pas les artefacts gitignorés → faux rouges). Les 2
  agents ont eu un bon jugement (F02 s'est arrêté sur C4 plutôt que d'inventer du produit — R0).
- **#5 zsh** : pas de word-splitting sur variables non quotées ; `docker exec` a besoin de `-i` pour
  lire un heredoc stdin ; `--include=*.py` doit être quoté (glob zsh).
- **#6 doc à jour** : tout chunk qui ferme un point MAJ ce fichier dans la foulée (épinglé au SHA).
- **#7 nix** : ne PAS interpoler un path nix `./ml/state/eurio.replica.db` en éval flake pure (copie
  ~108 Mo dans le store) — passer par `$PWD` dans un shellHook (racine repo au chargement direnv).
- **#8 split local-state** : les 3 tables bookkeeping n'ont **aucun JOIN SQL** au canonique (pont
  Python via liste d'eurio_ids) → 2 connexions séparées suffisent, pas d'ATTACH. Leurs FK cross-DB
  (→experiment_cohorts, →image_assets) ont dû être **retirées** de schema.sql (impossibles cross-fichier).
