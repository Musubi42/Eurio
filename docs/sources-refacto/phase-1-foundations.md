# Phase 1 — Fondations

> Tables, base modulaire, refacto eBay vers le nouveau contrat.
> **Bloque toutes les phases suivantes.**

## Pourquoi cette phase

- Sans tables, rien n'a où atterrir.
- Sans `_base/`, chaque nouveau scraper réinvente la roue (cf.
  `module-contract.md`).
- eBay est le **bon premier candidat** parce qu'il existe déjà, qu'il
  est utilisé en routine, et qu'il est le gisement images le plus
  important (capture des images au passage des runs prix).

## Périmètre

### 1.1 Schéma DB

- Migration Supabase : `image_assets`, `coin_market_quotes`,
  `source_runs` (DDL complet dans `schema.md`).
- Régénérer `supabase/types/database.ts`.
- Pas de touch à `coins`, `coin_images`, `coin_market_prices` legacy.

### 1.2 Base modulaire `ml/sources/_base/`

À créer :

- `sources_registry.py` — dataclass `SourceSpec` listant chaque source
  avec `id`, `kind`, `quota`, `license`, `cadence_days`,
  `default_variant_kind`. Exposable par `GET /sources/status`.
- `run_logger.py` — context manager qui ouvre/ferme un row
  `source_runs`. Gère `start`, `bump`, `end`.
- `quota_guard.py` — lit/écrit `ml/state/quotas/<source>.json`.
- `dedup.py` — `upsert_image(row)`, `upsert_quote(row)` avec ON
  CONFLICT.
- `storage.py` — calcule `storage_path` selon convention, écrit le
  fichier seulement si nouveau hash.
- `license_map.py` — table source → license + redistributable.
- `condition_map.py` — raw → enum normalisée.
- `http.py` — session requests partagée (UA, retry, backoff).

### 1.3 Refacto eBay vers `ml/sources/ebay/`

- Déplacer `ml/market/ebay_client.py` + `scrape_ebay.py` vers
  `ml/sources/ebay/`.
- Adapter `fetch.run(ctx, EbayFilters)` au nouveau contrat.
- **Capturer les images au passage** : pour chaque listing, créer une
  row `image_assets` par image (jusqu'à 3 par listing, configurable),
  télécharger en local, marquer `variant_kind='auction_listing'`,
  `training_eligible=false` (le pipeline qualité — phase 3 —
  remplira ça).
- Continuer à écrire les prix dans `coin_market_quotes` (`source='ebay_active'`).
- **Conserver l'écriture legacy** dans `coin_market_prices` pendant la
  transition pour ne pas casser la page admin existante. Un flag
  `--legacy-mirror` pendant 1 cycle, retiré à la fin.

### 1.4 Tasks go-task

- Renommer / aliaser :
  - `ml:scrape-ebay` → alias de `ml:src:ebay:run`
  - `ml:scrape-ebay-dry` → alias de `ml:src:ebay:dry`
- Ajouter `ml:src:ebay:status`, `ml:src:ebay:limit`.

### 1.5 Tests

- `tests/sources/test_base_dedup.py` — l'ON CONFLICT marche, fichier
  pas réécrit si même hash.
- `tests/sources/test_base_quota.py` — quota se décrémente, raise
  quand épuisé.
- `tests/sources/ebay/test_fetch_smoke.py` — dry run ne touche ni la
  DB ni le disque.

## Out of scope (phase 1)

- Migration Numista, BCE, MdP, LMDLP vers `ml/sources/` — ces
  modules continuent de vivre sous `ml/referential/` jusqu'à
  phase 2/3. Ils peuvent quand même écrire dans `image_assets` via
  un adaptateur léger si on veut commencer à matérialiser leur
  contribution sans refactor profond — décision au moment de
  l'implém.
- Pipeline qualité photos (phase 3).
- Page détail admin (phase 4).

## Ordre d'attaque

1. Migration DB + types
2. `_base/` au complet, avec tests unitaires
3. Refacto eBay, tests smoke
4. Validation manuelle : un `go-task ml:src:ebay:limit -- 5` doit
   créer 5 rows quotes + ~10-15 rows images sur disque + DB.
5. Tag git `sources-refacto-phase1` quand tout vert.
