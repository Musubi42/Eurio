# Progress — sources refacto

> Append-only. Une entrée par session significative. Format : date,
> phase touchée, ce qui a été fait, ce qui bloque ensuite.

## 2026-05-02 — Doc initiale

- Discussion produit : matrice photos + matrice prix, séparation
  stricte par source, dédup intra-source uniquement.
- Décisions actées (cf. `README.md` § Décisions actées).
- Doc `docs/sources-refacto/` créée avec :
  - `README.md` (vision + index + décisions)
  - `analysis.md` (état par source)
  - `schema.md` (DDL des 2 nouvelles tables)
  - `module-contract.md` (structure `ml/sources/<source>/`)
  - `quality-pipeline.md` (filtre photos)
  - `admin-ux.md` (page détail `/sources/:id`)
  - `phase-1-foundations.md`
  - `phase-2-new-sources.md`
  - `phase-3-quality-pipeline.md`
  - `phase-4-admin-ux.md`
  - `open-problems.md`
- **Aucun code livré.**
- **Prochaine étape** : phase 1 — migration DB + `ml/sources/_base/` +
  refacto eBay.

## 2026-05-02 — Brainstorm + consolidation (vision Raphaël)

Critique de la doc initiale + alignement sur la vision produit. Choix
structurants actés :

- Label = `eurio_id` (pas `design_group`) — Albert II BE 2002/2008
  prouve que les design_groups étaient trop lâches.
- Pipeline résolution 3 niveaux : `auto_name` (v1) → `auto_dino`
  (futur) → `manual` via review queue.
- `eurio_id` nullable post-fetch, jamais de delete auto.
- Schéma split `source_images` (raw) + `image_assets` (crops).
- Multi-coin lots OK : crop multiple via OpenCV/YOLO, pas de quote.
- Quotes non-résolues → `pending_quotes`, promues à la résolution.
- Quotas et runs full SQLite, JSON déprécié.
- Dédup pHash + propagation auto de label.
- Anti-leakage DinoV2 : bench exclut `auto_*`, ne dépend que de
  Numista canonical + cohort_capture + manual.
- Mac ↔ PC : pas de DB partagée, sync via export task étendue.
- Review queue V0 livrée en phase 1 (sans elle, ingestion = entrepôt
  mort).

Docs créées / réécrites :
- `decisions.md` (NEW) — 12 décisions actées
- `schema.md` (REWRITE) — split + nouvelles tables
  pending_quotes, review_queue
- `review-queue.md` (NEW) — vision complète + V0 minimale
- `module-contract.md` (UPDATE) — SQLite, fetch en 5 étapes
- `phase-1-foundations.md` (UPDATE) — review queue + sync Mac/PC + tests
- `open-problems.md` (UPDATE) — OP-1 désormais adressée
- `README.md` (UPDATE) — pointers + résumé décisions

**Prochaine étape** : discussion archi code (scrapers, orchestrateur,
détecteur, résolveur) avant d'attaquer la phase 1.

## 2026-05-02 — Archi orchestration gravée + fondations phase 1 démarrées

### Décisions complémentaires actées

- **D-13** Pipeline étape-par-étape (6 étapes : Discover → Persist →
  Download → Detect & crop → Resolve → Enqueue review). Pas
  monolithique. Idempotence par étape, batch-friendly, reprise après
  crash.
- **D-14** Triggers en CLI uniquement en V1. Pas de
  `POST /sources/:id/run` côté API. Admin reste read-only +
  review queue.
- **D-15** Prix d'un lot multi-pièces conservé en
  `source_images.listing_price` pour audit, jamais promu vers
  `coin_market_quotes`.

