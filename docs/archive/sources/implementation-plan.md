---
title: Plan d'implémentation — page admin /sources
date: 2026-04-26
status: actionable
audience: nouvelle session Claude Code (autonome)
---

# Plan d'implémentation — page admin `/sources`

## TL;DR pour la session qui prend la suite

Une page admin `/sources` en lecture seule a été **conçue, documentée et
livrée côté frontend avec données mockées**. Cette session est mandatée pour
**livrer le backend + brancher les vraies données + ajouter les helpers CLI
manquants**.

Lis dans cet ordre :

1. Ce fichier (plan d'action consolidé)
2. `docs/sources/README.md` — index des 6 docs de spec
3. `docs/sources/vision.md`, `frontend.md`, `backend.md`, `quotas.md`,
   `temporal.md` quand une phase y fait référence

Ne lis **pas** `v2-triggering.md` — c'est un mémo futur, hors scope.

## État actuel (avril 2026)

### Frontend (livré, mocké)

```
admin/packages/web/src/features/sources/
├── pages/SourcesPage.vue           # Orchestratrice, 3 sections, polling 10s
├── components/
│   ├── SourceCard.vue              # Carte source unifiée (gère is_future)
│   ├── QuotaProgressBar.vue        # Barre + breakdown par clé (Numista)
│   ├── DeltaIndicator.vue          # ↗/↘ price OR count, swing warning
│   └── CliHintsBlock.vue           # Multi-commandes, copier→check 2s
└── composables/useSourcesApi.ts    # Types + MOCK_SOURCES_STATUS + fetch stub
```

Nav (`src/app/nav.ts`) et route (`src/app/router.ts`) câblés.
**`pnpm typecheck` passe** sur tous les nouveaux fichiers.

Le mock affiche 8 cartes (3 Numista + eBay + LMDLP + MdP + BCE + Wikipedia)
qui couvrent les 4 états : `healthy`, `warning`, `error`, `future` (Wikipedia).

### Backend (à livrer)

- ❌ Endpoint `GET /sources/status` — pas implémenté
- ❌ Refacto `numista_key_usage` → `api_call_log` générique — pas faite
- ❌ Marker `ml/state/sources_runs.json` — pas créé
- ❌ Snapshot prix mensuel `ml/state/price_snapshots/ebay_<period>.json` — pas écrit
- ❌ Plusieurs flags CLI manquants (cf. Phase B)
- ❌ Scraper Wikipedia — pas écrit (Wikipedia reste en mode `is_future`)

## Phasage (ordre obligatoire — chaque phase débloque la suivante)

```
A. Helpers CLI manquants  (low-risk, 1-2h)
   ↓
B. Refacto api_call_log + instrumentation eBay  (4-6h)
   ↓
C. Marker sources_runs.json + price snapshots eBay  (2-3h)
   ↓
D. Endpoint GET /sources/status  (3-4h)
   ↓
E. Branchement frontend (mock → real fetch)  (15min)
   ↓
F. Test bout-en-bout  (30min)
```

Phases A et B peuvent se faire en parallèle si tu veux. C dépend de B
(snapshot écrit après le run eBay = au même endroit où l'instrumentation
quota se fait).

---

## Phase A — Helpers CLI manquants

**Objectif** : ajouter les flags argparse manquants pour que les commandes
exposées dans `useSourcesApi.ts` fonctionnent toutes vraiment.

**Pourquoi maintenant** : l'UI affiche déjà ces commandes avec
`description` + `expected_outcome`. Si l'utilisateur les copie et lance, ça
doit marcher. C'est aussi un travail trivial qui peut servir de
warm-up avant les phases techniques plus lourdes.

### A.1 — `--limit N` sur 3 scripts

| Script | Comportement attendu |
|---|---|
| `ml/referential/batch_match_numista.py` | Ne traite que les N premiers candidats |
| `ml/referential/enrich_from_numista.py` | Idem |
| `ml/referential/scrape_monnaiedeparis.py` | Ne scrape que N fiches |

**Pattern** : ajouter `parser.add_argument('--limit', type=int, default=None)`,
slicer la liste en début de boucle si non-None. Ne pas court-circuiter le
flush final (qui doit toujours écrire le snapshot/marker).

### A.2 — `--countries=ISO2,ISO2` sur `enrich_from_numista.py`

Aligner sur le même flag déjà présent dans `scrape_ebay.py:464` :
```python
ap.add_argument('--countries', default=None,
                help='Comma-separated ISO2 country filter')
```
Filtrer la liste de coins par `country in {DE, FR, ...}` après le chargement.

### A.3 — `--dry-run` sur `scrape_ebay.py`

Quand activé :
- Faire les requêtes eBay normalement (consomme du quota — ok pour tester)
- **Ne pas insérer dans Supabase** (skip `_insert_market_price`)
- **Ne pas écrire le snapshot mensuel** (skip l'écriture `ml/state/price_snapshots/`)
- Afficher le récap stdout comme avant

### A.4 — `--list-missing` sur 2 scripts

| Script | Sortie attendue |
|---|---|
| `ml/referential/batch_fetch_images.py` | Liste des `eurio_id` sans `images.obverse` |
| `ml/referential/scrape_lmdlp.py` | Liste des `eurio_id` absents du dernier snapshot LMDLP |

Mode lecture seule, sortie ligne-par-ligne sur stdout, pas d'appel API.

### A.5 — `--year=N` sur `scrape_bce_images.py`

Aujourd'hui le script hardcode 2004→année courante. Ajouter `--year` qui,
si fourni, scrape uniquement cette année. Compatible avec le run complet
(comportement par défaut inchangé).

### A.6 — Wikipedia : NE PAS écrire de scraper

Volontairement laissé en mode `is_future`. Si tu en as envie c'est OK mais ce
n'est pas dans le scope de cette session. Ce qui compte c'est que la carte
reste cohérente avec son état "à venir".

### Validation Phase A

Pour chaque flag ajouté, lancer une fois la commande correspondante du mock
(`useSourcesApi.ts` → `MOCK_SOURCES_STATUS`) en local et vérifier qu'elle
n'échoue pas. Pas besoin de tests automatisés — c'est de l'argparse trivial.

---

## Phase B — Refacto `api_call_log` + instrumentation eBay

**Spec complète** : `docs/sources/quotas.md` (à lire en entier avant d'attaquer).

**Objectif** : remplacer la table SQLite `numista_key_usage` par une table
générique `api_call_log` qui supporte (source, key_hash, window, period) en
clé composite. Instrumenter `EbayClient` pour qu'il décompte aussi son quota
journalier dans la même table.

### B.1 — Migration SQLite

Créer `ml/state/migrations/001_api_call_log.sql` :

```sql
CREATE TABLE api_call_log (
    source       TEXT NOT NULL,
    key_hash     TEXT NOT NULL DEFAULT '',
    window       TEXT NOT NULL,            -- 'monthly' | 'daily'
    period       TEXT NOT NULL,            -- '2026-04' ou '2026-04-26'
    calls        INTEGER NOT NULL DEFAULT 0,
    exhausted    INTEGER NOT NULL DEFAULT 0,
    last_call_at TEXT,
    PRIMARY KEY (source, key_hash, window, period)
);

INSERT INTO api_call_log (source, key_hash, window, period, calls, exhausted)
SELECT 'numista', key_hash, 'monthly', month, calls, exhausted
FROM numista_key_usage;

DROP TABLE numista_key_usage;
```

Appliquée par un mini-runner Python qui check si la migration a été passée
(nouvelle table `schema_migrations` ou simple `PRAGMA user_version`).

### B.2 — `ml/api_quota.py` (nouveau)

```python
class QuotaTracker:
    def __init__(self, source: str, window: Literal['monthly', 'daily'],
                 limit: int, db_path: Path = DEFAULT_DB): ...
    def record(self, key_hash: str = "") -> None: ...
    def mark_exhausted(self, key_hash: str = "") -> None: ...
    def status(self) -> list[QuotaStatus]: ...
    def total(self) -> QuotaStatus: ...
```

Implémentation thread-safe (lock + WAL), `period` calculé dynamiquement
(`datetime.now().strftime('%Y-%m')` ou `'%Y-%m-%d'`).

### B.3 — Refacto `KeyManager` (Numista)

`ml/referential/numista_keys.py` : la classe garde sa logique de rotation
multi-clés mais délègue le comptage à `QuotaTracker(source='numista',
window='monthly', limit=1800)`. Le code existant `record_call`,
`mark_exhausted`, `status` reste fonctionnel mais s'appuie sur le tracker.

### B.4 — Instrumenter `EbayClient`

`ml/market/ebay_client.py` : injecter un `QuotaTracker` optionnel dans le
constructeur. Wrapper chaque appel HTTP (`search`, `get_items_by_group`,
`get_item`) avec `tracker.record()` avant le `return`, et
`tracker.mark_exhausted()` sur 429.

### B.5 — Commande CLI `ml:quota:status`

Nouveau script `ml/api_quota_cli.py` (ou intégré au Taskfile direct) qui
dump JSON :

```bash
go-task ml:quota:status -- --source=numista
# {"source":"numista","window":"monthly","period":"2026-04","limit":1800,"calls":1247,"remaining":553,"exhausted":false,"per_key":[...]}

go-task ml:quota:status -- --source=ebay
# {"source":"ebay","window":"daily","period":"2026-04-26","limit":5000,"calls":127,...}
```

Ajouter l'entrée Taskfile correspondante.

### B.6 — Mise à jour mock `useSourcesApi.ts`

Une fois `ml:quota:status` opérationnel, remettre les 2 entrées CLI qui ont
été retirées par l'audit précédent (cf. plus bas, section "Mock à
re-synchroniser après Phase B").

### Validation Phase B

```bash
# 1. Migration applique sans erreur
go-task ml:migrate

# 2. Quotas Numista hérités
sqlite3 ml/state/training.db 'SELECT * FROM api_call_log WHERE source="numista"'
# → doit afficher l'historique préservé

# 3. eBay instrumenté
go-task ml:scrape-ebay -- --limit 3
sqlite3 ml/state/training.db 'SELECT * FROM api_call_log WHERE source="ebay"'
# → doit afficher 3-9 calls (1 search + group expansions)

# 4. CLI quota status fonctionne
go-task ml:quota:status -- --source=ebay
# → JSON valide
```

---

## Phase C — Marker temporel + snapshots prix

**Spec complète** : `docs/sources/temporal.md`.

### C.1 — `ml/state/sources_runs.json`

À chaque run de `batch_match_numista.py`, `enrich_from_numista.py`,
`batch_fetch_images.py`, `scrape_ebay.py`, `scrape_lmdlp.py`,
`scrape_monnaiedeparis.py`, `scrape_bce_images.py` : écrire/mettre à jour
une entrée :

```json
{
  "numista_match": {
    "last_run_at": "2026-04-26T14:32:11Z",
    "last_run_kind": "batch_match",
    "last_run_calls": 87,
    "last_run_added_coins": 3
  },
  "numista_enrich": { ... },
  "numista_images": { ... },
  "ebay": { ... },
  "lmdlp": { ... },
  "mdp": { ... },
  "bce": { ... }
}
```

Pas de marker pour Wikipedia (mode `is_future`).

**Note d'archi** : créer un helper partagé `ml/state/sources_runs.py` avec
deux fonctions :

```python
def record_run(source_id: str, kind: str, *,
               calls: int = 0, added_coins: int = 0) -> None: ...
def read_all() -> dict[str, dict]: ...
```

Chaque script appelle `record_run('numista_match', 'batch_match',
calls=client.call_count, added_coins=len(added_nids))` à la fin.

### C.2 — Snapshot prix mensuel eBay

Dans `scrape_ebay.py`, après le `save_referential` final, écrire :

```python
def write_price_snapshot(records: list[dict], period: str) -> Path:
    path = ML_DIR / 'state' / 'price_snapshots' / f'ebay_{period}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'source': 'ebay',
        'period': period,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'coins': {
            r['eurio_id']: {
                'p25': r['stats']['p25'],
                'p50': r['stats']['p50'],
                'p75': r['stats']['p75'],
                'samples': r['stats']['samples_count'],
            }
            for r in records
            if r['stats']['samples_count'] >= 3
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path
```

`period` = `datetime.now().strftime('%Y-%m')`. Convention idempotente :
plusieurs runs dans le même mois écrasent le snapshot du mois (le
dernier gagne).

**Important** : le snapshot Supabase `coin_market_prices` reste INSERT-only.
Le snapshot local n'est qu'un cache pour l'admin — la source de vérité
historique est Supabase.

### C.3 — Helper de calcul delta

`ml/api/sources_aggregator.py` (créé en Phase D) consommera ces snapshots.
Ne rien faire ici — juste s'assurer qu'ils sont écrits correctement.

### Validation Phase C

```bash
# 1. Markers écrits
go-task ml:scrape-ebay -- --limit 3
cat ml/state/sources_runs.json
# → doit contenir une entrée 'ebay' avec last_run_at récent

# 2. Snapshot prix écrit
ls ml/state/price_snapshots/
# → doit contenir ebay_2026-04.json (mois courant)
cat ml/state/price_snapshots/ebay_2026-04.json | jq '.coins | length'
# → nombre de pièces avec ≥3 samples
```

---

## Phase D — Endpoint `GET /sources/status`

**Spec complète** : `docs/sources/backend.md`.

### D.1 — Module `ml/api/sources_aggregator.py`

```python
SOURCES_REGISTRY = [
    {'id': 'numista_match', 'label': 'Numista — Match', ...},
    # ... cf. backend.md pour le registry complet
]

def build_status() -> dict:  # SourcesStatusResponse
    return {
        'sources': [_build_one(s) for s in SOURCES_REGISTRY],
        'quota_groups': _build_quota_groups(),
    }
```

`_build_one` lit :
- Quota : `QuotaTracker(source, window, limit).total()` → `SourceQuota`
- Temporal : `sources_runs.json[source_id]` + calcul `days_since_last_run`,
  `overdue` (= days > 1.5 × cadence)
- Delta : pour eBay, lire les 2 derniers fichiers
  `ml/state/price_snapshots/ebay_*.json` et calculer
  `n_stable / n_new / n_dropped / delta_p50_median_pct / p10 / p90 /
  swing_warning`. Pour les autres, dériver `n_new` / `n_dropped` depuis les
  snapshots du dossier `ml/datasets/sources/` (comparaison de listes
  d'`eurio_id` ou de `numista_id` selon la source).
- Coverage : query Supabase **une fois** par requête HTTP — pas par poll —
  cachée 60s avec `lru_cache(ttl=...)` ou un cache simple in-memory.

### D.2 — Router `ml/api/sources_routes.py`

```python
from fastapi import APIRouter
from .sources_aggregator import build_status

router = APIRouter(prefix='/sources', tags=['sources'])

@router.get('/status')
def sources_status() -> dict:
    return build_status()
```

### D.3 — Branchement

`ml/api/server.py` :

```python
from . import sources_routes
app.include_router(sources_routes.router)
```

### D.4 — Wikipedia en mode future

Le registry doit produire, pour Wikipedia, une carte avec `is_future=True`,
`future_note=...`, et tout le reste (temporal, delta, coverage) à des
valeurs par défaut sentinelles. Le frontend s'adapte automatiquement (déjà
implémenté côté Vue).

### Validation Phase D

```bash
go-task ml:api  # Lance FastAPI
curl http://localhost:8042/sources/status | jq
# → JSON conforme au type SourcesStatusResponse de useSourcesApi.ts
# → 8 entrées dans .sources, dont 1 avec .is_future == true
# → .quota_groups.numista non null
```

Vérifier la latence : doit rester < 200ms à froid, < 50ms en cache. Si plus,
profile et déplace le calcul Supabase coverage en background (cf.
`backend.md` "Performance").

---

## Phase E — Branchement frontend

Une fois D livré et testé :

`admin/packages/web/src/features/sources/pages/SourcesPage.vue` ligne ~28 :

```diff
-import {
-  fetchSourcesStatusMocked,
+import {
+  fetchSourcesStatus,
   ...
 } from '../composables/useSourcesApi'

 const sourcesPoller = usePoller(
-  () => fetchSourcesStatusMocked(),
+  () => fetchSourcesStatus(),
   10_000,
```

Aussi ligne ~40 dans `refreshSources()`. **Garder le bandeau "Données
mockées"** masqué via une condition `v-if` qui devient false quand le
fetch réel réussit (ou retirer le bandeau complètement, à ton goût).

Re-test : nav sur `/sources`, vérifier que les 8 cartes affichent les
vraies données. Wikipedia doit toujours être en mode `is_future`.

---

## Phase F — Test bout-en-bout

```bash
# 1. ML API up
go-task ml:api &

# 2. Admin web up
cd admin && pnpm dev &

# 3. Lancer un scrape eBay réel (consomme ~5 calls)
go-task ml:scrape-ebay -- --limit 3

# 4. Naviguer sur http://localhost:5173/sources
# → la carte eBay doit afficher "il y a 0j", quota daily incrémenté
# → toutes les autres cartes affichent leurs vraies données
# → Wikipedia reste grisée
```

Si tout passe : la feature est shippée.

---

## Mock à re-synchroniser après Phase B

Quand B.5 (`ml:quota:status`) est livré, ré-ajouter dans
`useSourcesApi.ts` les 2 entrées CLI retirées par l'audit précédent — sur
les cartes `numista_match` (ou autre carte Numista) et `ebay` :

```typescript
{
  kind: 'status',
  title: 'Status quota',
  command: 'go-task ml:quota:status -- --source=numista',
  description: 'Dump JSON du quota Numista courant',
  expected_outcome: 'calls/limit/remaining/exhausted par clé',
},
// Idem avec --source=ebay sur la carte ebay
```

Ces entrées sont mockées (Phase E remplace les mocks par le vrai endpoint),
mais doivent rester présentes pour que l'utilisateur ait la commande en
main dans l'UI.

## Pièges connus / à anticiper

### Pré-existant (pas ton problème)

- `pnpm typecheck` à la racine `admin/packages/web/` remonte des erreurs
  dans `audit/`, `coins/CoinDetailPage.vue`, `lab/`, `sets/`. **Ces
  erreurs sont pré-existantes**, sans rapport avec sources/. Ignore-les.
- `coin_market_prices` n'est pas encore dans
  `admin/packages/web/src/database.ts` (Supabase types). À régénérer
  avec `supabase gen types typescript` quand la migration eBay sera
  propagée — pas dans le scope `/sources`.

### Concurrence SQLite

`api_call_log` doit être atomique. SQLite WAL + le pattern `INSERT ... ON
CONFLICT (...) DO UPDATE SET calls = calls + 1` actuel suffit. **Ne pas**
faire un read-modify-write côté Python — tout doit passer par une seule
requête SQL atomique.

### Reset mensuel automatique

Pas de cron. Le `period` est calculé à chaque appel
(`datetime.now().strftime('%Y-%m')`), donc une nouvelle ligne
`(numista, key, monthly, '2026-05')` s'incrémente naturellement le 1er du
mois. Les anciennes lignes restent (utiles pour historique).

### Wikipedia coverage = 0 / 21

Dans le mock, Wikipedia a `coverage.total_target = 21` (les 21 pays
eurozone). Côté backend, hardcode cette valeur dans le registry pour
garder un signal de cible visible même sans implémentation. C'est ok :
ça documente l'intention.

## Done quand

- [ ] Phase A : 6 flags argparse ajoutés, validés à la main
- [ ] Phase B : `api_call_log` migré, `KeyManager` refacto, `EbayClient`
      instrumenté, `ml:quota:status` opérationnel
- [ ] Phase C : `ml/state/sources_runs.json` mis à jour à chaque run,
      snapshots prix eBay écrits dans `ml/state/price_snapshots/`
- [ ] Phase D : `GET /sources/status` retourne le contrat complet,
      latence < 200ms à froid
- [ ] Phase E : `SourcesPage.vue` consomme le vrai endpoint
- [ ] Phase F : test bout-en-bout passant — un scrape réel se reflète
      immédiatement dans l'admin

## Hors scope

Tout ce qui est dans `docs/sources/v2-triggering.md` (déclenchement de
fetch depuis l'UI). Ne pas attaquer.

Le scraper Wikipedia. Garder la carte en mode `is_future`.

## En cas de blocage

Les ❓ à brainstormer (non-bloquants pour ce plan) :

1. Si le calcul de delta filesystem devient trop lent (>500ms total
   endpoint), on cache dans `ml/state/sources_status_cache.json` —
   décision à prendre seulement si le profil le démontre.
2. Si la coverage Supabase pose problème (egress free tier), on stocke
   un compteur `enriched_count` directement dans `sources_runs.json` à
   chaque run.

Sinon : tout est dans les docs `docs/sources/*.md`. Bonne route.
