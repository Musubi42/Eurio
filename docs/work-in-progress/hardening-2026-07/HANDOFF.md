# HANDOFF — Hardening Eurio (reprise en session fraîche)

> **Point d'entrée unique.** Lis-le en entier avant d'agir. Épinglé au SHA `6b93aab`
> (`sources-jo-wikipedia`) — si `HEAD` a avancé, re-vérifie avant de suivre (leçon #6).

---

## 0. TL;DR — où on en est (2026-07-05, nuit)

- **État machine** : **Model A actif, lab 100% fonctionnel** (scan intrus+face Dino re-testé OK,
  manual-crop OK). Tout committé + **poussé codeberg+github** (`HEAD=6b93aab`). **Suite ML : 0 rouge
  / 1393 verts.** 3 machines : Mac à jour ; **PC et VPS à `git pull`** (voir §5).
- **Énorme progrès cette session** : harmonisation 3 machines, F05 (A/B/C), F02 (C3/C2/C5), **split
  bookkeeping** (précond flip), et **flip 1a tenté + validé sur son périmètre puis rollback**.
- **🎯 LE PROCHAIN CHANTIER = §2** : compléter le **routage Direction A des writers canoniques du
  lab** (révélé par le flip). Une fois fait → **re-flip → clôt F01** → re-validation globale.
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

### Le problème (ce que le flip a révélé)

Sous le flip (`EURIO_DB_READONLY=1` + `EURIO_DB_PATH=replica`), **toute opération du lab qui édite le
canonique en DIRECT lève `sqlite3.OperationalError: attempt to write a readonly database`** — échec
**BRUYANT** (mode sûr, zéro perte/divergence silencieuse). Reproduit live : `POST
/coins/assets/{id}/manual-crop` → `crop_edit.py:304 apply_manual_crop` → `conn.execute(UPDATE
image_assets…)`.

**Cause racine** : Direction A veut que les écritures canoniques partent au VPS (`/ingest/*`,
writer unique) pendant que les machines dev lisent la réplique ro. F01 a routé CERTAINS writers
(crops/exclude, gate/reject, referential-fix, delete-asset, confusion-map) mais PAS tous, et ceux
qui ont un forward écrivent souvent le **local d'abord** (non gardé sous readonly) → throw avant le
forward. `resolve_db_readonly()` (existe, `store/__init__.py`) n'est **garde d'écriture nulle part**.

### Worklist (writers canoniques reachable du lab, à router)

| Fichier | # writes canoniques | forward `/ingest` déjà ? | action |
|---|---|---|---|
| `review/review_queue_routes.py` | 16 | ❌ | garde readonly + endpoint(s) `/ingest` + forward |
| `store/decisions.py` (`apply_reassign`, `apply_lot_decide`, …) | 12 | ❌ | idem — writers décision review |
| `serving/review_queue/writes.py` | 7 | ❌ | idem |
| `serving/crop_edit.py` (`apply_manual_crop`, `delete_crop`, …) | 4 | ✅ (8 refs) | **garder le write local sous `resolve_db_readonly()`** (le forward existe déjà) |
| `serving/coin_assets_routes.py` | 4 | ❌ | garde + endpoint + forward |
| `serving/{lab,coins}_routes.py` | 1+1 | — | vérifier au cas par cas |

_(Comptes obtenus par grep `INSERT/UPDATE/DELETE (image_assets|coins|review_queue|source_images|coin_source_*|coin_canonical)` ; refaire l'audit précis en début de session.)_

### Le pattern de fix (par writer)

1. **Garder l'écriture locale** : `if not resolve_db_readonly(): conn.execute(<write local>)`.
   Sous le flip → skip le local (pas de throw) ; en Model A → écrit local comme avant.
2. **Forward VPS** : sous `sync_enabled()` (`EURIO_API_URL` posé), POST vers un endpoint
   **`/ingest/*`** (dans `serving/ingest_routes.py`, TOUJOURS monté sur le VPS — les routers
   `review_queue`/`coin_assets`/`referential` sont **skippés** sur le VPS, PIL/cv2 absents, cf.
   leçon #3). Pattern client déjà en place : `client/ingest.py` (`push_crops`, `push_delete_asset`,
   `push_confusion_map`) + `store/*.py` `apply_ingest_*` (validation bruyante). En créer pour :
   reassign, lot-decide, review-queue mutations, coin-assets, manual-crop-géométrie…
3. **Déployer** `server_serve.py` sur le VPS pour exposer les nouveaux `/ingest/*` **avant** de
   re-flipper (les forwards 404 sinon — bruyant).

⚠️ **Attention scan face-write** : `training/training_set_scan.py` écrit `image_assets.face`
(canonique) pendant le scan → même traitement (garde + forward). Le scan a marché en Model A
re-testé, mais throwera sous le flip s'il n'est pas gardé.

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
