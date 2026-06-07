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

## 2026-05-02 — Front admin sources refacto + Step 1 backend

### Front admin (livré, ~6h cumulées)

5 chunks audités visuellement par l'utilisateur entre chaque livraison.
Tous typecheckent propre (`pnpm typecheck` sur `admin/packages/web`,
les erreurs résiduelles sont pré-existantes hors scope refacto).

- **Chunk 1** — `/sources` : passage de 3 sections (Numista / Marché /
  Éditorial) à **2 sections** (`Référentiel canonique` /
  `Enrichissement`). Décision UX validée pendant la session : la
  frontière marché vs éditorial ne tient pas (eBay produit parfois
  meilleures photos que MdP). Ajout pill `PRODUIT · …` auto-doc sur
  chaque card + chevron `Détails →` discret. Architecturalement, on a
  posé `SOURCE_PIPELINE_META: Record<SourceId, {role, produces}>`
  (constante côté front) plutôt que d'étendre l'interface
  `SourceStatus` — c'est de la metadata d'identité, pas du runtime
  qui dépend du backend.
- **Chunk 2** — `/sources/:id` (route + page) : header dense
  persistant (KPIs strip 4 colonnes), 4 onglets (Runs / Données /
  Couverture / Commandes), composable `useSourceDetail.ts` mocké.
- **Chunk 3** — `/review` : split A/B crop ↔ canonique, top-5
  vertical avec stagger, raccourcis 1-5/⏎/R/N/F/Esc/O/V/U, undo
  toast 5s, auto-focus du top-1 si score ≥ 0.5, empty state
  scholaresque.
- **Chunk 4** — modal `CoinSearchModal` : cascade 21 drapeaux pays
  (emoji flag) → chips dénomination → chips année → grille thumbs
  24/page, combobox `/` avec parser fuzzy (`BE 2 2002`, `fr 50c`,
  `DE comm 2020`).
- **Chunk 5** — multi-select + batch toolbar disabled "Coming soon" :
  **livré puis revert**. Cf. ce qui n'a pas marché ci-dessous.

Fichiers ajoutés/modifiés (front) :
- `features/sources/composables/useSourcesApi.ts` (extension)
- `features/sources/components/SourceCard.vue` (extension)
- `features/sources/pages/SourcesPage.vue` (refacto 2 sections)
- `features/sources/pages/SourceDetailPage.vue` (NEW)
- `features/sources/composables/useSourceDetail.ts` (NEW)
- `features/review/{pages,components,composables}/...` (8 nouveaux fichiers)
- `app/router.ts` + `app/nav.ts` (routes /sources/:id et /review)

### Step 1 backend (livré)

Extension du schéma SQL + UDFs pHash + migration JSON → DB.

- **`ml/state/schema.sql`** : ajout table `discovery_log` (couche 1
  du dédup cross-runs) avec UNIQUE(source, source_ref),
  `pipeline_state` enum (`discovered → persisted → downloaded →
  cropped → resolved → rejected`) et 3 indexes.
- **`ml/state/store.py`** : `_register_phash_udfs(conn)` qui
  enregistre `hamming(a, b)` et `phash_match(a, b, threshold)` comme
  UDFs Python deterministic. Hookée dans `_connection()` thread-local.
  Mask interne `& 0xFFFFFFFFFFFFFFFF` pour gérer signed/unsigned int64.
- **`ml/scripts/migrate_sources_runs_to_db.py`** : migration one-shot
  testée idempotente (5/5 insérés au 1er run, 0/5 au 2e).
  `legacy_kind` (scrape/batch_match/enrich/fetch) archivé dans
  `filters_json` plutôt que mappé bêtement.
- **`docs/sources-refacto/schema.md`** : doc `discovery_log` complète
  avec pattern d'usage upsert, section nouvelle "Dédup en 5 couches"
  (table couche/question/mécanisme/coût + cas eBay/Catawiki cross-source),
  section "Recherche pHash et UDF Hamming" (justification SQLite <
  3.43, signature UDF, scaling B-tree → BK-tree au-dessus de 100k).
- **`docs/sources-refacto/decisions.md`** : ajout **D-16** "Pas de
  batch review par multi-select manuel" — le batch est *toujours*
  suggéré par la machine (cluster pHash D-07 ou vue grille parallèle),
  jamais composé à la main dans le flow single-item.
- **`docs/sources-refacto/review-queue.md`** : §"Évolutions futures"
  durci — cluster pHash propagation est *le seul vrai pattern batch*.

### Ce qui a bien fonctionné

- **Chunk-by-chunk avec audit visuel** : la rétro courte de
  l'utilisateur après chaque chunk a évité les divergences. Les
  remarques (taxonomie 2 vs 3 sections, page détail layout, batch
  cassé sémantiquement) ont toutes été attrapées tôt.
- **Discussion stratégique avant d'attaquer Step 1 backend** : poser
  les 5 couches de dédup avec le user *avant* d'écrire le SQL a
  cristallisé l'architecture. La table `discovery_log` est née de
  cette conversation, pas d'un draft initial.
