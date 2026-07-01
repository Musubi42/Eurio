# R3 — Itérations canoniques (sync Mac ↔ PC + origine)

> Design pour rendre les **itérations lab** visibles sur toutes les machines.
> Créé le 2026-07-01. Fait suite au déplacement des **recettes** vers le canonique
> (`refactor(recipes)`, `2ca9de55`, déployé). Cadrage **validé** par le PO :
> **push-aux-transitions + métadonnée-canonique-MVP + origine-hostname**.

## Problème

Aujourd'hui, une itération créée via le ML local (`serving.server` sur
`state/eurio.db` ou la réplique) écrit dans la **DB locale de la machine**. La
réplique est un *pull* read-only du VPS, écrasé au prochain `ml:db:pull-replica`.
→ **les itérations ne remontent jamais au canonique** : celles du Mac et du PC ne
se voient pas. (Constaté : `1fcac3c9` vit sur le PC, `74ba5d2e140e` sur le Mac ;
aucune des deux n'est chez l'autre.)

C'est le **brief R3 de Model B** (« training --push au canonique »), jusqu'ici
différé.

## But (MVP)

1. La **liste d'itérations** est la même où que tu sois (Mac/PC) : chaque itération
   créée sur une machine remonte au **canonique VPS**.
2. Une **colonne d'origine** (`mac` / `pc`) dans la liste dit où l'itération a été
   calculée (et donc où vivent ses artefacts lourds).

## Décisions (validées)

| Axe | Choix MVP | Raison |
|---|---|---|
| **Écriture** | **1a — push aux transitions** : le calcul reste local ; à chaque étape (create → bake → train → completed/failed → benchmarked) on **pousse un snapshot** de la row + métriques au canonique. Cohérence *eventual*. | Le compute lourd (bake/train, cv2/torch) ne peut pas vivre sur l'image lean du VPS. On ne bloque jamais un run sur la joignabilité du canonique. |
| **Artefacts** | **MVP — métadonnée seule canonique** : id, cohort, recette, config, statut, verdict, résumés de métriques, origine, timestamps. Les artefacts lourds (tflite / embeddings / checkpoints) **restent sur la machine** qui a calculé. | « Voir toutes les itérations partout » vite, sans embarquer la migration artefacts→MinIO. La colonne origine dit où sont les artefacts. |
| **Origine** | **hostname** → map (`…MacBook-Air-Oim`→`mac`, `desktop`→`pc`, `nixos`→`vps`), fallback = hostname brut. Colonne `created_on` nullable, backfill = `null`. | Zéro config, aligné sur le dispatch `.envrc`. |

**Conséquence assumée (MVP)** : une itération PC vue sur le Mac montre ses
**chiffres** (R@1, loss, verdict) mais pas ses artefacts. Les actions qui en
dépendent (re-bench, build test-app, live-tests) restent dispo **sur la machine
d'origine** ; ailleurs elles sont grisées avec une note « artefacts sur `<origin>` ».
La migration artefacts→MinIO (Full) est un chantier ultérieur.

## Modèle de données

`experiment_iterations` (canonique) : ajouter **`created_on TEXT`** (nullable).
Toutes les autres colonnes existent déjà (id, cohort_id, name, hypothesis,
recipe_id, variant_count, training_config_json, status, training_run_id,
benchmark_run_id, verdict, verdict_override, delta/diff_json, notes, error,
timestamps, augmentations_seed). Le snapshot poussé = la row telle quelle +
`created_on` + les résumés (`training_summary` / `benchmark_summary` — déjà
dérivés côté API).

Migration : `ALTER TABLE experiment_iterations ADD COLUMN created_on TEXT;`
(idempotent via `db_migrate` sur le canonique + `state/schema.sql`).

## Endpoints canoniques (légers, sur `server_serve`)

Nouveau router **léger** `serving/iteration_sync_routes.py` (Store seul, aucun
import cv2/torch — mêmes contraintes que `recipe_routes`) :

- `GET /iterations?cohort_id=` → liste **toutes** les itérations (toutes machines).
  Read-only, scope `coins:read` (ou un `lab:read`). Sert la liste du front.
