# HANDOFF — Hardening Eurio (reprise en session fraîche)

> **Point d'entrée unique.** Lis-le en entier avant d'agir. Épinglé au SHA `ce3a802`
> (`sources-jo-wikipedia`, chunks C3+B2a livrés) — si `HEAD` a avancé, re-vérifie avant de
> suivre (leçon #6).

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
- **Effet : le flip est maintenant LIVABLE pour le cœur du lab** (toutes décisions review/funnel/
  lot + reassign → VPS ; recrop + delete manuels → OK sous le flip ; tout le reste refuse
  proprement en 503). Reste B2b + stragglers (§2) avant flip 100%.
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
| **B1 — décisions avec jumeau VPS** (`decisions.py apply_*`, `review_queue/writes.py`) : reassign, accept/reopen/training-eligible, lot-decide, decide/skip/reject/restore | le **front** appelle le jumeau VPS via `eurioApi` (chemin identique) | ✅ **FAIT** : single+funnel déjà sur `eurioApi` ; **lot-decide** reroutée `8dc06b3` (dernier gap) |
| **B2 — writers cv2 lourds** (compute obligatoirement local) : recrop, delete, **add-crop**, lot detect/sync-crops | garde `resolve_db_readonly()` (skip write local) + forward `/ingest` (compute local → push VPS) | 🟡 **B2a FAIT** (`ce3a802` : recrop+delete gardés, forwards existants) ; **B2b RESTE** |
| **B3 — filet de sécurité** : tout write canonique local résiduel sous le flip | 1 exception handler DRY → 503 `canonical_readonly` | ✅ **FAIT** (`8dc06b3`, `server.py`) |

### RESTE (B2b + stragglers) — le vrai backlog

1. **B2b — `create_manual_crop` (add-crop)** : écrit un NOUVEAU crop + row review, mais n'a **pas**
   de forward `/ingest` (utilise encore l'event-log défunt `emit_state_event` row_ops). Sous le
   flip → 503 (refus propre via le handler). Pour le rendre **fonctionnel** sous le flip : créer un
   endpoint `/ingest/*` « nouveau crop + review » (client `push_*` + `store.apply_ingest_*` +
   **déployer VPS**). Idem lot **detect** (`detections_json`) + **sync-crops** (review_queue_routes).
2. **Stragglers SANS jumeau VPS** (vivent SEULEMENT dans `review/review_queue_routes.py`, skippé sur
   le VPS) : `requalify-single` / `requalify-lot` (+batch) / `correct-listing` / `move-lane→manual`.
   Ce sont des décisions **SQL-pures** → **DÉCISION À PRENDRE** : (a) extraire un jumeau lean dans
   `review_queue/writes.py` ou `funnel_writes.py` (comme decide/lot l'ont été) + reroute front
   `eurioApi`, OU (b) acter ces features **indisponibles sous le flip** (refus 503, features rares).
3. **C6 (event-log)** : `emit_state_event`/`emit_field_event` écrivent ENCORE le canonique
   `image_state_events`+`image_state_current`. Pas bloquant (gardes + handler couvrent le readonly),
   mais c'est du poids mort sous Direction A → retrait C6 à cadrer (cf. `migration-direction-a.md`).
4. **Scan face-write** : `training/training_set_scan.py:469` écrit `image_assets.face` (déjà gardé
   par `sync_enabled()` + push_faces ? **à re-vérifier** avant re-flip — sinon throw/503 au scan).

### Le pattern (B2b, par writer cv2)

`client/http.py` a le client générique (`post_json`/`delete_json` → `EURIO_API_URL` + Bearer).
`client/ingest.py` a `push_crops`/`push_delete_asset`/`push_confusion_map` + `store/*.apply_ingest_*`
(validation bruyante). Pour add-crop : nouvel endpoint `/ingest/*` (VPS lean, TOUJOURS monté ;
`review_queue`/`coin_assets` sont skippés — PIL/cv2 absents, leçon #3) + `push_*` + `apply_ingest_*`,
puis **déployer `server_serve.py` VPS AVANT de re-flipper** (sinon forward 404).

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
