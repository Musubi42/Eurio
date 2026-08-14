# Architecture Eurio — où vit la donnée, qui écrit quoi

> **Lis ce fichier avant de chercher où se trouve une donnée.** Il décrit l'état
> **réel** au 2026-08-14, vérifié dans le code, pas l'état visé.
>
> Détail des artefacts (producteur, consommateur, régénérable ?) : [`artifacts.md`](./artifacts.md).
> Décisions et leur raison : [`../adr/README.md`](../adr/README.md).
> Chantier de refonte en cours : [`../work-in-progress/repo-refactor/README.md`](../work-in-progress/repo-refactor/README.md).

## En une phrase

Trois stockages, chacun avec un rôle net : **SQLite sur le VPS** est le canonique,
**MinIO** porte les images, **Supabase** est une projection read-only pour l'app en prod.

## Les trois stockages

| Stockage | Rôle | Écrivain | Lecteurs |
|---|---|---|---|
| **`eurio.db`** — SQLite WAL, VPS `/var/lib/eurio/eurio.db` | **Canonique.** Référentiel, review, cohortes, itérations d'entraînement | `eurio-api` **uniquement** (writer unique, Direction A) | Mac et PC via une **réplique read-only** |
| **MinIO** — `eurio-s3.musubi.dev` | **Images.** Raws scrapés, crops normalisés, canoniques Numista | Mac et PC (upload direct) | Tous, via cache read-through |
| **Supabase** — Postgres hébergé | **Projection app-facing**, read-only côté app | poussé depuis `eurio.db` par `ml/export/` | App Android en prod, proto en mode `live`, build de `loan` |

**Il n'y a pas de Postgres auto-hébergé sur le VPS.** Le Postgres du projet, c'est
Supabase. Confusion fréquente : `infra/eurio-api/docker-compose.yml` monte
`./data:/var/lib/eurio` avec `EURIO_DB_PATH=/var/lib/eurio/eurio.db` — c'est du SQLite.

### Buckets MinIO

| Bucket | Contenu | Accès |
|---|---|---|
| `numista-canonical` | Images de référence Numista | lecture **anonyme** via CDN `eurio-images.musubi.dev` |
| `enrichment-raws` | Photos scrapées brutes (eBay…) | privé, URL signée |
| `enrichment-crops` | Crops normalisés — entrée d'entraînement | privé, URL signée 6 h |

Pas de bucket modèles/datasets à ce jour. Versioning S3 **délibérément désactivé**
(cf. `infra/minio/README.md` §Anti-patterns) : la protection, c'est tarball hebdo + audit.
Un versionnage d'artefact doit donc passer par la **clé d'objet** ou un **manifeste sha256**.

## Les trois machines

| Machine | Rôle | Particularité |
|---|---|---|
| **Mac** (`Musubi42s-MacBook-Air-Oim`) | Dev, admin, scraping, crop, review | Pas de GPU. `ml/prod/` **n'existe pas** → ne peut pas promouvoir d'assets |
| **PC** (`desktop`, NixOS, 1080 Ti) | Entraînement | Se synchronise par `git fetch && git reset --hard` |
| **VPS** (`nixos`) | Writer canonique, MinIO, API, fronts | devShell allégé (`go-task` + `mc`) |

Le devShell est segmenté **par machine, pas par module** (`flake.nix`) : une session
Android charge toute la stack Python/CUDA.

## Les flux réels

### 1. Métadonnées — automatisé, propre

```
VPS eurio.db (writer unique)
  │  sqlite3_rsync incrémental (ssh, clé dédiée, forced-command)
  │  fallback : GET /db/replica (snapshot VACUUM INTO + sha)
  ▼
Mac / PC : ml/state/eurio.replica.db  (READ-ONLY)
  │  écritures via HTTP : POST /ingest/run, /ingest/crops, /ingest/dino
  ▼
VPS applique (idempotent, UPSERT + garde batch_sha)
```

Commande : `go-task ml:db:pull-replica`. **Ne passe jamais par git.**

### 2. Images — automatisé via MinIO

