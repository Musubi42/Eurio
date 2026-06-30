# Handoff — récupération des résultats de test on-device (cohort-test)

> Pour une session Claude Code fraîche sur le **PC** (Linux, hostname `desktop`, GPU 1080 Ti).
> Branche : `sources-jo-wikipedia`. Tout le contexte produit/archi est ici.
> Date : 2026-06-30.

## 0. Où on en est (TL;DR)

Le pipeline **lab** complet (front → bake → training GPU → export → benchmark →
bundle → APK de test on-device) **fonctionne de bout en bout**, validé en vrai :
l'utilisateur a créé/lancé l'itération depuis le front, scanné ses pièces sur le
Pixel 9a, et obtenu des verdicts corrects. **Blocage actuel = la dernière étape :
récupérer le JSONL des résultats depuis le tel (`cohort-test:pull-tests`).**

- **Itération de référence** : `1fcac3c952a9` (name `reel`, cohorte `mix-zone-17`
  = id `b0299ca0252b`, 16 classes, R@1≈0.85). `completed`.
- **APK installé** : `com.musubi.eurio.cohorttest` sur `Pixel 9a - 16` (Android 16).
  48 tests (16 pièces × 3 conditions) effectués par l'utilisateur sur l'appareil.

## 1. Le blocage immédiat (à résoudre en premier)

```bash
go-task -t app-android/Taskfile.yml cohort-test:pull-tests ITERATION=1fcac3c952a9
```
…reste **bloqué sur la ligne `adb pull`** (pas d'erreur, pas de complétion). Un
`adb shell ls` lancé en debug a **timeout à 2 min** → **adb est hung**, pas un vrai
échec applicatif.

**Important** : ce N'EST PROBABLEMENT PAS le scoped storage. Une tentative
ANTÉRIEURE de `pull-tests` (avant que les tests existent) renvoyait un propre
`adb: error: failed to stat ... No such file or directory` — donc adb **peut**
lire `/sdcard/Android/data/<pkg>/...` sur ce device. Le hang actuel est un état
adb/USB/device transitoire.

**Première chose à faire** :
```bash
adb kill-server && adb start-server && adb devices   # device 5C091JEBF12847 attendu
# réveiller le tel (écran allumé, USB debugging actif), puis :
go-task -t app-android/Taskfile.yml cohort-test:pull-tests ITERATION=1fcac3c952a9
```
La tâche fait : `adb pull <device>/eurio_live_tests/1fcac3c952a9.jsonl →
ml/state/live_test_logs/1fcac3c952a9.jsonl` puis `POST 127.0.0.1:8042/lab/cohorts/_/iterations/1fcac3c952a9/live-tests/sync`
→ §5 du front. Chemin device exact :
`/sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/eurio_live_tests/1fcac3c952a9.jsonl`
(écrit par `LiveTestLogger.kt`, via `getExternalFilesDir`).

**Si adb pull échoue encore après recovery** (scoped storage Android 16) :
- Vérifier la présence du fichier : `adb shell ls -la /sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/eurio_live_tests/`.
- Option propre : faire écrire `LiveTestLogger` dans un dossier lisible par adb
  (Downloads via MediaStore) OU exposer un export. Mais d'abord confirmer que le
  hang n'est qu'adb (probable).

## 2. Serveur backend (doit tourner pour le sync et le front)

Le **ML API tourne sur le port 8042** (lancé cette session, encore up), en mode
**replica + sans --reload** (équivalent `ml:api-replica-prod`) :
```bash
sops exec-env secrets/dev.env 'EURIO_DB_PATH="$PWD/ml/state/eurio.replica.db" \
  ml/.venv/bin/python -m uvicorn serving.server:app --port 8042 --app-dir ml'
```
S'il a été coupé, relance-le ainsi (PAS `ml:api` nu : reload tue les subprocess +
lit la mauvaise DB). Front local : `pnpm -C admin/packages/studio-local dev`
(déjà sur `localhost:5173`, `.env.local` → `VITE_ML_API=8042`).

## 3. Architecture — invariants à connaître (Model B)

- **DB canonique = SQLite sur le VPS derrière `eurio-api`**. Le compute (PC) lit une
  **réplique locale** `ml/state/eurio.replica.db` tirée par `go-task ml:db:pull-replica`
  (via `GET /db/replica`, auth PAT `ingest:run`, env SOPS). Les itérations créées
  localement **ne sont PAS poussées au VPS** (différé) → elles vivent dans la replica.
- **Tout ce qui lit la DB doit honorer `EURIO_DB_PATH`** (corrigé cette session via
  `store.resolve_db_path()` partout). Le serveur le pose via la tâche ; les
  subprocess détachés (`run_*.py`, bench, `build_cohort_bundle`) l'héritent.
