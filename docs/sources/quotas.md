---
title: Gestion des quotas — sources
date: 2026-04-26
status: draft
---

# Gestion des quotas

## État actuel

| Source | Quota | Tracking |
|---|---|---|
| Numista | ~2000 calls/mois (soft 1800) | ✅ SQLite `numista_key_usage` (rotation multi-clés) |
| eBay | 5000 calls/jour | ❌ Compteur in-memory `EbayClient.call_count`, perdu à chaque run |
| LMDLP / MdP / BCE / Wikipedia | Pas de quota explicite | N/A (scrape HTML, on s'auto-limite à coups de `time.sleep`) |

Le tracking Numista est solide. C'est le seul. Pour `/sources` on doit étendre
ça à eBay (et potentiellement futures APIs).

## Refacto proposé : table `api_call_log` générique

### Schéma

```sql
-- ml/state/training.db
CREATE TABLE api_call_log (
    source       TEXT NOT NULL,           -- 'numista', 'ebay', ...
    key_hash     TEXT NOT NULL DEFAULT '',-- vide pour eBay (1 seule clé), hash sha256[:12] pour Numista
    window       TEXT NOT NULL,           -- 'monthly' | 'daily'
    period       TEXT NOT NULL,           -- '2026-04' (monthly) ou '2026-04-26' (daily)
    calls        INTEGER NOT NULL DEFAULT 0,
    exhausted    INTEGER NOT NULL DEFAULT 0,
    last_call_at TEXT,                    -- ISO timestamp (debug / "dernière activité")
    PRIMARY KEY (source, key_hash, window, period)
);
```

Ce schéma absorbe `numista_key_usage` (qui devient `WHERE source='numista'
AND window='monthly'`).

### Migration

```sql
-- One-shot migration script ml/state/migrate_api_call_log.py
INSERT INTO api_call_log (source, key_hash, window, period, calls, exhausted)
SELECT 'numista', key_hash, 'monthly', month, calls, exhausted
FROM numista_key_usage;

DROP TABLE numista_key_usage;
```

Pas de fallback / dual-write : c'est une refacto interne, on bascule en un
commit.

### API Python

```python
# ml/api_quota.py (nouveau)
from dataclasses import dataclass

@dataclass
class QuotaStatus:
    source: str
    window: str
    period: str
    limit: int
    calls: int
    remaining: int
    exhausted: bool
    last_call_at: str | None

class QuotaTracker:
    def __init__(self, source: str, window: str, limit: int, db_path: Path = DEFAULT_DB):
        self.source = source
        self.window = window      # 'monthly' | 'daily'
        self.limit = limit
        self.db_path = db_path

    def record(self, key_hash: str = "") -> None: ...
    def mark_exhausted(self, key_hash: str = "") -> None: ...
    def status(self) -> list[QuotaStatus]: ...      # une ligne par key_hash
    def total(self) -> QuotaStatus: ...             # somme cross-clés
```

`KeyManager` (Numista) devient un cas particulier construit sur
`QuotaTracker(source='numista', window='monthly', limit=1800)`. La logique
multi-clés (rotation, pick) reste dans `numista_keys.py` mais délègue le
comptage à `QuotaTracker`.

### Instrumentation eBay

`market/ebay_client.py` est appelé via `EbayClient(token)`. On ajoute :

```python
class EbayClient:
    def __init__(self, token: str, tracker: QuotaTracker | None = None):
        self._tracker = tracker or QuotaTracker('ebay', 'daily', limit=5000)
        ...

    def search(self, ...):
        resp = self._http.get(...)
        if resp.status_code == 429:
            self._tracker.mark_exhausted()
            raise RateLimitExceeded(...)
        self._tracker.record()
        return resp.json()
```

Idem pour `get_items_by_group`, `get_item`. Chaque appel HTTP = un
`tracker.record()`.

### Période daily/monthly

Pour eBay (daily), `period` = `YYYY-MM-DD`. Le compteur se reset
automatiquement à minuit UTC (au sens : on commence à incrémenter une nouvelle
ligne `(ebay, '', 'daily', '2026-04-27')`). Pas de purge active des vieilles
lignes — on garde l'historique pour pouvoir afficher des graphes "calls/jour
sur 30 jours" plus tard.

Pour Numista (monthly), `period` = `YYYY-MM`. Soft limit 1800, reset au
1er du mois.

## Affichage UI dans `/sources`

Voir `frontend.md` pour le rendu, mais le contrat de données :

```json
{
  "quota": {
    "window": "monthly",
    "period": "2026-04",
    "limit": 1800,
    "calls": 1247,
    "remaining": 553,
    "pct_used": 69.3,
    "exhausted": false,
    "per_key": [
      { "slot": 1, "key_hash": "a3b9c1...", "calls": 1247, "exhausted": false },
      { "slot": 2, "key_hash": "d8e2f4...", "calls": 0,    "exhausted": false }
    ]
  }
}
```

Pour les sources sans quota (LMDLP, MdP, BCE, Wikipedia), `quota` = `null` et
la carte affiche juste un badge `Scrape HTML — pas de quota`.

## Risques / edge cases

- **Concurrence multi-process** : si on lance deux `scrape_ebay` en parallèle
  (peu probable mais possible), le `record()` doit être atomique. SQLite avec
  WAL + l'`ON CONFLICT ... DO UPDATE SET calls = calls + 1` actuel suffit.
- **Quota dépassé en cours de run** : `mark_exhausted()` ne stoppe pas le run
  en cours, il signale juste l'état pour l'admin. Le `EbayClient` lève une
  exception sur 429, le script de scrape catch et termine proprement (comme
  Numista aujourd'hui).
- **Reset manuel** : prévoir une commande CLI `go-task ml:quota:reset
  --source=ebay --period=2026-04-26` pour les cas où on veut re-tester après
  un run cassé. Pas exposé dans l'UI.

## Travail à faire

1. Créer `ml/state/migrations/001_api_call_log.sql`
2. Écrire `ml/api_quota.py` (`QuotaTracker`)
3. Refacto `ml/referential/numista_keys.py` pour utiliser `QuotaTracker`
4. Instrumenter `ml/market/ebay_client.py` avec `QuotaTracker`
5. Tests : `tests/test_api_quota.py` couvrant monthly/daily/multi-key
6. CLI utilitaire `go-task ml:quota:status` (dump JSON pour debug)

Pas de code dans cette doc — uniquement la structure et les contrats.
