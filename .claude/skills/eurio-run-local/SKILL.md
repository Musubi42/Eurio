---
name: eurio-run-local
description: Lancer la stack Eurio en local (API ML :8042, front :5173) et dérouler le lab — cohorte, bake, entraînement. À consulter avant de dire à quelqu'un comment tester, ou quand le front/l'API refuse de démarrer.
---

# Lancer Eurio en local

## Le minimum

```bash
direnv allow          # une fois — sans lui, front:dev refuse de démarrer
go-task ml:api-prod   # terminal 1 → :8042
go-task front:dev     # terminal 2 → :5173
```

Deux pièges d'entrée :

- **`ml:api-prod`, pas `ml:api`.** `ml:api` ajoute `--reload` : uvicorn redémarre
  à chaque sauvegarde de fichier et **tue le subprocess d'entraînement** en cours.
- **Le PAT ne vient pas d'un `.env.local`.** `front:dev` exige `VITE_EURIO_PAT`,
  aliasé par `.envrc` sur `EURIO_API_TOKEN` (source unique : `secrets/dev.env`).
  Ne recrée pas de `.env.local` pour ça — `admin/packages/studio-local/.env.example`
  le dit explicitement. D'où le `direnv allow` obligatoire.

Vérifier le PAT : `curl -H "Authorization: Bearer $EURIO_API_TOKEN" "$EURIO_API_URL/me"` → 200.

## ⛔ Arrêter l'API : jamais `pkill -f` avec un motif qu'on retape

`pkill -f "uvicorn serving.server"` matche **aussi la ligne de commande du shell
qui l'exécute** : le shell se tue lui-même. Vécu le 2026-08-16 — plus aucun shell
n'a redémarré de la session, exercice interrompu.

```bash
lsof -ti :8042 | xargs kill        # par PID, le motif n'apparaît nulle part
```

## Hors shell interactif (agent, CI, script)

direnv n'est pas chargé. Deux enveloppes cumulables :

```bash
sops exec-env secrets/dev.env '<commande>'     # secrets
nix develop .#mac --command <commande>          # toolchain (java, sqlite3_rsync, pnpm…)
```

⚠️ **`sqlite3_rsync` n'existe QUE dans le devShell.** Hors devShell,
`client.replica.rsync_available()` renvoie `False` et le pull bascule sur le
repli HTTP : snapshot complet de ~156 Mo, **~20 s** au lieu de **~1 s**. Une
mesure de perf faite hors devShell est fausse — vécu.

## Dérouler le lab

`/lab` → **Nouveau cohort** → itération → tiroir bake → tiroir entraînement.

- Créer une itération **gèle** la cohorte (les pièces sont verrouillées).
- `training_config` vide = **40 epochs**. Pour un test, mets `epochs: 5`.
- Préflight : chaque classe a besoin de **≥ 4 sources réelles** (`m_per_class`).
  Une cohorte de pièces pauvres est refusée à la création d'itération.
- L'entraînement tourne à la maille **design_group** : il tire des pièces
  **hors cohorte** (membres des mêmes groupes). C'est attendu.

Trouver des pièces entraînables :

```bash
sops exec-env secrets/dev.env 'curl -s -H "Authorization: Bearer $EURIO_API_TOKEN" \
  "$EURIO_API_URL/coins/enrichment-counts"' | python3 -c "
import json,sys; d=json.load(sys.stdin)
for k,v in sorted(d.items(), key=lambda kv:-kv[1])[:10]: print(f'{v:4d}  {k}')"
```

## ⛔ L'entraînement ne marche pas sous le flip

`create_run_row` écrit `training_runs` dans le canonique → `readonly database`.
C'est une décision d'archi ouverte (cf. skill `eurio-data-writes`). Mode
compute explicite en attendant :

### ☠️ Ne JAMAIS écraser une `work.db` existante

`VACUUM INTO` **refuse** d'écrire sur un fichier existant (« output file already
exists »). Le réflexe — `rm ml/state/eurio.work.db` puis re-VACUUM — est
**destructeur** : `work.db` est le SEUL endroit où vivent les `training_runs` /
`benchmark_runs` des itérations calculées sur cette machine. Rien ne les
sauvegarde, rien ne les régénère, elles ne remontent pas au canonique (c'est le
design R3 : seul l'état voyage, jamais le modèle). Un `rm` efface pour de bon le
résultat de chaque entraînement joué ici.

**Si `work.db` existe déjà : on la garde et on la réutilise telle quelle.** Elle
se répare, elle ne se refait pas.

```bash
# 1. Créer work.db — UNIQUEMENT si elle n'existe pas
[ -e ml/state/eurio.work.db ] || nix develop .#mac --command \
  sqlite3 ml/state/eurio.replica.db \
  "VACUUM INTO 'ml/state/eurio.work.db'"          # jamais `cp` : WAL

# 2. Besoin d'une base *fraîche* (réplique à jour) sans perdre les runs :
#    VACUUM INTO un fichier NEUF, et pointer EURIO_DB_PATH dessus.
nix develop .#mac --command sqlite3 ml/state/eurio.replica.db \
  "VACUUM INTO 'ml/state/eurio.work-2026-08-16.db'"

EURIO_DB_READONLY= EURIO_DB_PATH="$PWD/ml/state/eurio.work.db" go-task ml:api-prod
```

Le prix du fichier neuf : les runs de l'ancienne `work.db` n'y sont pas. C'est un
arbitrage conscient (fraîcheur du référentiel contre historique de compute), pas
un effet de bord — et l'ancienne reste sur le disque, donc réversible.

Les dimensions continuent de remonter au canonique par F09 (le statut
`completed` de l'itération y arrive). Les **résultats** (runs, métriques)
restent dans `work.db` : relancer l'API sans ces variables les rend invisibles.

⚠️ **La promotion doit tourner sous le MÊME `EURIO_DB_PATH`** — sinon elle lit
`state/eurio.db`, où l'itération n'existe pas :

```bash
cd ml && EURIO_DB_PATH="$PWD/state/eurio.work.db" \
  .venv/bin/python -m scripts.promote_iteration <iid> --dry-run
```

(Le script honore `EURIO_DB_PATH` depuis le 2026-08-16 ; avant, le chemin était
codé en dur et la promotion était **impossible** en mode compute.)

## Suivre ce qui se passe

Les jobs longs tournent en **subprocess détaché** — leur sortie n'est pas dans
le terminal de l'API :

```bash
ls -t ml/state/job_logs/ | head        # ⚠️ contient aussi des logs d'anciennes runs
```

Pour trouver le bon, passe par la table `jobs` (voir `eurio-data-writes`) — elle
donne `log_path`, `status` et `error`. Un job `failed` y est **enregistré** :
c'est le premier endroit à regarder quand « rien ne se passe ».

## Tâches supprimées qu'on croit encore vivantes

`ml:api-replica` / `ml:api-replica-prod` **n'existent plus** (chantier local-sync,
juillet 2026). Des docs les citent encore. La tâche est `ml:api-prod`.