- **Décisions architecturales pragmatiques** : `SOURCE_PIPELINE_META`
  comme constante front plutôt que champ DB, UDF Python deterministic
  plutôt que lib externe pour bit_count, ID déterministe pour la
  migration idempotente. Toutes ces choses ont coûté < 5 min de
  réflexion mais évitent des semaines de friction.
- **Tests intégrés au flow** : `pnpm typecheck` après chaque chunk
  front, smoke test Python pour UDFs/migration. Aucun bug shipped
  vers l'utilisateur.

### Ce qui a moins bien fonctionné

- **Chunk 5 (batch UI) implémenté avant d'avoir vérifié la sémantique
  du workflow.** L'utilisateur a immédiatement vu que le pattern
  "checkbox au passage en single-item" est conceptuellement cassé :
  pour batcher, il faut *voir* les items à grouper. Coût : ~30 min
  de code à écrire puis revert. Leçon : avant d'implémenter une UX
  composée, formuler le scénario d'usage en 1 phrase ("je vois un
  item, j'en coche plusieurs, ensuite je…") et vérifier qu'il tient.
- **Quelques erreurs structurales SFC Vue** : second `<script>` non
  setup dans `SourceDetailPage.vue` initial (corrigé), import
  `onBeforeUnmount` placé mid-file dans `CoinSearchModal.vue`
  (corrigé). Erreurs de base à éviter — toujours mettre les imports
  en haut, jamais deux blocs script dans un SFC.
- **Pas de stratégie batch claire dès le kickoff** : le doc kickoff
  mentionnait "mode batch dès V1 dans l'UI" sans avoir tranché le
  *workflow* sous-jacent. Si on avait écrit "le batch est suggéré
  par cluster pHash, jamais multi-select" avant de coder, le Chunk 5
  n'aurait pas existé.

### Reste à faire (mise à jour de la todo)

✅ Tâches **14** (migration JSON → DB) faite via
`scripts/migrate_sources_runs_to_db.py`.
✅ Tâches **11/12** (API endpoints review + page Vue review) — mockées
côté front, à câbler quand le backend exposera les endpoints.

Ordre d'attaque pour la suite (cf. `orchestrator-kickoff.md`) :
- **Étape 2 — Orchestrateur 6 étapes** (le gros morceau, ~1 jour
  découpable en 2.A / 2.B / 2.C / 2.D)
- Étape 3 — Première source réelle bout-en-bout (eBay)
- Étape 4 — API FastAPI pour basculer les fetchers front du mock au réel
- Étape 5 — Auto-name (résolution niveau 1)

### Comment reprendre dans une nouvelle session

1. Lire `orchestrator-kickoff.md` (brief auto-suffisant pour la
   prochaine session).
2. Vérifier que les tests passent toujours :
   `cd ml && .venv/bin/python -m pytest tests/test_sources_base.py -q`
3. Vérifier que la migration n'a rien à faire (devrait dire
   "5 skipped" si elle a déjà tourné, ou "5 inséré" sinon) :
   `cd ml && .venv/bin/python -m scripts.migrate_sources_runs_to_db --dry-run`
4. Attaquer le chunk **2.A** (Interface `SourceAdapter` + `Orchestrator`
   squelette).

## 2026-05-03 — Étape 2 : Orchestrateur 6 étapes livré (chunks 2.A → 2.D)

Pipeline d'ingestion bout-en-bout opérationnel sur un mock adapter,
avec idempotence validée sur les 5 couches de dédup (D-13).

### Chunks livrés

- **2.A** — Interface `SourceAdapter` (Protocol) + `SourceQuery`
  (dataclass strict + `extra: dict`) + `DiscoveredItem` +
  `RawDownloadResult`. Squelette `run_pipeline()` qui parcourt les 6
  steps en stubs. Mock adapter avec 5 fixtures (coins 64/80/88/96/104,
  obverse.jpg réels). Test bout-en-bout vert.
- **2.B** — Discover + Persist en vrai. `query_signature` (sha256 16
  chars stable). Helpers `upsert_discovery_log` + `set_discovery_pipeline_state`
  ajoutés à `dedup.py`. Idempotence validée : run #1 → 5 rows, run
  #2 → 0 nouvelles rows, `last_seen_at` strictement avancé.
- **2.C** — Download + Detect & crop. `storage.py` (chemins canoniques
  sharded `<sha1[0:2]>/`, écriture atomique). `phash.py` DCT 64-bit
  signed (compatible UDFs `hamming` / `phash_match`). `scan.normalize_studio_path`
  réutilisé directement, **pas de fallback silencieux** (D-17). Erreurs
  par item non-bloquantes (`n_errors` compteur, autres items continuent).
  Audit visuel : 5 crops 224×224 produits depuis les obverse Numista.
- **2.D** — Resolve (V1 : tout en `needs_review`, pas d'auto-name —
  D-18) + Enqueue review. Priority calc : 100 base, -30 si
  `target_eurio_id` connu. `review_queue.UNIQUE(image_asset_id)`
  garantit l'idempotence (5 inserts run #1, 0 run #2).

