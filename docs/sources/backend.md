---
title: Backend — endpoint /sources/status
date: 2026-04-26
status: draft
---

# Backend — endpoint `/sources/status`

## Contrat

`GET /sources/status` → `200 OK`, retourne un tableau de cartes source.

Pas de pagination (≤ 10 sources), pas de filtres (V1). Le frontend appelle
toutes les 10s en polling léger pendant que la page est ouverte (cohérent
avec `TrainingPage.vue` qui poll `/health` à 10_000ms).

## Schéma de réponse

```typescript
type SourceStatus = {
  id: 'numista_match' | 'numista_enrich' | 'numista_images' | 'ebay' | 'lmdlp' | 'mdp' | 'bce' | 'wikipedia'
  label: string                    // 'Numista — Match', 'eBay Browse', ...
  type: 'api' | 'scrape'
  quota_group?: string             // ex 'numista' — partagé entre 3 cartes Numista (UI peut grouper)
  health: 'healthy' | 'warning' | 'error'
  health_reason: string | null     // explication textuelle si pas healthy

  // Quota — null pour les scrapes HTML
  quota: {
    window: 'monthly' | 'daily'
    period: string                 // '2026-04' ou '2026-04-26'
    limit: number
    calls: number
    remaining: number
    pct_used: number               // 0..100
    exhausted: boolean
    per_key?: Array<{              // Numista uniquement
      slot: number
      key_hash: string
      calls: number
      exhausted: boolean
    }>
  } | null

  // Temporel — voir temporal.md
  temporal: {
    last_run_at: string | null     // ISO timestamp
    last_run_kind: string | null   // 'match', 'enrich', 'images', 'scrape', ...
    days_since_last_run: number | null
    expected_cadence_days: number  // cadence cible
    overdue: boolean               // last_run > 1.5 × expected_cadence
    delta: {
      n_stable: number | null      // pour eBay (delta prix), null sinon
      n_new: number                // nouvelles pièces / cotes vs run précédent
      n_dropped: number
      delta_p50_median_pct: number | null   // eBay only
      delta_p50_p10_pct: number | null
      delta_p50_p90_pct: number | null
      swing_warning: boolean
    } | null
  }

  // Couverture
  coverage: {
    enriched: number               // # pièces enrichies par cette source
    total_target: number           // # pièces ciblables (commémos pour eBay, all coins pour Numista)
    pct: number                    // 0..100
  }

  // V2 — boutons "Fetch maintenant"
  // V1 : on retourne la liste de toutes les commandes CLI pertinentes
  cli_hints: Array<{
    command: string                // 'go-task ml:scrape-ebay'
    description: string            // 'Run complet : enrichit toutes les commémos avec numista_id'
    expected_outcome: string       // 'Insère N lignes dans coin_market_prices, écrit ml/state/price_snapshots/ebay_<period>.json'
    kind: 'run' | 'dry-run' | 'list' | 'status' | 'reset' // pour grouper / styliser dans l'UI
  }>
}
```

## Implémentation côté FastAPI

Nouveau module `ml/api/sources_routes.py` :

```python
from fastapi import APIRouter
from .sources_aggregator import build_status

router = APIRouter(prefix="/sources", tags=["sources"])

@router.get("/status")
def sources_status() -> list[dict]:
    return build_status()
```

Branchement dans `ml/api/server.py` :

```python
from . import sources_routes
app.include_router(sources_routes.router)
```

### Module d'agrégation

`ml/api/sources_aggregator.py` orchestre la lecture :