- **Maille des labels = `COALESCE(design_group_id, eurio_id)`** : le modèle ArcFace
  prédit des labels de **design_group** (ex. `ad-2euro-standard-t1`), pas des
  eurio_id. Toute comparaison verdict doit être **équivalence design_group**
  (`isCorrectEq` / `EquivalenceMap.areEquivalent` côté Android).
- **Images dans MinIO** : `enrichment-crops` (crops eBay, privé), `numista-canonical`
  (avers canoniques, public via `eurio-images.musubi.dev`). Accès via
  `shared/storage/local_cache.py::local_path` (read-through + retry 403). Creds
  `MINIO_*` dans l'env SOPS.
- **Catalogue Android = `app-android/src/main/assets/app_core.db`** (P6 ; a remplacé
  le legacy `catalog_snapshot.json`).
- **Env** : préfixer les commandes Python/MinIO par `sops exec-env secrets/dev.env`.
  venv = `ml/.venv`. Le devShell nix (Android SDK, JDK17, go-task) est chargé via
  direnv dans le shell interactif.

## 4. Ce qui a été corrigé cette session (10 commits, branche `sources-jo-wikipedia`)

Partant d'un `ModuleNotFoundError: jose`, une chaîne de blocages a été déroulée :

| Commit | Fix |
|---|---|
| (env) | venv périmée → `go-task ml:setup` (installe `python-jose`) |
| `b26dcab2` | retry-backoff borné sur `local_path()` — 403 transitoire MinIO (cache froid) |
| `57532072` | `run_augmentation/iteration/pipeline` honorent `EURIO_DB_PATH` (étaient hardcodés `state/eurio.db`) |
| `b1f8ffcf` | garde-fous launch-training à la maille **classe** (be-2007 sans crops propres ne bloque plus) |
| `9e243dfc` | `prepare_dataset` lit le **staging prebaked** (option b) au lieu du raw `datasets/` |
| `3030fcfe` | aperçu d'augmentation via **MinIO** au lieu de Supabase (retiré sous Model B) |
| `a7e4c582` | bench (`evaluate_real_photos`) + `coin_lookup` + `class_resolver` + `train_embedder` honorent `EURIO_DB_PATH` |
| `3b3f7d0f` | `build_cohort_bundle` honore `EURIO_DB_PATH` |
| `d4cfc70f` | bundle migré **app_core.db** (catalog_snapshot.json retiré) + embeddings filtrés par **classe design_group** (16/16) + fix chemin `i18n.py` (`country_fr.json`) |
| `268d4536` | vignette avers réel (`image_obverse_url` MinIO/canonique) + re-snap réenregistre (plus de boucle) |
| `bc17d955` | **verdict équivalence design_group** (`areEquivalent` gère un id de groupe en entrée ; verdict+compteur sur `isCorrectEq`) + viewfinder `weight(1f)+clipToBounds` (plus d'overlap) |

Backlog/notes annexes : `docs/work-in-progress/storage-hardening/README.md`
(P1 cause racine MinIO 403 côté infra VPS, P2 readiness qui download pour compter,
P3 CORS-sur-500, P4 OOM batch 256, etc.).

## 5. État working tree (à trier)

`git status` montre des modifs non commitées :
- `app-android/src/cohortTest/assets/cohort_bundle/*` (artefacts de bundle régénérés
  par `cohort-test:bundle` ; `catalog_snapshot.json` + `cohort_meta.json` supprimés
  par la migration P6). **À décider** : commiter le bundle régénéré ou le gitignorer
  (c'est un artefact par-itération).
- `ml/eurio_ml.egg-info/*` (bruit de build, cf. backlog P6).
- `MIGRATION-CODEBERG.md`, `docs/work-in-progress/HANDOFF-pc-full-training.md`
  (modifs hors périmètre de cette session).

## 6. Tests

`pytest` ciblé vert sur le périmètre touché. **1 échec pré-existant connu**
(`tests/test_lab_api.py::test_delete_iteration_forbidden_while_running`) — hors
scope, vérifié non-régression.

## 7. Mission de la nouvelle session

1. **Débloquer `cohort-test:pull-tests`** (recover adb d'abord ; cf. §1). Objectif :
   le JSONL des 48 tests remonte dans `ml/state/live_test_logs/` puis se **sync dans
   §5** du front (`/lab/cohorts/mix-zone-17/iterations/1fcac3c952a9`).
2. Vérifier l'affichage des résultats live-tests dans §5 (R@1 on-device, par
   condition, confusions).
3. Trier le working tree (§5 ci-dessus) et committer ce qui doit l'être.