### Critère de succès atteint

Trace bout-en-bout sur 2 runs consécutifs (logs réels) :

```
RUN #1 — status=success
  discover → 5 items (5 new / 0 already-seen)
  persist  → 5 added / 0 refreshed
  download → 5 new / 0 skipped / 0 errors
  detect   → 5 crops / 0 skipped / 0 errors / 0 auto_phash
  resolve  → 5 marked needs_review / 0 already-resolved
  enqueue  → 5 new / 0 already-queued

RUN #2 (même query) — status=success
  discover → 5 items (0 new / 5 already-seen)   ← C1 (discovery_log)
  persist  → 0 added / 5 refreshed              ← C2 (source_images.UNIQUE)
  download → 0 new / 5 skipped / 0 errors       ← C3 (filesystem)
  detect   → 0 crops / 5 skipped / 0 errors     ← C4 (image_assets.UNIQUE + pHash)
  enqueue  → 0 new / 5 already-queued           ← C5 (review_queue.UNIQUE)
```

17/17 tests verts (`tests/test_orchestrator.py` 9 + `tests/test_sources_base.py` 8).

### Fichiers livrés

```
ml/sources/_base/
  adapter.py            NEW — SourceAdapter Protocol + dataclasses
  orchestrator.py       NEW — run_pipeline(adapter, query, *, store, dry_run, force)
  query_sig.py          NEW — compute_query_signature
  storage.py            NEW — chemins canoniques + write_atomic
  phash.py              NEW — DCT 64-bit signed
  dedup.py              EXT — +upsert_discovery_log, +set_discovery_pipeline_state
  sources_registry.py   EXT — entrée 'mock' (fixture, is_future=True)
  steps/
    __init__.py         NEW
    discover.py         NEW — C1 dédup
    persist.py          NEW — C2 dédup + license/redistributable du SourceSpec
    download.py         NEW — C3 dédup
    detect_crop.py      NEW — C4 dédup pHash, normalize_studio direct (D-17)
    resolve.py          NEW — V1 tout en needs_review (D-18)
    enqueue.py          NEW — C5 dédup + priority calc

ml/sources/_mock/
  __init__.py           NEW
  adapter.py            NEW — 5 fixtures coins 64/80/88/96/104

ml/tests/
  test_orchestrator.py  NEW — 9 tests (incl. audit visuel + idempotence
                              + dédup + priority + signature stable)
```

### Décisions actées en cours de session (cf. decisions.md)

- **D-17** — Pas de fallback silencieux dans `detect_crop`.
- **D-18** — Pas d'auto-name en V1 (réintroduit après stats sur vraies
  données pour calibrer un seuil défendable).

### Ce qui a bien fonctionné

- **Découpage 2.A → 2.D auditable.** Chaque chunk testable en
  isolation a permis de repérer immédiatement les pépins (overflow
  SQLite signed/unsigned sur pHash, `_DATASETS_ROOT` parents[3]
  vs [2]) avant qu'ils ne s'accumulent.
- **Décisions tranchées avant code.** Les 9 questions du kickoff
  (Protocol vs ABC, hash format, fallback, auto-name, fixtures, etc.)
  ont été toutes débattues avant 2.A. Aucun bikeshed à mi-chemin.
- **Audit visuel des crops vraiment regardés.** Le critère "j'ouvre
  les PNG dans le Finder et je vois 5 crops corrects" a remplacé un
  `assert image.shape == (224,224,3)` qui passe sans rien prouver.
- **Erreur par item non-bloquante.** Le pattern `continue + bump
  n_errors` permet à un run sur 5 items où 1 échoue de produire 4
  résultats utilisables — critique pour les vraies sources où une
  image corrompue ne doit pas casser tout le run.

### Ce qui a moins bien fonctionné

- **Indentation cassée par un Edit partiel** sur `orchestrator.py`
  (déplacement du `with` sans réindenter le contenu) — corrigé via
  Write complet. Leçon : pour réorganiser un bloc indenté, préférer
  Write entier plutôt qu'un Edit ciblé.
- **Overflow `OverflowError: Python int too large`** non anticipé.
  pHash retourne unsigned 64-bit, SQLite INTEGER est signed 64-bit.
  Les UDFs masquent en interne mais le store du Python int brut
  pète. Fix : conversion unsigned → signed dans `compute_phash` (15
  lignes après le commentaire). À retenir pour tout entier ≥ 2^63
  qui doit aller dans SQLite.

### Reste à faire (hors session 2)

1. **CLI `go-task ml:src:mock:run`** + bouton dry-run dans
   `SourceDetailPage.vue` — exposition front du nouveau pipeline.
2. **Vraie source eBay** (étape 3 du plan stratégique) : implémenter
   `ml/sources/ebay/fetch.py` qui satisfait le `SourceAdapter`.
   Utilise quota_guard à câbler aussi.
