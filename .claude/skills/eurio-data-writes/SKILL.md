---
name: eurio-data-writes
description: Où vit la donnée d'Eurio et où part une écriture (Direction A, flip read-only, les 4 SQLite d'une machine de dev). À lire AVANT de toucher une route qui écrit, ou quand une écriture échoue en « readonly database » / 503 canonical_readonly.
---

# Où part une écriture dans Eurio

> La question qui coûte le plus cher dans ce repo n'est pas « quelle table ? »
> mais **« quel fichier ? »**. Une machine de dev porte quatre SQLite qui ont le
> même schéma. Se tromper de fichier ne lève pas d'erreur : ça écrit ailleurs,
> ou ça échoue en lecture seule au pire moment.

## Le flip Direction A — le piège numéro un

**Le devShell lui-même** pose ces deux variables (`flake.nix`, profils `mac` et `pc`) :

```
EURIO_DB_PATH=$PWD/ml/state/eurio.replica.db
EURIO_DB_READONLY=1
```

Conséquence : **tout Store ouvert sans `read_only=` explicite est en lecture
seule**, y compris dans l'API ML locale. C'est voulu — Direction A = writer
canonique unique (VPS), Mac/PC = clients replica + forward.

Le symptôme quand une route n'a pas été reroutée :

```
503 {"code":"canonical_readonly","detail":"… Route non encore reroutée — path=/lab/…"}
```

Ce 503 vient d'un handler global (`serving/server.py`) qui traduit
`sqlite3.OperationalError: attempt to write a readonly database`.

⚠️ **Mais son message ment par omission, et c'est tout le diagnostic.** Il dit
« Route non encore reroutée » dans **deux** cas très différents :

| Cas | Ce qui se passe | Ce qu'il faut faire |
|---|---|---|
| **Vrai résiduel** — aucun jumeau au VPS | la route n'existe nulle part ailleurs | rerouter (§ plus bas) |
| **Faux positif** — le jumeau existe déjà au VPS | le handler `:8042` est mort-mais-vivant ; c'est l'**appelant** qui tape la mauvaise adresse | corriger l'appelant, pas le backend |

Trancher prend une commande — **l'OpenAPI du canonique fait autorité** :

```bash
curl -s https://eurio-api.musubi.dev/openapi.json \
  | python3 -c "import json,sys; [print(k) for k in sorted(json.load(sys.stdin)['paths'])]" \
  | grep '<le chemin>'
```

Vérifié le 2026-08-17 : `move-lane`, `requalify-lot`, `correct-listing` et
`requalify-single` **ont tous leur jumeau au VPS**, et le front les y envoie déjà
(`useReviewApi.ts` → `eurioApi`). Le commentaire de `server.py` qui les liste
comme « résiduels » décrit `:8042`, pas le produit. Les vrais résiduels mesurés
ce jour-là : `POST /review-queue/requalify-lot/batch` et
`POST /coins/assets/reflag-needs-review`.

## Les quatre SQLite d'une machine de dev

| Fichier | Rôle | Écriture |
|---|---|---|
| `ml/state/eurio.replica.db` | **Réplique read-only** du canonique VPS, rafraîchie par `sqlite3_rsync` | ❌ jamais — `StoreBase` refuse même de l'ouvrir en écriture |
| `ml/state/eurio.db` | DB de travail « Model A » (pré-flip). Peut être **périmée** | ✅ si le flip est levé |
| `ml/state/eurio.local.db` | **Bookkeeping local** : `jobs`, `cohort_jobs`, `cohort_training_scans*` | ✅ **toujours**, même sous le flip |
| `ml/state/eurio.work*.db` | Snapshots inscriptibles ponctuels (mode compute) — pas un standard | ✅ |

