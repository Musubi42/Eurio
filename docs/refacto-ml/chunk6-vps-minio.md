# Chunk 6 — Provisioning MinIO côté VPS pour le lease `eurio.db`

> **Doc de handoff** à confier à une session Claude Code **sur le VPS**. Objectif :
> préparer MinIO (déjà installé sur le VPS) pour héberger la copie canonique de
> `eurio.db` que Mac et PC se partagent via un verrou. Le travail client (Mac/PC)
> est déjà fait — voir `ml/store/lease.py`. Cette doc ne couvre **que** le serveur.

## Contexte (pourquoi)

L'admin ML tourne sur deux machines (Mac = prépare cohortes/référentiel/review,
PC = entraîne/bench), **séquentiellement dans le temps**, sur une base SQLite
unique `eurio.db` (doctrine SQLite-only). On a écarté libSQL/`sqld` : le client
Python libSQL ne supporte ni `row_factory`, ni `create_function` (nos UDFs phash),
ni `executescript` — un swap de driver casserait tout. À la place : **modèle
lease**. La copie canonique vit dans MinIO ; une machine la *pull*, pose un
verrou, travaille en `sqlite3` standard, puis *push* et libère. Aucune écriture
concurrente possible → pas de corruption, pas de merge binaire.

## Contrat client (ce que Mac/PC vont faire)

Le client utilise le **même client boto3 et les mêmes creds** que la couche
images (`ml/storage/__init__.py`), via les variables d'env déjà en place :

| Variable | Rôle |
|---|---|
| `MINIO_ENDPOINT` | host MinIO (ex. `eurio-s3.musubi.dev`, sans schéma) |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | creds |
| `MINIO_USE_SSL` | `true`/`false` |
| `EURIO_DB_BUCKET` | nom du bucket lease (défaut `eurio-db`) |

Objets manipulés dans le bucket `eurio-db` :

| Clé | Contenu |
|---|---|
| `eurio.db` | la base canonique (binaire SQLite, ~67 Mo) |
| `eurio.db.sha256` | empreinte SHA-256 (texte) pour vérif d'intégrité au pull |
| `eurio.db.lock` | JSON `{holder_host, pid, acquired_at, note}` — présent ⇔ verrou tenu |

Le verrou est créé **atomiquement** par `PutObject` avec l'en-tête
**`If-None-Match: *`** (échoue si l'objet existe déjà). C'est le seul point qui
exige une version récente de MinIO → voir §3.

## À faire sur le VPS

### 1. Créer le bucket
```bash
mc mb local/eurio-db          # 'local' = alias mc vers le MinIO du VPS
```

### 2. Activer le versioning (rollback gratuit)
Un mauvais `push` (DB corrompue, mauvaise machine) doit être récupérable.
```bash
mc version enable local/eurio-db
mc version info  local/eurio-db   # doit afficher "Enabled"
```

### 3. Vérifier le support des écritures conditionnelles (`If-None-Match`)
C'est **critique** : sans ça le verrou n'est pas atomique (race Mac/PC possible).
Le support `PutObject` conditionnel est arrivé dans MinIO courant 2024-2025.
```bash
mc admin info local             # relever la version du serveur
```
Test fonctionnel (doit échouer la 2ᵉ fois avec PreconditionFailed/412) :
```bash
echo a | mc pipe --if-not-exists local/eurio-db/_cond_probe   # 1er : OK
echo b | mc pipe --if-not-exists local/eurio-db/_cond_probe   # 2e : doit ÉCHOUER
mc rm local/eurio-db/_cond_probe
```
- Si le 2ᵉ écrit **écrase** au lieu d'échouer → MinIO trop ancien : **mettre à
  jour le serveur** (`mc admin update local`, ou redéployer l'image docker à jour)
  avant de continuer. Ne pas mettre la doctrine en prod sans ce garde-fou.

### 4. Politique d'accès
La clé `MINIO_ACCESS_KEY` utilisée par Mac/PC doit avoir **lecture+écriture** sur
`eurio-db` (get/put/delete object, list bucket). Si tu utilises une policy
nommée, ajoute `eurio-db` à son scope ; sinon, vérifie que la clé existante
(déjà rw sur `enrichment-*`) couvre aussi ce nouveau bucket.
```bash
mc anonymous get local/eurio-db   # doit rester PRIVÉ (aucun accès anonyme)
```

### 5. Seed initial (une seule fois)
Deux options — **une seule** suffit :

- **Option A (recommandée, rien à faire ici)** : laisser **Mac** semer. Au tout
  premier `go-task ml:db:acquire`, le bucket est vide → le client pose le verrou
  sans pull et prévient « seed initial requis ». Mac travaille puis
  `go-task ml:db:release` → ça pousse `eurio.db` + `eurio.db.sha256`. À partir de
  là le distant fait foi. **Ne rien uploader manuellement** (éviter une DB
  obsolète qui écraserait la bonne).
- **Option B (seed depuis le VPS, si un `eurio.db` autoritaire y est déjà)** :
  ```bash
  sha256sum eurio.db | cut -d' ' -f1 > eurio.db.sha256
  mc cp eurio.db        local/eurio-db/eurio.db
  mc cp eurio.db.sha256 local/eurio-db/eurio.db.sha256
  ```
  ⚠️ N'utilise B que si tu es **certain** que ce `eurio.db` est le plus à jour.

### 6. (Optionnel) Borner la rétention des versions
Le versioning accumule les anciennes copies (~67 Mo chacune). Limiter à ~30 j :
```bash
mc ilm rule add local/eurio-db --noncurrent-expire-days 30
mc ilm rule ls  local/eurio-db
```

## Vérification finale (checklist à rendre)
- [ ] `mc ls local/eurio-db` répond (bucket existe)
- [ ] `mc version info local/eurio-db` = **Enabled**
- [ ] test `--if-not-exists` : 1er OK, 2e **échoue** (conditional writes OK)
- [ ] bucket **privé** (pas d'accès anonyme)
- [ ] la clé d'accès Mac/PC a rw sur `eurio-db`
- [ ] (si Option B) `eurio.db` + `eurio.db.sha256` présents et cohérents

## Ce qui n'est PAS à faire ici
- ❌ Installer/configurer `sqld`/libSQL (approche abandonnée).
- ❌ Monter `eurio.db` sur un FS réseau (NFS/SMB) — locking SQLite cassé = corruption.
- ❌ Ouvrir le bucket en public.

Une fois cette checklist verte, prévenir la session Mac : elle pourra
`go-task ml:db:acquire` / `release` et le cross-machine est opérationnel.