3. **API FastAPI** `/sources/:id/runs`, `/sources/:id/run`,
   `/review-queue/...` (étape 4) — bascule des fetchers front du
   mock au réel.
4. **Auto-name** réactivé une fois qu'on a des stats sur 200+
   listings eBay (D-18).

### Comment reprendre dans une nouvelle session

1. `cd ml && .venv/bin/python -m pytest tests/test_orchestrator.py tests/test_sources_base.py -v`
   → doit afficher **17 passed**.
2. Run e2e + audit visuel reproductible :

   ```bash
   cd ml && rm -rf /tmp/eurio_audit && .venv/bin/python -c "
   import logging; logging.basicConfig(level=logging.INFO, format='%(message)s')
   from pathlib import Path
   from sources._base import storage
   storage._STORAGE_ROOT = Path('/tmp/eurio_audit/sources')
   import importlib
   from sources._base.steps import download, detect_crop
   importlib.reload(download); importlib.reload(detect_crop)
   from sources._base import orchestrator; importlib.reload(orchestrator)
   from sources._mock import MockAdapter
   from sources._base.adapter import SourceQuery
   from state.store import Store
   store = Store(Path('/tmp/eurio_audit/state.db'))
   orchestrator.run_pipeline(MockAdapter(), SourceQuery(source_id='mock'), store=store)
   "
   open /tmp/eurio_audit/sources/mock/crops/*/*.png
   ```
3. Pour la suite : choisir entre **étape 3 (eBay réel)** ou
   **exposition CLI/front du mock** selon priorité produit.

## 2026-05-03 — CLI + boutons front + API FastAPI

Suite directe à la session 2 : on expose le pipeline orchestrateur
au monde extérieur (terminal + admin web) sans toucher au pipeline
lui-même.

### Chunks livrés

- **CLI (`ml/sources/cli.py`)** — argparse complet (`--source`,
  `--dry-run`, `--country`, `--year`, `--denomination`,
  `--target-eurio-id`, `--limit`, `--db`, `--force`, `-v`).
  Affiche les compteurs final, exit 1 si `failed`.
- **4 nouvelles tasks Taskfile** (`ml:src:run`, `ml:src:run-dry`,
  `ml:src:mock:run`, `ml:src:mock:dry`) — wrap propres avec descriptions.
- **Boutons front Run / Dry run** dans `SourceDetailPage.vue`
  (header à droite, juste sous health pill). Spinner pendant inflight,
  toast résultat coloré (success/warning/danger), bandeau live qui
  rafraîchit `step / +N raws / +N crops / +N review / +N errors` en
  temps réel pendant le run.
- **API 4.A — Trigger + Status** (`ml/api/sources_routes.py`) :
  - `POST /sources/:id/runs?dry_run=&force=` — spawn daemon thread,
    retourne 202 `{run_id, status:"started"}`. 409 si run en cours,
    501 si pas d'adapter, 5xx si timeout d'enregistrement (2s).
  - `GET /sources/:id/runs/:run_id` — snapshot complet 1 run
    (cible polling toutes les 2s).
  - **Startup hook** dans `server.py` : `_sources_startup()` flip les
    `source_runs` orphelines (`status='running'` après crash uvicorn)
    → `'failed'` avec `error_summary='process restart — orphan run'`.
- **API 4.B — Read endpoints** (5 nouveaux GET) :
  - `GET /sources/:id` — header dérivé (label/health/last_run_summary/coverage)
  - `GET /sources/:id/runs?limit=&status=` — liste runs
  - `GET /sources/:id/images?page=&pageSize=` — crops paginés
  - `GET /sources/:id/quotes?page=&pageSize=` — cotations paginées
  - `GET /sources/:id/coverage` — couverture globale (breakdown vide V1)
  - `GET /sources/:id/assets/:asset_id/file` — streaming PNG du crop
    (`FileResponse`)
- **Front composables** (`useSourceDetail.ts`) refactor : 5 fetchers
  (`fetchSourceDetail/Runs/Images/Quotes/Coverage`) essaient le vrai
  endpoint, fallback graceful sur mock si network down (CORS,
  ECONNREFUSED). Page reste utilisable même sans FastAPI lancé. Plus
  `triggerSourceRun()`, `pollSourceRun()`, `fetchSourceRun()`,
  `TriggerError` typé.

### Pattern long-running adopté

`source_runs` table = source de vérité. Pas de status dict in-memory.
Le thread daemon écrit via `start_run()` context manager, le polling
HTTP lit straight from SQLite. Un crash uvicorn laisse l'orphelin en
`'running'` jusqu'au prochain startup où le hook le flip en `'failed'`.

Trade-off assumé (cohérent avec le précédent du repo : training,
export, lab) : aucune supervision processus ; un Ctrl-C en cours de
run laisse le thread mourir, l'orphelin sera nettoyé au reboot. Pour
des runs eBay multi-heures on pourra ajouter une notification
mid-flight ou un mode "fork & detach" plus tard.

### Décisions techniques en cours de session