⚠️ **La question porte sur le process, pas sur ton shell.** L'API peut avoir été
lancée avec d'autres variables que celles que `env` te montre. C'est pour ça que
le diagnostic ci-dessous lit `/proc`-équivalent du PID qui écoute, plutôt que
d'importer `serving.server` dans un process neuf — qui répondrait à une autre
question (*qu'utiliserait une nouvelle API*), en chargeant `cv2` et torch au
passage.

Ce que `ls ml/state/*.db` montre en plus, et qui n'est **pas** une destination :

| Fichier | Statut |
|---|---|
| `ml/shared/state/eurio.db` | legacy — ancienne DB de quota (`api_call_log`). Plus lu depuis le 2026-08-16, encore tracké dans git |
| `ml/state/review.db` | **legacy / autre système** — c'est la base du service de peer-review multi-utilisateur (`review_items`), pas la file `review_queue`. Ne rien y écrire |
| `ml/state/training.db` | legacy, froid depuis juin 2026. Ne rien y écrire |

Une machine de dev active en porte donc **huit ou neuf**, dont quatre seulement
sont des destinations. Le nombre de fichiers n'est pas un guide : la table du
haut l'est.

## Où part quoi

| Donnée | Destination | Par quoi |
|---|---|---|
| **Dimensions lab** (cohortes, itérations) | canonique VPS sous flip, local sinon | `serving/lab_writes.py` — **seul endroit qui décide** |
| **Jobs** (PID, log, avancement) | `eurio.local.db`, toujours | `jobs.connection()` (`jobs/conn.py`) |
| **Quota d'API** (eBay, Numista) | `eurio.local.db` | `shared/api_quota.default_db_path()` |
| **Crops / assets / funnel** | canonique | `POST /ingest/*` (`client/ingest.py`) |
| **Runs d'entraînement** (`training_runs`, epochs, steps) | ⛔ **non tranché** — écrit encore le canonique, donc échoue sous flip | cf. `docs/archive/local-sync/migration-direction-a.md` |

## Ajouter une route qui écrit

1. **Demande-toi si la donnée est locale par nature.** Un PID, un chemin de log,
   un compteur d'appels API : ça n'a de sens que sur cette machine → `eurio.local.db`
   via `store.local_state_store()`. Ne le mets **jamais** dans le canonique.
2. Sinon c'est du canonique : passe par `lab_writes` (dimensions) ou `/ingest/*`.
3. **Sous flip, un push raté n'est pas best-effort.** Si l'écriture n'atteint pas
   le VPS, elle n'existe nulle part → réponds 502, jamais 200.
4. **Méfie-toi des no-op documentés.** `client.ingest.push_cohort` renvoie `None`
   quand aucun canonique n'est configuré. Sous flip, ça rendrait 200 sans rien
   écrire nulle part. Garde explicite (`lab_writes._require_remote` → 503).

## Diagnostiquer en 30 secondes

```bash
# Quel fichier l'API QUI TOURNE utilise-t-elle ? (50 ms, rien à importer)
ps eww -o command= -p $(lsof -ti :8042) | tr ' ' '\n' | grep -E '^EURIO_(DB|API)'

# Un job détaché a-t-il échoué en silence ?
./.venv/bin/python -c "
import sys; sys.path.insert(0,'ml'); import jobs
for r in jobs.connection().execute(
    'select kind,status,n_done,n_total,error from jobs order by rowid desc limit 5'):
    print(dict(r))"
```

## Le piège WAL

**Ne copie jamais un SQLite vivant avec `cp`.** La réplique est en WAL : les
écritures récentes vivent dans le sidecar `-wal`, et une copie brute les perd
**en silence**. Vécu le 2026-08-16 — deux cohortes manquantes, dont celle qu'on
cherchait. Toujours :

```bash
nix develop .#mac --command sqlite3 ml/state/eurio.replica.db \
  "VACUUM INTO 'ml/state/eurio.work.db'"
```

## Références

- `docs/architecture/README.md` — les trois stockages, les flux
- `docs/archive/local-sync/migration-direction-a.md` — le plan C1→C7, ce qui reste
- `ml/serving/lab_writes.py`, `ml/jobs/conn.py` — les deux façades d'écriture