- `GET /iterations/{id}` → détail métadonnée.
- `PUT /iterations/{id}` → **upsert** d'un snapshot poussé par une machine de
  calcul. Scope `ingest:write` (le même que `db:pull-replica`). Idempotent,
  last-writer-wins **par itération** (chaque id uuid4 est possédé par une seule
  machine → pas de conflit réel).

> Ces routes ne remplacent PAS les routes lab lourdes (`/lab/cohorts/.../bake`,
> `launch-training`) : celles-là restent sur le ML local `:8042` (cv2/torch). Le
> canonique ne stocke que l'**état**, pas le calcul.

## Push depuis le compute (local → canonique)

- Ajouter `put_json()` à `client/http.py` (trivial, symétrique de `post_json`).
- Helper `serving/iteration_sync.py::push_iteration(iid)` : lit la row locale +
  résumés, `PUT /iterations/{iid}` au canonique. **Best-effort** : échec réseau →
  log + on continue (le run local n'est jamais bloqué). Un `resync` de rattrapage
  se fait au prochain create/list.
- Points d'appel dans `IterationRunner` : après `create_iteration`, en fin de
  bake, au lancement du training, à `completed`/`failed`, après benchmark. (~5
  hooks, un `push_iteration(iid)` chacun.)
- Auth : le compute pousse avec `EURIO_API_TOKEN` (PAT, déjà utilisé par
  `pull-replica`) vers `EURIO_API_URL=https://eurio-api.musubi.dev`.

## Origine

`shared/machine.py::machine_origin()` (pur, léger) : `socket.gethostname()` → map
`{Musubi42s-MacBook-Air-Oim: mac, desktop: pc, nixos: vps}`, fallback = hostname.
Stampé dans `created_on` à la **création** de l'itération (côté runner), puis
poussé. Source de vérité partagée avec le dispatch `.envrc` (à garder alignée).

## Front

- `useLabQueries` : la **liste** d'itérations d'une cohorte lit désormais le
  **canonique** (`eurioApi.get('/iterations?cohort_id=')`) → montre Mac+PC.
- Le **détail** métadonnée + actions légères → canonique. Les actions **lourdes**
  (bake/train/bench/live-tests) restent sur `ML_API` et ne sont proposées que si
  `origin === thisMachine` (sinon grisées + note « artefacts sur `<origin>` »).
  `thisMachine` dérivé d'un `GET /whoami`-léger ou du `machine_origin` exposé par
  le ML local `/health`.
- Nouvelle **colonne « Origine »** dans la table d'itérations (badge `mac`/`pc`).

## Découpage proposé (chunks, testables)

1. **R3.1 — canonique read/write** : migration `created_on` + router léger
   `iteration_sync_routes` (`GET list/detail`, `PUT upsert`) + tests. Monté sur
   `server_serve`. *(N'affecte encore aucun run.)*
2. **R3.2 — push depuis le runner** : `put_json` + `push_iteration` + `machine_origin`
   + les ~5 hooks dans `IterationRunner`. Best-effort, testé (mock transport).
   Smoke : créer une itération locale → vérifier qu'elle apparaît au canonique.
3. **R3.3 — front** : liste depuis le canonique + colonne origine + gating des
   actions lourdes hors-origine.
4. **R3.4 — backfill** (optionnel) : pousser les itérations locales existantes
   (Mac `74ba5d2e`, PC `1fcac3c9`) au canonique une fois, pour ne pas les perdre.

## Non-objectifs (MVP — explicites)

- **Pas** de migration artefacts → MinIO (tflite/checkpoints restent locaux). →
  chantier « R3-Full » ultérieur si on veut les actions lourdes cross-machine.
- **Pas** de résolution de conflit multi-writer (chaque itération = 1 machine).
- **Pas** de bascule des routes lab lourdes sur le canonique.

## Questions ouvertes

- Scope exact des routes (`lab:read` / `ingest:write` vs réutiliser `coins:read`) —
  à trancher avec le modèle de scopes auth-redesign.
- Exposer `machine_origin` du ML local via `/health` (pour le gating front) vs un
  petit `/whoami`.