- **Pas de status dict in-memory** : la table `source_runs` est déjà
  persistée et exhaustive (current_step, n_*, error_summary). Doubler
  l'état serait du couplage gratuit. Le polling DB toutes les 2s coûte
  ~0.1ms par requête.
- **Fallback graceful sur le front** : `getJson()` retourne `null` sur
  network error → composables tombent sur les mocks préexistants.
  Permet de bosser le front sans lancer FastAPI, et évite la page
  blanche si l'utilisateur arrive avant que le backend soit warm.
- **Synthèse de SourceSpec si pas dans aggregator** :
  `_aggregator_source()` fallback sur `sources._base.sources_registry`
  si l'aggregator (qui pilote `/sources/status`) ne connaît pas la
  source. Évite un 404 sur `/sources/mock` (mock = registry-only,
  intentionnellement absent de l'aggregator).
- **5 raccourcis Taskfile vs 1 entrée générique** : 4 alias
  (`src:run`, `src:run-dry`, `src:mock:run`, `src:mock:dry`) car ergo
  shell prime sur DRY pour les commandes manuelles fréquentes.

### Vérifications

- ✅ E2E POST → poll → success vérifié (mock pipeline complet via API
  en 2s, avec n_raws=5, n_crops=5, n_review_enqueued=5, n_errors=0)
- ✅ Edge cases testés : 501 (source sans adapter), 404 (run inconnu),
  202 dry-run (kind='dry', stop après discover)
- ✅ FileResponse : 94 KB PNG renvoyé sur `/assets/:id/file`
- ✅ Typecheck front : 0 régression dans `features/sources/`
  (les 9 erreurs résiduelles sont toutes dans `features/sets/`,
  pré-existantes, hors scope)
- ✅ 17/17 tests Python orchestrator toujours verts

### Ce qui a bien fonctionné

- **Réutiliser `source_runs` comme état partagé thread/HTTP** plutôt
  que d'inventer un job dict : zéro nouveau code de plomberie, et le
  startup hook des orphelins tombe naturellement.
- **Fallback réseau-down côté front** : le pattern "real → null →
  mock" garde l'expérience dev fluide. Coût : 5 lignes de
  `try/catch (TypeError)` par fetcher.
- **POST 202 + polling** : pas de WebSocket, pas de SSE. La cadence
  2s est insensible pour l'utilisateur (les runs mock terminent en
  <2s donc on voit direct le résultat ; les vraies runs sont assez
  longues pour que 2s entre ticks soit pertinent).

### Ce qui a moins bien fonctionné

- **Route file pas planifiée pour les images** : j'ai ajouté
  `/sources/:id/assets/:asset_id/file` après coup quand j'ai réalisé
  que les `<img>` des thumbnails 404eraient. Aurait dû être dans le
  planning 4.B initial. Coût : 15 lignes ajoutées en patch, mais
  l'oubli aurait pété la page Données si on avait livré sans tester.
- **Test e2e sur le wrong DB** : le test inline initial pointait sur
  `ml/state/training.db` (chemin par défaut du Store) au lieu d'une
  DB temp. Résultat : compteurs incohérents (data résiduelle).
  Corrigé en injectant `srv._store = Store(tmp_db)` après import.
  Pattern à formaliser pour les tests d'intégration FastAPI.
- **Deux fix de fallback en série** : `fetchSourceDetail` puis
  `fetchSourceCoverage` lançaient `Source inconnue : mock` parce que
  le fallback mock supposait que toute source est dans
  MOCK_SOURCES_STATUS. Pas grave (5 lignes par fix) mais aurait pu
  être anticipé en testant la page `/sources/mock` plus tôt.

### Reste à faire (la suite immédiate)

- **Étape 4.C — Review queue endpoints** (next session) :
  GET /review-queue, GET /:id, POST /:id/decide, POST /:id/reject,
  GET /stats. Branchement front sur `useReviewQueue.ts` (déjà
  partiellement écrit en mock dans la session frontend précédente).
- **Étape 3 — Vraie source eBay** (session dédiée, mérite son propre
  kickoff doc) : implémenter `ml/sources/ebay/fetch.py`, brancher
  `quota_guard`, gérer la pagination Browse API, mapping
  `condition_raw`. C'est le moment où le pipeline livre de la valeur
  produit (la review queue se remplit, on peut auditer auto-name).

### Comment reprendre dans une nouvelle session

1. `cd ml && go-task ml:api` → l'API démarre sur 8042 avec le hook
   d'orphans + tous les endpoints sources.
2. Dans un autre terminal : `cd admin/packages/web && pnpm dev` →
   front sur 5173.
3. Naviguer à `http://localhost:5173/sources/mock` → cliquer Run →
   bandeau live → toast vert → onglet Runs/Données se peuple avec
   du vrai data.
4. Pour eBay : nouveau kickoff doc à rédiger (cf. `orchestrator-kickoff.md`
   pour le format), ouvrir une session dédiée.

## 2026-05-03 — Brainstorm eBay + kickoff étape 3

