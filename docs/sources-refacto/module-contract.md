# Contrat modulaire `ml/sources/<source>/`

> Ce que tout module source — ancien ou nouveau — doit respecter.

## Structure type

```
ml/sources/
├── _base/
│   ├── __init__.py
│   ├── sources_registry.py       ← liste les sources autorisées + métadonnées
│   ├── run_logger.py             ← INSERT source_runs, update status, count
│   ├── quota_guard.py            ← check + decrement quota par source/key
│   ├── dedup.py                  ← upsert image_assets / coin_market_quotes par (source, source_ref)
│   ├── storage.py                ← écriture disque ml/datasets/sources/<source>/...
│   ├── license_map.py            ← mapping source → license + redistributable
│   ├── condition_map.py          ← raw condition string → enum normalisée
│   └── http.py                   ← session HTTP avec retry/backoff/UA partagé
├── numista/
│   ├── __init__.py
│   ├── fetch.py                  ← logique fetch + parse → rows
│   ├── schema.py                 ← dataclasses des payloads source
│   ├── cli.py                    ← entrypoint Click pour go-task
│   └── README.md                 ← license, ToS, quirks, exemples
├── ebay/
│   └── … (idem)
├── catawiki/
│   └── …
└── …
```

Les modules `ml/referential/` et `ml/market/` existants sont
progressivement migrés sous `ml/sources/<source>/` (phase 1 commence
par eBay).

## Contrat de `fetch.py`

Chaque module expose au minimum :

```python
from ml.sources._base import RunContext, FetchResult

def run(ctx: RunContext, filters: Filters) -> FetchResult:
    """
    Fetch complet ou filtré, écrit dans image_assets / coin_market_quotes.
    Retourne un FetchResult avec n_images, n_quotes, n_errors, n_calls.
    Lève QuotaExhausted si quota épuisé en cours.
    """
```

`RunContext` porte :
- `run_id` (UUID, créé par `run_logger`)
- `dry_run: bool`
- `db_session`
- `quota` (instance de `QuotaGuard` pour cette source)
- `storage_root: Path`
- `logger`

`Filters` est un dataclass par source (ex: `EbayFilters(countries=[...], limit=5)`).

Le module **ne sait rien** de la table cible directement — il appelle
`ctx.upsert_image(...)` et `ctx.upsert_quote(...)` qui passent par
`_base/dedup.py`.

## Contrat go-task uniforme

Toute source expose 4 commandes minimum :

```yaml
# ml/Taskfile.yml
ml:src:<source>:run:
  desc: "Run complet de la source <source>"
  cmds:
    - python -m ml.sources.<source>.cli run

ml:src:<source>:dry:
  desc: "Preview sans écrire"
  cmds:
    - python -m ml.sources.<source>.cli run --dry

ml:src:<source>:limit:
  desc: "Run limité (test rapide)"
  cmds:
    - python -m ml.sources.<source>.cli run --limit {{.CLI_ARGS}}

ml:src:<source>:status:
  desc: "Affiche dernier run + quota courant"
  cmds:
    - python -m ml.sources.<source>.cli status
```

Optionnelles selon la source :

```yaml
ml:src:<source>:reset:        # purge artefacts locaux + reset quota local
ml:src:<source>:countries:    # run filtré par pays
ml:src:<source>:eurio:        # run filtré sur un eurio_id précis
```

Les commandes "haut niveau" historiques (`ml:scrape-ebay`,
`ml:batch-images`) sont conservées comme alias pendant la transition,
puis supprimées une fois la migration complète.

## Logging & runs

- À chaque démarrage : `run_id = run_logger.start(source, kind, filters)`.
- Pendant le run : `run_logger.bump(run_id, n_calls=…, n_images=…, n_errors=…)`.
- À la fin : `run_logger.end(run_id, status='success'|'failed'|'partial', error_summary=…)`.

Les `cli_hints` exposés par la page admin **doivent matcher
exactement** les commandes go-task écrites dans le `Taskfile.yml`.
Pas de drift toléré.

## Quota guard

`_base/quota_guard.py` lit/écrit `ml/state/quotas/<source>.json` :

```json
{
  "window": "monthly",
  "period": "2026-05",
  "limit": 1800,
  "calls": 1247,
  "per_key": [
    {"slot": 1, "key_hash": "a3b9c1f24e8d", "calls": 1247, "exhausted": false},
    {"slot": 2, "key_hash": "d8e2f4901abc", "calls": 0, "exhausted": false}
  ]
}
```

Avant chaque call API : `quota.check_and_decrement(weight=1)`. Si
épuisé, raise `QuotaExhausted`, le run logger marque `status='partial'`
et logge ce qui a été récolté avant l'arrêt.

Pour les scrapes HTML sans quota dur (LMDLP, MdP, Catawiki…), le
quota guard impose un **rate limit** configurable par source (calls/s)
mais ne bloque pas.

## Dédup

`_base/dedup.py.upsert_image(row)` :

1. Calcule `source_ref` selon la convention (cf. `schema.md`).
2. `INSERT … ON CONFLICT (source, source_ref) DO UPDATE SET fetched_at = now(), raw_payload = excluded.raw_payload`.
3. **Le fichier disque n'est pas réécrit** si déjà présent (vérifie
   par hash). On ne re-télécharge pas si le fichier existe et que sa
   taille matche.

Pour `coin_market_quotes`, l'unicité est `(source, eurio_id, period_start, condition_normalized)` — un re-fetch dans le même mois met à jour, pas crée.

## Storage

```
ml/datasets/sources/
├── numista/
│   └── <eurio_id>/
│       ├── obverse_<hash>.jpg
│       └── reverse_<hash>.jpg
├── ebay/
│   └── <eurio_id>/
│       └── <itemId>_img0_<hash>.jpg
├── catawiki/
│   └── <eurio_id>/
│       └── <lotId>_img2_<hash>.jpg
…
```

`<hash>` = SHA-256 court (8 hex) du contenu, évite d'écraser une
image légèrement différente sous le même nom de listing.

Les chemins sont absolus dans `image_assets.storage_path` (relatif au
repo root), pour pouvoir bouger plus tard vers S3 sans casser le
schéma.

## Onboarding nouvelle source — checklist

1. Créer `ml/sources/<source>/{__init__.py, fetch.py, schema.py, cli.py, README.md}`
2. Ajouter `<source>` dans `_base/sources_registry.py` avec quota,
   license, kind, cadence cible.
3. Ajouter mapping dans `_base/license_map.py` et `_base/condition_map.py`.
4. Implémenter `fetch.run(ctx, filters)` qui appelle `ctx.upsert_image` / `ctx.upsert_quote`.
5. Ajouter les 4 tasks `ml:src:<source>:{run,dry,limit,status}` dans `ml/Taskfile.yml`.
6. Ajouter une carte côté admin (`useSourcesApi.ts`) — automatisable
   via lecture de `_base/sources_registry.py` exposée par
   `GET /sources/status`.
7. Tests : un `test_fetch_smoke.py` qui vérifie que `dry_run` ne
   touche pas la DB et écrit un summary cohérent.
8. Documenter ToS, license, quirks dans le `README.md` du module.