```python
SOURCES_REGISTRY = [
    # 3 cartes Numista — même quota_group, cadences différentes
    {
        'id': 'numista_match', 'label': 'Numista — Match',
        'quota_group': 'numista', 'expected_cadence_days': 14,
        'last_run_kind': 'match', 'cli_hints': [...],
    },
    {
        'id': 'numista_enrich', 'label': 'Numista — Enrichissement',
        'quota_group': 'numista', 'expected_cadence_days': 30,
        'last_run_kind': 'enrich', 'cli_hints': [...],
    },
    {
        'id': 'numista_images', 'label': 'Numista — Images',
        'quota_group': 'numista', 'expected_cadence_days': 30,
        'last_run_kind': 'images', 'cli_hints': [...],
    },
    {
        'id': 'ebay', 'label': 'eBay Browse', 'type': 'api',
        'quota_source': 'ebay', 'quota_window': 'daily', 'quota_limit': 5000,
        'expected_cadence_days': 30,
        'snapshot_glob': 'ebay_*.json',
        'price_snapshot_glob': 'ebay_*.json',  # ml/state/price_snapshots/
        'cli_hints': [...],
    },
    # lmdlp, mdp, bce, wikipedia ...
]

def build_status() -> list[dict]:
    return [_build_one(s) for s in SOURCES_REGISTRY]

def _build_one(spec: dict) -> dict:
    return {
        'id': spec['id'],
        'label': spec['label'],
        'type': spec['type'],
        'quota': _read_quota(spec),
        'temporal': _read_temporal(spec),
        'coverage': _read_coverage(spec),
        'health': _derive_health(...),
        'health_reason': _derive_health_reason(...),
        'cli_hint': spec['cli_hint'],
    }
```

### Sources de données

| Champ | Origine |
|---|---|
| `quota` | `QuotaTracker(spec['quota_source'], spec['quota_window']).status()` |
| `temporal.last_run_at` | `ml/state/sources_runs.json` (Numista) ou `MAX(mtime)` du `snapshot_glob` |
| `temporal.delta` (eBay) | Lecture filesystem `ml/state/price_snapshots/ebay_*.json` — diff entre les 2 derniers fichiers (mois N vs N-1). **Aucun call Supabase**. Voir `temporal.md` |
| `temporal.delta.n_new` (autres) | Compare 2 derniers snapshots du `snapshot_glob` |
| `coverage.enriched` | Count distinct `eurio_id` dans `coin_market_prices WHERE source=X` (eBay) ou `coins WHERE 'X' IN provenance.sources_used` (autres) |
| `coverage.total_target` | Count des coins ciblables (commémos pour eBay, all pour Numista) |

### Health derivation

```python
def _derive_health(quota, temporal) -> tuple[str, str | None]:
    if quota and quota['exhausted']:
        return 'error', 'Quota épuisé'
    if quota and quota['pct_used'] > 90:
        return 'warning', f"Quota presque épuisé ({quota['calls']}/{quota['limit']})"
    if temporal['overdue']:
        return 'warning', f"Pas de fetch depuis {temporal['days_since_last_run']} jours"
    if temporal.get('delta', {}).get('swing_warning'):
        return 'warning', 'Swing de prix anormal détecté'
    return 'healthy', None
```

## Performance

- Lecture quota : 1 query SQLite, < 5ms
- Lecture filesystem `snapshot_glob` : cached via `lru_cache(maxsize=10, ttl=...)` côté Python — sinon mtime stat() à chaque appel
- Lecture coverage : 1 query Supabase par source, ~50-100ms
- Calcul delta eBay : lecture 2 fichiers JSON locaux + diff in-memory, ~10ms

Total endpoint : ~150ms à froid, ~50ms après cache. Acceptable pour un poll
toutes les 10s.

**Important : aucun call Supabase n'est fait à chaque poll** — Raphaël
tourne sur Supabase free tier (1GB egress/mois), donc poll 10s × 8 cartes ×
500 coins serait suicidaire. Tout passe par `ml/state/`.

## Sécurité / auth

L'admin est déjà auth-gated (Supabase auth) côté Vue. L'endpoint FastAPI
tourne en local (`localhost:8042`), CORS limité à `localhost:5173/4173`
comme tous les autres endpoints ml/. Pas de durcissement supplémentaire.

## Travail à faire

1. `ml/api/sources_aggregator.py` — registry + builder
2. `ml/api/sources_routes.py` — router FastAPI
3. Branchement dans `ml/api/server.py`
4. Helpers : `_read_quota`, `_read_temporal`, `_read_coverage`, `_derive_health`
5. Tests : `tests/test_sources_aggregator.py` (mocks pour Supabase + filesystem)
