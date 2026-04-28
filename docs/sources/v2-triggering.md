---
title: V2 — déclenchement fetch depuis l'UI
date: 2026-04-26
status: deferred (mémo)
---

# V2 — déclenchement fetch depuis l'UI

## Pourquoi pas en V1

V1 = lecture seule. La page `/sources` montre l'état, fournit la commande à
copier, point. Implémenter le déclenchement maintenant = sur-coût important
pour un gain incertain.

**Coût estimé V1 (lecture seule)** : ~2 jours (endpoint + composants + nav)  
**Coût estimé V2 (avec déclenchement)** : ~1 semaine supplémentaire  

Vu qu'aujourd'hui Raphaël lance les scripts au terminal sans friction, on n'a
pas besoin d'urgence — on attend d'avoir la V1 en main pour évaluer si c'est
vraiment manquant.

## Pourquoi c'est non-trivial

### 1. Job runner

Les fetchs sont **longs** :

| Source | Durée typique | Ordre de grandeur |
|---|---|---|
| Numista (match, 50 nouvelles pièces) | 2–5 min | court |
| Numista (enrich, 1000 pièces) | 30–60 min | long |
| eBay (full run, 500 commémos) | 10–20 min | moyen |
| LMDLP / MdP scrape complet | 5–10 min | court |
| BCE scrape années | 1–2 min | rapide |

Ces durées dépassent largement le timeout d'une requête HTTP. Il faut un
**job runner** style `TrainingRunner` actuel :

- Endpoint `POST /sources/{id}/fetch` lance un job en background
- État du job persisté en SQLite (table `source_runs` séparée ou dans
  `api_call_log` étendu)
- Endpoint `GET /sources/{id}/active-run` pour suivre la progression
- Streaming des logs (cf. `_runner.load_logs` actuel)
- Recovery on boot (cf. `_lab_startup` qui re-queue les iterations stuck)

C'est exactement ce que fait déjà `TrainingRunner` pour le ML. On peut
**copier le pattern** mais c'est ~600 LoC à écrire et tester.

### 2. Locking & concurrence

Deux runs eBay en parallèle = pollution des résultats (deux INSERT dans
`coin_market_prices` à la même seconde, dont un partiel). Il faut un lock
**par source** :

```python
class SourceJobLock:
    """One active fetch per source at a time."""
    def acquire(source_id: str) -> bool: ...
    def release(source_id: str) -> None: ...
```

Stocké en SQLite (`source_active_runs` table avec PK source_id).

### 3. UX d'un long-running job

L'UI doit gérer :

- État **idle** → bouton "Fetch maintenant"
- État **running** → barre de progression + logs streamés + bouton "Annuler"
- État **completed** → résumé du delta + lien vers le run
- État **failed** → message d'erreur + bouton "Voir logs"

Cf. `TrainingPage.vue:534-XXX` (section "Active run") pour le pattern à
réutiliser. Beaucoup de code Vue.

### 4. Annulation propre

Ctrl-C sur un script Python termine proprement (gestion des signaux). Annuler
depuis l'UI = envoyer SIGTERM au subprocess sans laisser de demi-état (par ex.
une ligne `coin_market_prices` insérée mais pas l'incrément quota). Demande
des transactions + checkpoint propre.

### 5. Sécurité

V1 : l'admin tourne en local, pas de risque. V2 : si un jour l'admin est
déployé sur Vercel et que l'API ML reste sur la machine de Raphaël, l'endpoint
de déclenchement est sensible (un attaquant peut faire griller le quota
Numista). Auth + rate limiting + IP allowlist nécessaires.

## Architecture proposée pour V2

```
┌─────────────────────────────────────────────────────┐
│ POST /sources/{id}/fetch                            │
│   → SourceJobLock.acquire(id)                       │
│   → INSERT INTO source_runs (status='queued', ...)  │
│   → spawn thread: subprocess.Popen([go-task, ...])  │
│   → return {run_id, status: 'queued'}               │
├─────────────────────────────────────────────────────┤
│ Background thread:                                  │
│   - read stdout/stderr line by line                 │
│   - persist to source_runs.logs                     │
│   - update progress markers                         │
│   - on exit: status='completed'/'failed'            │
│   - SourceJobLock.release(id)                       │
├─────────────────────────────────────────────────────┤
│ GET /sources/{id}/active-run                        │
│   → SELECT * FROM source_runs                       │
│       WHERE source_id=? AND status IN ('queued',    │
│             'running')                              │
├─────────────────────────────────────────────────────┤
│ GET /sources/{id}/runs                              │
│   → liste paginée                                   │
├─────────────────────────────────────────────────────┤
│ POST /sources/{id}/runs/{run_id}/cancel             │
│   → SIGTERM au PID                                  │
└─────────────────────────────────────────────────────┘
```

Schéma SQLite :

```sql
CREATE TABLE source_runs (
    id            TEXT PRIMARY KEY,         -- uuid
    source_id     TEXT NOT NULL,
    kind          TEXT NOT NULL,            -- 'match', 'enrich', 'scrape', ...
    status        TEXT NOT NULL,            -- 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
    started_at    TEXT,
    finished_at   TEXT,
    pid           INTEGER,
    cmd           TEXT NOT NULL,            -- 'uv run python -m market.scrape_ebay --limit 50'
    exit_code     INTEGER,
    logs_path     TEXT,                     -- ml/state/source_runs/{run_id}.log
    delta_summary TEXT                      -- JSON
);

CREATE TABLE source_active_runs (
    source_id  TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL,
    acquired_at TEXT NOT NULL
);
```

## Réutilisations possibles

- `ml/api/training_runner.py` : pattern `start_run` / `active_run` /
  `recover_on_boot` à dupliquer/généraliser
- `usePoller` côté Vue
- `TrainingPage.vue` section "Active run" comme template UX

Idéalement, on **généralise `TrainingRunner` en `JobRunner`** capable de
gérer training ET source fetch. Demande un refacto soigné, pas un copier-coller.

## Points à trancher au moment de la V2

1. **Granularité du job** : un endpoint par kind (`POST /sources/numista/match`
   vs `/enrich` vs `/images`) ou un seul endpoint avec param `kind` ?
   Probablement le second.
2. **Annulation = grace ou hard kill** : SIGTERM avec délai 30s puis SIGKILL ?
3. **Concurrence cross-source** : faut-il limiter à 1 run **global** à la fois
   pour éviter de saturer la machine, ou 1 par source ? Probablement par source.
4. **Logs : stream WebSocket ou polling** ? Polling à 2s suffit comme pour le
   training, plus simple, pas de WebSocket à gérer.
5. **Résultat du run** : on affiche le delta calculé directement dans la page
   `/sources` (carte qui se met à jour) ou dans un detail panel ? Probablement
   les deux : carte refresh + lien "voir détails".

## Ce qu'on note pour ne pas l'oublier

- Notes ci-dessus → fichier vivant à mettre à jour quand on a plus
  d'infos sur l'usage V1
- À chaque fois qu'on lance un script `go-task ml:...` à la main et qu'on se
  dit "ce serait bien d'avoir un bouton" → ajouter un commentaire ici
- Quand 5+ entrées s'accumulent → c'est le signal qu'on doit faire la V2