Scrape/crop écrivent dans MinIO ; la lecture passe par `local_path(bucket, key)`
(`ml/shared/storage/local_cache.py`) : cache read-through sur disque, racine
`EURIO_CACHE_ROOT` (défaut `~/.cache/eurio`), éviction LRU.

⚠️ **Pas de fallback par design** : MinIO injoignable ou clé absente ⇒ `FileNotFoundError`.
Toute chaîne qui en dépend devient **non fonctionnelle hors ligne**.

### 3. Modèles et poids — MANUEL, VIA GIT ⚠️

C'est la dette la plus visible. `best.pt` et les `.tflite` sont **force-ajoutés**
dans git (`ml/output/` est pourtant gitignoré) parce que **git sert de transport
Mac→PC** : cf. commit `d1f5812 "Add .pt and .tflite for PC"` et
`docs/work-in-progress/HANDOFF-pc-full-training.md` qui prescrit `git reset --hard`.

**Conséquence à connaître avant tout nettoyage** : sortir ces fichiers de git sans
remplacement casse le PC **silencieusement** au prochain `reset --hard`.
Cible décidée : [ADR-004](../adr/004-artefacts-binaires-hors-git.md).

### 4. Photos éditées Mac → PC — MANUEL, one-shot

`infra/sync/rsync-from-mac.sh` puis `scripts/migrate_to_minio` sur le VPS. Le README
le dit : *« le transfert se fait une fois »*. Pas de synchro continue.

## Chaîne du catalogue offline (app Android)

```
eurio.db (VPS)
  │  ml/export/app_export/run.py  →  push PostgREST
  ▼
Supabase  (projection app-facing v2 : table `coin`)
  │  ml/export/build_app_core.py  (LIT Supabase, pas eurio.db)
  ▼
app_core.db  →  écrit DIRECTEMENT dans app-android/src/main/assets/  →  commité
```

**Pourquoi passer par Supabase et pas par `eurio.db` ?** C'est délibéré : le docstring
de `build_app_core.py` l'assume — *« C3 is a strict SUBSET of Supabase. By reading from
Supabase (not eurio.db) we guarantee C3 ⊆ C2 by construction »*. Le catalogue offline ne
peut donc jamais contenir quelque chose que l'app ne retrouverait pas en ligne.

**Tension connue** : ça fait de Supabase un maillon **obligatoire** du build, ce qui
contredit « Supabase = legacy en cours de retrait » (`CLAUDE.md`). Non tranché.

⚠️ `AppCoreBootstrapper.kt` gate le rechargement sur `APP_CORE_VERSION`, **constante
codée en dur, valeur 1, jamais incrémentée**. Un `app_core.db` au contenu neuf sans
incrément ⇒ l'app **skippe le bootstrap en silence**.

## Trois mécanismes de déploiement d'assets — dont un mort-vivant

| # | Entrée | Source → cible | État |
|---|---|---|---|
| A | `go-task ml:deploy` | `ml/output/` → assets Android | ⚠️ **obsolète** : `ml/serving/server.py` déclare `ml/output/` supprimé, la tâche y pointe toujours |
| B | `python -m scripts.promote_prod_assets` | `ml/prod/current/` → assets | courant, **PC uniquement** |
| C | `POST /export/deploy` | `ml/prod/current/` → assets | ⚠️ **skip silencieux** si source absente : renvoie `200 {count: 0}` |

Et `coin_detector.tflite` **n'est couvert par aucun des trois** : copié à la main,
jamais retouché depuis le déplacement `app/` → `app-android/`. Probablement désynchronisé
du `best.pt` tracké.

## Ce qui n'existe pas (et qu'on croit souvent exister)

- **Aucune CI.** Pas de `.github/workflows`, pas de hook git. `go-task tokens:check`
  existe mais n'est lancé que localement ou par un agent (`actions.yml`).
- **Aucune tâche « lancer toute la suite de tests ».** Seulement 3 invocations pytest ciblées.
- **Aucun générateur de types** ml ↔ front. Les types TS sont retapés à la main.
  `ml/swagger.yaml` est la spec **de Numista**, pas d'Eurio, et n'est référencée nulle part.
- **`supabase/types/database.ts` n'a aucun import** — c'est de la doc de schéma.