Suite directe à la session précédente. Brainstorm long avec
l'utilisateur sur la stratégie eBay, dissipation d'un malentendu de
fond sur le pilotage des sources d'enrichissement, et rédaction du
kickoff doc avant toute ligne de code.

### Le malentendu dissipé

J'avais en tête un modèle "SourceQuery par cohort country/year/denom"
hérité de la session précédente. **Faux modèle.** eBay (et toute
source d'enrichissement) est pilotée par la **liste des `eurio_id`
du référentiel canonique** (issu de Numista). Pas de cohort dans
cette boucle — les cohorts sont un concept training-side, sans rapport
avec l'ingestion source.

La page `/sources` admin a même déjà figé la dichotomie "Référentiel
canonique" / "Enrichissement" en chunk 1 de la session frontend
précédente. J'aurais dû y prêter attention.

### Décisions actées (D-19 → D-27)

Cf. `decisions.md` pour les explications complètes :

- **D-19** Sources d'enrichissement pilotées par `eurio_id`, pas
  cohort. Conséquence : `SourceQuery.country/year/denomination`
  inertes pour eBay. Ajout `target_eurio_ids: list[str] | None`
  (pluriel) en chunk 3.A.
- **D-20** Freshness queue en vue SQL pure (`v_ebay_freshness`),
  ordonnée `last_enriched_at ASC NULLS FIRST`.
- **D-21** 1 run = 1 batch de N eurio_ids (default **10**), pas 50
  (durée + spam risk).
- **D-22** Tout télécharger en HD (`item/{id}` systématique pour
  `additionalImages`). Coût quota assumé, rendu visible front.
- **D-23** Pagination `limit=50` no-paginate V1.
- **D-24** Velocity weighting → vue SQL post-hoc (parking lot V1.5).
- **D-25** Quota stop = `partial`, recovery par idempotence des 5
  couches. Pas de SAVEPOINT.
- **D-26** Lot detection à **2 niveaux** : (a) heuristique titre →
  `source_images.is_lot_suspected` ; (b) `n_crops > 1` sur une image →
  cette image en `review_queue.kind='lot'`. Quote éligible **uniquement
  si** `is_lot_suspected = false`.
- **D-27** Pre-flight quota check avant batch : refuse 409 si
  `estimate × 1.3 > remaining`, suggère `max_safe_batch`.

### Doc créée / mise à jour

- `ebay-kickoff.md` (NEW) — brief auto-suffisant pour la session 3,
  ~300 lignes : malentendu cohort, décisions, archi, découpage 3.A→3.G,
  parking lot V1.5+, endpoints eBay.
- `decisions.md` (UPDATE) — append D-19 → D-27.

### Plan d'attaque session 3 (chunks)

- **3.A** Schema (`is_lot_suspected`, `review_queue.kind`,
  `v_ebay_freshness`) + `SourceQuery.target_eurio_ids` pluriel +
  loop orchestrator. Tests 17/17 verts à conserver.
- **3.B** EbayAdapter core — `discover()` itère eurio_ids, search +
  `item/{id}` HD + group expansion ; `download_raw()` CDN. Tests httpx
  mocked.
- **3.C** API quota + freshness — `GET /sources/ebay/quota-status`,
  `GET /sources/ebay/freshness`, pre-flight 409 dans `POST /runs`.
- **3.D** CLI eBay — `ml:src:ebay:{run,dry,limit,status}` qui lit la
  freshness queue.
- **3.E** Front — `EbayQuotaKPI`, `EbayFreshnessWidget`, `EbayRunDialog`
  pré-run avec estimation. Audit visuel chunk-par-chunk.
- **3.F** Quote + lot routing dans `steps/resolve.py`.
- **3.G** Smoke run réel sur 5 commemos, audit visuel images, doc
  des stats observées (calls/eurio_id, taux lots, etc.).

### Parking lot — V1.5+ documentés dans le kickoff pour ne rien perdre

- Lot review page (`/review/lots`) — UI dédiée à la décomposition
  des coffrets, pré-requis 200+ rows accumulées
- Auto-name calibré sur vraies données (D-18 a différé)
- Velocity weighting view (D-24)
- Pagination > 50 (V2)
- `item/{id}` paresseux si `additionalImages` déjà HD dans summary
- Scheduled re-fetch via `/schedule` agent
- `v_enrichment_freshness` cross-source (multi-source pivot)

### Comment reprendre en début de session 3

1. Lire `ebay-kickoff.md` en entier (10 min).
2. `cd ml && .venv/bin/python -m pytest tests/test_sources_base.py tests/test_orchestrator.py -q`
   → doit afficher **17 passed**.
3. Vérifier token eBay : `.venv/bin/python -c "import os; from market.ebay_client import get_app_token; print(get_app_token(os.environ['EBAY_CLIENT_ID'], os.environ['EBAY_CLIENT_SECRET'])[:20])"`.
4. Attaquer 3.A (schema + SourceQuery extension).

## 2026-05-03 — Étape 3 livrée (eBay bout-en-bout, 3.A.0 → 3.G)

Suite directe au kickoff. 7 chunks livrés sans interruption après
le « Je valide tu peux continuer » de l'utilisateur. Pipeline réel
fonctionnel sur la vraie API eBay.

### Découverte cours-route + correction

Le kickoff initial supposait une table `coins` en SQLite. **Faux** :
le référentiel canonique vit en JSON (`ml/datasets/eurio_referential.json`,
2628 entrées dont 466 commémos 2€ non-EU). Pause + escalation au user :
il a tranché Option B (canonicaliser en SQLite). Chunk **3.A.0** ajouté
au plan pour bootstrapper la table avant 3.A.

D-20 mis à jour dans decisions.md pour refléter (table `coins` +
`go-task ml:bootstrap-coins` + vue SQL pure désormais possible).

### Chunks livrés

- **3.A.0** Table `coins` SQLite + script bootstrap idempotent
  (`scripts/bootstrap_coins_from_referential.py`) + tasks `ml:bootstrap-coins{,-dry}` +
  warning au boot du Store si vide. Vue `v_ebay_freshness` ajoutée.
  4 tests verts.
- **3.A** Extension `SourceQuery.target_eurio_ids: tuple[str, ...]`
  (pluriel, mutually exclusive avec singular). Boucle dans
  `steps/discover.py::_iter_subqueries` : 1 batch query → N sub-queries
  mono-eurio_id (l'adapter ne voit jamais le batching). Signature
  query stable indépendamment de l'ordre. Colonnes
  `source_images.is_lot_suspected` et `review_queue.kind` ajoutées.
  4 tests dédiés.
- **3.B** Module `ml/sources/ebay/` complet : `queries.py`
  (build_query depuis SQLite), `filters.py` (accept_listing,
  is_lot_suspected D-26 niveau 1, listing_row), `adapter.py`
  (EbayAdapter implémente SourceAdapter), `__init__.py`, `README.md`.
  Convention `source_ref = ebay_<itemId>_img<N>` (1 row par image).
  Fallback gracieux si `item/{id}` plante. **24 tests httpx-mocked verts**.
- **3.C** API : `GET /sources/ebay/quota-status`, `GET /sources/ebay/freshness`,
  pre-flight check 409 dans `POST /sources/ebay/runs` (D-27, marge 30%).
  `EbayAdapter` chargé dans `_load_adapter` via env vars + token cache.
  8 tests d'intégration FastAPI verts.
- **3.D** CLI : `--target-eurio-ids` + `--batch N` (default 10) +
  `_resolve_ebay_targets()` (lit `v_ebay_freshness`) + pre-flight
  print + tasks `ml:src:ebay:{run,dry,limit,status}`. Sub-cmd
  `status_cli.py` pour le snapshot quota/freshness. **Adapter
  `dry_run` flag** pour skip `item/{id}` en preview (1 call/eurio_id
  au lieu de ~10) — propagé via CLI/API.
- **3.E** Front : `EbayPilotPanel.vue` (KPI quota + buckets + slider
  batch + estimation pré-run + preview prochaines pièces +
  warning insufficient quota). Composables étendus
  (`fetchEbayQuotaStatus`, `fetchEbayFreshness`,
  `triggerSourceRun({target_eurio_ids})`). Injecté dans
  `SourceDetailPage.vue` avec `v-if="id === 'ebay'"`. Toast 409
  affiche `max_safe_batch`. Typecheck `features/sources/` clean
  (les erreurs `features/sets|audit|lab` sont pré-existantes hors scope).
- **3.F** `steps/resolve.py` : pending_quote créée pour single
  non-lot avec prix > 0 ET `image_index == 0` (1 quote par listing,
  pas par image). `steps/enqueue.py` : `kind = 'lot'` si
  `is_lot_suspected` OU si N crops > 1 sur la source_image
  (D-26 niveaux 1+2). 9 tests verts.
- **3.G** Smoke run réel sur `it-2017-2eur-2000-years-since-the-death-of-titus-livius`
  (commémo ambiguë → peu de résultats → cheap). Pipeline bout-en-bout :
  - 3 raws JPEG 1500×1500 téléchargés depuis `ebayimg.com`
  - 3 crops PNG 224×224 produits (normalize_snap, **0 errors**)
  - 2 pending_quotes (10.74€ + 10.95€ EUR)
  - 3 review_queue rows en `kind='single'`
  - **Re-run = 0 nouveau row, 0 fichier téléchargé** (idempotence
    parfaite des 5 couches dédup C1→C5)

### Bilan tests

```
tests/test_sources_base.py        8/8
tests/test_orchestrator.py       12/12   (8 existants + 4 nouveaux 3.A)
tests/test_bootstrap_coins.py     4/4   (3.A.0)
tests/test_ebay_adapter.py       24/24  (3.B, httpx-mocked)
tests/test_ebay_api.py            8/8   (3.C, FastAPI integration)
tests/test_resolve_lot_quote.py   9/9   (3.F)
                                ────
                                 65/65 ✅
```

(le 66e ‘test_query_signature_is_stable’ déjà présent avant 3.A reste vert)

### Décisions techniques en cours de session

- **Storage_path eBay contient des `|`** (du format itemId `v1|336075712778|0`).
  Pas un bug — ces caractères sont valides en POSIX, juste salissant
  visuellement dans les outputs sqlite3 default-pipe-separator. Aucun
  impact fonctionnel.
- **`source_runs.n_calls` sous-évalue les calls réels** : le compteur
  bump une fois par sub-query dans `discover.py` mais l'adapter fait
  N calls par sub-query (1 search + N item/{id}). Le vrai compteur quota
  est `api_call_log` (lu par `/sources/ebay/quota-status`). Acceptable
  V1, à raffiner si besoin (V1.5).
- **Image index canonicality pour pending_quote** : 1 listing = N
  source_images (1 par photo). On insère la pending_quote uniquement
  pour `image_index == 0` (extracted from `raw_payload`) — sinon on
  créerait N doublons de la même quote.
- **Dry-run cheap** : EbayAdapter.dry_run flag skip `item/{id}` →
  1 call/eurio_id au lieu de ~10. Fix livré en 3.D quand le first
  dry-run a consommé 33 calls inutilement.

### Fichiers ajoutés / modifiés

```
docs/sources-refacto/
  ebay-kickoff.md                NEW (3.A.0 + 3.A § corrigés post-discovery coins)
  decisions.md                   D-19 → D-27 (D-20 corrigé : table coins SQLite)
  progress.md                    cette entrée

ml/state/
  schema.sql                     +coins table, +v_ebay_freshness view
  store.py                       +ALTERs (is_lot_suspected, kind), +warning si coins vide

ml/scripts/
  bootstrap_coins_from_referential.py   NEW (idempotent INSERT OR REPLACE)

ml/sources/_base/
  adapter.py                     +target_eurio_ids tuple, +is_lot_suspected
  query_sig.py                   stable hash sur sorted(target_eurio_ids)
  dedup.py                       SourceImageRow.is_lot_suspected propagé
  steps/discover.py              _iter_subqueries (1 sub-query par eurio_id)
  steps/persist.py               propage is_lot_suspected
  steps/resolve.py               pending_quote pour single canonical
  steps/enqueue.py               kind='lot' (titre OU n_crops>1)

ml/sources/ebay/                 NEW (1 module entier)
  __init__.py · adapter.py · queries.py · filters.py · status_cli.py · README.md

ml/api/sources_routes.py         +EbayQuotaStatus + EbayFreshness + pre-flight 409
ml/sources/cli.py                +ebay loader + freshness queue + pre-flight print
ml/Taskfile.yml                  +bootstrap-coins{,-dry} + src:ebay:{run,dry,limit,status}

admin/packages/web/src/features/sources/
  composables/useSourceDetail.ts +fetchEbayQuotaStatus, fetchEbayFreshness, target_eurio_ids
  components/EbayPilotPanel.vue  NEW (KPI + freshness + slider + estimation)
  pages/SourceDetailPage.vue     intégration v-if="id === 'ebay'" + toast 409 max_safe_batch

ml/tests/
  test_bootstrap_coins.py        NEW (4)
  test_ebay_adapter.py           NEW (24)
  test_ebay_api.py               NEW (8)
  test_resolve_lot_quote.py      NEW (9)
  test_orchestrator.py           +4 tests target_eurio_ids
```

### Reste à faire (V1.5+, parking lot)

Documenté dans `ebay-kickoff.md` §"Parking lot" :
- Lot review page (`/review/lots`) — UI dédiée à la décomposition
  des coffrets, pré-requis 200+ rows kind='lot' accumulées
- Auto-name calibré sur vraies données (D-18 différé)
- Vue `v_coin_market_quotes_weighted` (velocity weighting post-hoc, D-24)
- Pagination > 50 (V2)
- `item/{id}` paresseux si `additionalImages` déjà HD dans summary
- Scheduled re-fetch via `/schedule` agent
- `v_enrichment_freshness` cross-source (multi-source pivot)
- Suppression du legacy `ml/market/scrape_ebay.py` (chunk séparé après audit V1.5)

### Comment reprendre dans une nouvelle session

```bash
cd ml && .venv/bin/python -m pytest \
  tests/test_sources_base.py tests/test_orchestrator.py \
  tests/test_bootstrap_coins.py tests/test_ebay_adapter.py \
  tests/test_ebay_api.py tests/test_resolve_lot_quote.py -q
# → 65 passed

# Bootstrap canonical coins (1× par machine ou après update du JSON)
go-task ml:bootstrap-coins

# Status quota + freshness
go-task ml:src:ebay:status

# Lance un batch eBay réel (default 10 prochains de la freshness queue)
go-task ml:src:ebay:run

# Ou dry-run 5 next (cheap, 1 call/eurio_id)
go-task ml:src:ebay:dry -- --batch 5
```

Ou via le front : `cd admin/packages/web && pnpm dev` →
`/sources/ebay` → panneau pilot → slider 1-30 → bouton Run/Dry.
