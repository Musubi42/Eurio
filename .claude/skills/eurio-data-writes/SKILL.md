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
`sqlite3.OperationalError: attempt to write a readonly database`. **Le message
dit la vérité** : la route écrit encore en local alors qu'elle ne devrait plus.

## Les quatre SQLite d'une machine de dev

| Fichier | Rôle | Écriture |
|---|---|---|
| `ml/state/eurio.replica.db` | **Réplique read-only** du canonique VPS, rafraîchie par `sqlite3_rsync` | ❌ jamais — `StoreBase` refuse même de l'ouvrir en écriture |
| `ml/state/eurio.db` | DB de travail « Model A » (pré-flip). Peut être **périmée** | ✅ si le flip est levé |
| `ml/state/eurio.local.db` | **Bookkeeping local** : `jobs`, `cohort_jobs`, `cohort_training_scans*` | ✅ **toujours**, même sous le flip |
| `ml/state/eurio.work.db` | Snapshot inscriptible ponctuel (mode compute) — pas un standard | ✅ |

`ml/shared/state/eurio.db` est un **cinquième**, legacy : c'était la DB de quota
d'API (`api_call_log`). Plus lu depuis le 2026-08-16, encore tracké dans git.

## Où part quoi

| Donnée | Destination | Par quoi |
|---|---|---|
| **Dimensions lab** (cohortes, itérations) | canonique VPS sous flip, local sinon | `serving/lab_writes.py` — **seul endroit qui décide** |
| **Jobs** (PID, log, avancement) | `eurio.local.db`, toujours | `jobs.connection()` (`jobs/conn.py`) |
| **Quota d'API** (eBay, Numista) | `eurio.local.db` | `shared/api_quota.default_db_path()` |
| **Crops / assets / funnel** | canonique | `POST /ingest/*` (`client/ingest.py`) |
| **Runs d'entraînement** (`training_runs`, epochs, steps) | ⛔ **non tranché** — écrit encore le canonique, donc échoue sous flip | cf. `docs/work-in-progress/local-sync/migration-direction-a.md` |

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
# Quel fichier l'API utilise-t-elle vraiment ?
cd ml && ./.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from serving import server
print(server.CANONICAL_DB, '| read_only =', server._store._read_only)"

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
- `docs/work-in-progress/local-sync/migration-direction-a.md` — le plan C1→C7, ce qui reste
- `ml/serving/lab_writes.py`, `ml/jobs/conn.py` — les deux façades d'écriture