DinoV2 simplifié (clarification du chantier #7) : ne fait que
**pré-remplir `candidate_eurio_ids`** dans review_queue. Plus de
`auto_dino` status — validation finale toujours humaine. Effet
collatéral : data leakage anti-mur quasi gratuit.

D-06 simplifié : Mac et PC sont deux installations totalement
indépendantes, pas de sync inter-machine.

### Doc créée / mise à jour

- `orchestration.md` (NEW) — 4 couches, pipeline 6 étapes, modules,
  API surface V1, séquence review, évolutions V2.
- `decisions.md` — D-02, D-06, D-08 simplifiés ; ajout D-13, D-14, D-15.
- `schema.md` — `auto_dino` retiré de l'enum.
- `review-queue.md` — DinoV2 = aide review, pas auto-label.
- `phase-1-foundations.md` — section sync Mac/PC supprimée.

### Code livré (phase 1.1 + 1.2 partielle)

**Schéma SQLite** appended à `ml/state/schema.sql` :
- `source_runs` (avec `current_step`, `n_*` counters)
- `source_images` (raw, FK vers source_runs)
- `image_assets` (crops, FK vers source_images, resolution_status
  enum, phash, training_eligible)
- `coin_market_quotes` (UNIQUE sur condition_raw, pas
  condition_normalized — fix critique #7)
- `pending_quotes`
- `review_queue`
- Tous les indexes (run_id, status, phash, face, eurio_id, etc.)

**Modules `ml/sources/_base/`** :
- `__init__.py` — re-exports
- `sources_registry.py` — `SourceSpec` dataclass + `SOURCES` dict
  pour 9 sources (numista, ebay, lmdlp, mdp, bce, catawiki,
  numiscorner, cgb, wikipedia avec is_future flag)
- `run_logger.py` — `start_run` context manager, `RunHandle` avec
  `set_step` / `bump` / `end`, anti-double-run (`RunAlreadyRunning`
  exception), auto-fail sur exception
- `dedup.py` — dataclasses + upsert idempotents pour
  `source_images`, `image_assets`, `coin_market_quotes`,
  `insert_pending_quote`, `delete_pending_quotes_for`

**Tests** `ml/tests/test_sources_base.py` (8 tests, tous verts) :
- création des tables au bootstrap
- lifecycle complet d'un run (start → step → bump → end)
- run.end='failed' quand exception levée
- anti-double-run + bypass `force=True`
- upsert source_image idempotent
- upsert image_asset idempotent
- regression test : 'FDC' et 'SUP-62' (qui mappent tous deux vers
  `condition_normalized='UNC'`) créent **2 rows** distinctes dans
  `coin_market_quotes` parce que la unique key est sur `condition_raw`
- pending_quote insert + delete

**Config** :
- `ml/pyproject.toml` — `sources*` ajouté à `packages.find.include`
- `.gitignore` — exclut `ml/datasets/sources/`,
  `ml/state/sources_runs.json`, `ml/state/quotas/`,
  `ml/state/price_snapshots/` (D-06)

### Reste à faire en phase 1 (par ordre d'attaque suggéré)

1. **`_base/storage.py`** — chemins canoniques + write_raw + write_crop
   avec hash-based dedup disque.
2. **`_base/quota_guard.py`** — wrapper sur `ml/api_quota.py` SQLite
   existant + rate-limit pour scrapes (calls/s).
3. **`_base/http.py`** — session requests partagée (UA, retry,
   backoff, timeout).
4. **`_base/license_map.py`** + **`_base/condition_map.py`**.
5. **`ml/detection/`** — factorisation YOLO+Hough depuis `ml/scan/`,
   API `detect_coins(image_path) -> list[bbox]` mode batch CPU.
6. **`ml/resolution/name_match.py`** — extraction (country, year,
   denomination) depuis listing metadata + matching contre `coins`,
   retourne top-5 avec scores. Seuils 0.85 / 0.55 (D-13).
7. **`ml/resolution/phash_propagate.py`** — calcul pHash + lookup +
   propagation de label.
8. **`ml/review_queue/enqueue.py`** — calcul priority + insert.
9. **`_base/orchestrator.py`** — pipeline 6 étapes générique.
10. **`ml/sources/ebay/`** — refacto depuis `ml/market/scrape_ebay.py`
    vers le nouveau contrat (fetch.py + cli.py + filters.py).
11. **API endpoints** review_queue (`GET /review-queue`,
    `POST /review-queue/:id/decide` avec promotion pending→quote, etc.).
12. **Page Vue `/review`** (admin) V0 minimaliste.
13. **Tasks go-task** `ml:src:ebay:{run,dry,limit,status}` + alias.
14. **Migration legacy** `ml/state/sources_runs.json` → table SQLite
    (one-shot script + suppression du JSON).

### Comment reprendre dans une nouvelle session

1. Lire `decisions.md` + `orchestration.md` + `schema.md` (15 min).
2. Lire ce log progress.md jusqu'au bout pour voir ce qui est déjà
   livré.
3. Vérifier que les tests passent toujours :
   `cd ml && .venv/bin/python -m pytest tests/test_sources_base.py -q`
4. Reprendre la todo "Reste à faire en phase 1" ci-dessus dans
   l'ordre.
