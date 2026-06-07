# Kickoff orchestrateur — Étape 2 sources refacto

> Brief auto-suffisant pour ouvrir une nouvelle session dédiée à
> l'orchestrateur d'ingestion (étape 2 du plan stratégique). À lire
> en premier dans la nouvelle conversation.

## Prompt à coller en début de session

```
J'ouvre une session pour implémenter l'orchestrateur des sources
(étape 2 de la refacto sources). Lis ce fichier en entier :
docs/sources-refacto/orchestrator-kickoff.md

Puis lis dans l'ordre :
  1. docs/sources-refacto/decisions.md (D-13 surtout)
  2. docs/sources-refacto/orchestration.md (architecture 4 couches)
  3. docs/sources-refacto/schema.md (§"Dédup en 5 couches")
  4. docs/sources-refacto/progress.md (dernière entrée — Step 1 livré)
  5. ml/state/schema.sql (lignes 267-fin — tables sources refacto)
  6. ml/state/store.py (la classe Store + _register_phash_udfs)
  7. ml/sources/_base/ (modules existants : sources_registry,
     run_logger, dedup)

On va construire brique par brique. Le user m'arrête entre chaque
chunk pour audit. Ordre proposé :
  - 2.A — Interface SourceAdapter + Orchestrator squelette
  - 2.B — Étapes Discover + Persist (couches 1-2 du dédup)
  - 2.C — Étapes Download + Detect & crop (couches 3-4)
  - 2.D — Étapes Resolve + Enqueue review (couche 5)

Chaque chunk doit être testable en isolation (mock adapter qui
retourne 5 listings fixtures) avant de brancher une vraie source.
```

## État actuel — ce qui est déjà en place

### Schéma DB (Step 1 livré)
- `source_runs` — log d'exécution par run
- `source_images` — raw fichiers (UNIQUE source/source_ref)
- `image_assets` — crops avec `phash`, `resolution_status`, etc.
- `coin_market_quotes` + `pending_quotes`
- `review_queue`
- **`discovery_log`** (nouveau Step 1) — couche 1 dédup
- UDFs Python `hamming()` et `phash_match()` enregistrées via
  `_register_phash_udfs()` dans chaque connexion

### Modules `ml/sources/_base/` (déjà partiellement écrits)
Lire ces fichiers en début de session :
- `sources_registry.py` — `SourceSpec` dataclass + dict `SOURCES`
- `run_logger.py` — context manager `start_run()` avec
  `RunHandle.set_step()`, `bump()`, `end()`, anti-double-run
- `dedup.py` — upserts idempotents pour `source_images`,
  `image_assets`, quotes

**Ce qui manque** : l'orchestrateur lui-même (`orchestrator.py`),
l'interface `SourceAdapter` que chaque source implémente, et les 6
étapes du pipeline.

## Architecture cible (cf. orchestration.md couches 3+4)

```
┌─────────────────────────────────────────────────────────────────┐
│  ml/sources/<source>/                                           │
│    cli.py            entrypoint go-task                         │
│    fetch.py          implémente SourceAdapter                   │
│    filters.py        spec des cohortes ciblées                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  ml/sources/_base/                                              │
│    orchestrator.py   pipeline 6 étapes générique                │
│    adapter.py        interface SourceAdapter (Protocol)         │
│    run_logger.py     ✓ déjà écrit                               │
│    dedup.py          ✓ déjà écrit                               │
│    sources_registry  ✓ déjà écrit                               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tables SQL (Step 1 livré)                                      │
│    source_runs · source_images · image_assets ·                 │
│    discovery_log · coin_market_quotes · pending_quotes ·        │
│    review_queue                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Le pipeline 6 étapes (D-13)

Chaque étape est **idempotente** par upsert. Toute l'étape N termine
avant N+1. L'orchestrateur logge dans `source_runs.current_step`,
incrémente les compteurs `n_*_added`, et met à jour
`discovery_log.pipeline_state` à chaque transition.

| # | Étape | Couches dédup | Output principal |
|---|---|---|---|
| 1 | **Discover** | C1 (`discovery_log`) | `discovery_log` rows + `source_runs.n_discovered` |
| 2 | **Persist raw** | C2 (`source_images.UNIQUE`) | `source_images` rows + `discovery_log.pipeline_state='persisted'` |
| 3 | **Download** | C3 (filesystem) | fichier sur disque + `source_images.storage_path` |
| 4 | **Detect & crop** | C4 (pHash) | `image_assets` rows + `phash` calculé |
| 5 | **Resolve** | C5 (`resolution_status`) | `image_assets.eurio_id` (auto_name) ou `needs_review` |
| 6 | **Enqueue review** | dédup `UNIQUE(image_asset_id)` | `review_queue` rows |

## Découpage brique-par-brique

### 2.A — Interface `SourceAdapter` + `Orchestrator` squelette

**Objectif** : poser le contrat et un orchestrateur qui exécute les 6
étapes sur un *mock adapter* qui retourne des fixtures. Pas de vraie
source. Audit possible : log lisible montrant chaque étape qui passe.

Fichiers créés :
- `ml/sources/_base/adapter.py` — `SourceAdapter(Protocol)` :
  ```python
  class SourceAdapter(Protocol):
      source_id: str

      def discover(self, query: SourceQuery) -> Iterable[DiscoveredItem]: ...
      def download_raw(self, item: DiscoveredItem, dest: Path) -> RawDownloadResult: ...
      # detect / resolve sont génériques, vivent dans _base/
  ```
- `ml/sources/_base/orchestrator.py` — fonction
  `run_pipeline(adapter, query, *, store, dry_run=False)` qui
  exécute les 6 étapes séquentiellement, écrit dans `source_runs`,
  gère les exceptions par étape sans casser tout.
- `ml/sources/_mock/` — adapter de test qui retourne 5 fixtures.
- `ml/tests/test_orchestrator.py` — un test bout-en-bout sur le mock
  adapter, vérifie qu'on a 5 `discovery_log` rows + 5 `source_images`
  + N crops + statuts cohérents.

**Audit attendu** : lancer `pytest tests/test_orchestrator.py -v`
et voir une trace lisible "Discover (5 found) → Persist (5 added) →
Download (5 written) → Detect (12 crops) → Resolve (3 auto / 9 review)
→ Enqueue (9 enqueued)".

### 2.B — Étapes Discover + Persist (couches 1-2 dédup)

**Objectif** : implémenter les 2 premières étapes pour de vrai, avec
le dédup `discovery_log` + `source_images.UNIQUE`. Re-runner le mock
adapter doit donner "0 nouveaux" la 2e fois.

Fichiers créés :
- `ml/sources/_base/steps/discover.py` — boucle sur `adapter.discover()`,
  upsert `discovery_log` avec `query_signature` calculé depuis la
  `SourceQuery`.
- `ml/sources/_base/steps/persist.py` — upsert `source_images` ; passe
  `discovery_log.pipeline_state='persisted'` à la fin.

**Audit attendu** : run mock adapter 2 fois, `source_runs` contient
2 rows distincts mais `source_images` reste à 5 rows. Counter
`n_raws_added` est 5 puis 0.

### 2.C — Étapes Download + Detect & crop (couches 3-4 dédup)

**Objectif** : télécharger les fichiers (avec skip si déjà sur disque)
et croper avec pHash dedup.

Fichiers créés :
- `ml/sources/_base/steps/download.py` — appelle
  `adapter.download_raw()` sauf si `storage_path` existe + fichier
  présent (couche 3).
- `ml/sources/_base/steps/detect_crop.py` — appelle
  `scan.normalize_snap` (réutilisation directe, pas de fallback).
  **Pas de fallback silencieux** : si `normalize_snap` échoue sur une
  image, on log l'erreur explicitement, on marque le `source_image`
  en `detect_error` (nouveau status à ajouter) et on continue les
  autres items. Calcule pHash via `imagehash.phash()` sur le crop
  retourné. Pour chaque crop : check `phash_match()` sur les
  `image_assets` existants ; si match résolu → `auto_phash`.
- `ml/sources/_base/storage.py` — chemins canoniques + écriture
  atomique (déjà mentionné dans la todo phase-1).

**Audit attendu** :
1. Run mock 2 fois → 0 fichier re-téléchargé, 0 crop re-calculé,
   counter `n_crops_added` 0 au 2e run.
2. **Audit visuel** : les 5 crops produits sont écrits dans un dossier
   accessible (`ml/state/sources/_mock/crops/`) pour inspection
   manuelle après le run. Le test imprime les chemins en sortie.

⚠️ Si `scan.normalize_snap` n'est pas importable directement (deps
TFLite, OpenCV, etc.) sans tirer tout `ml/scan/`, on extrait la
fonction `detect_circles_and_normalize()` dans `ml/detection/core.py`
en chunk préliminaire avant 2.C. Pas de duplication de logique.

### 2.D — Étapes Resolve + Enqueue review (couche 5 dédup)

**Objectif** : finaliser le pipeline. **Pas d'auto-name pour V1**
(reco validée) — extraire pays/année/dénom d'un titre eBay est trop
bruité, on auto-namerait des trucs faux. 100% des items vont en
`needs_review`. L'auto-name reviendra en chunk séparé une fois qu'on
a des vraies données pour évaluer la précision.

Fichiers créés :
- `ml/sources/_base/steps/resolve.py` — pour V1 : marque tout en
  `resolution_status='needs_review'`. Le module `ml/resolution/` n'est
  PAS créé maintenant — on attend d'avoir des stats sur des vraies
  données pour décider du seuil d'auto-name.
- `ml/sources/_base/steps/enqueue.py` — insert `review_queue` pour
  les `needs_review`, calcule `priority` selon `review-queue.md` §
  "Priorisation".

**Audit attendu** : la review queue mockée du front affiche les
items du run de test si on flippe le mock côté admin. Les 5 items
fixtures apparaissent tous en `needs_review` (0 auto).

## Décisions à valider en début de session 2.A

Questions ouvertes que je pose en début de session pour ne pas
bloquer :

1. **`SourceAdapter` = Protocol ou ABC ?** Protocol est plus pythonic
   et n'oblige pas l'héritage ; ABC plus explicite. Mon vote :
   Protocol.
2. **`SourceQuery`** : dataclass simple (`country`, `denomination`,
   `year`, `target_eurio_id`) ou ouvert via `kwargs` ?
   Mon vote : dataclass strict, avec un `extra: dict` pour les
   sources qui ont des filtres atypiques (ex: catégorie eBay).
3. **`query_signature`** : `hashlib.sha256(json.dumps(query, sort_keys=True))[:16]`
   ou dérivation lisible style `ebay/2eur/BE/2002` ? Mon vote :
   hash court (stable, robuste aux ajouts de filtres). Lisibilité
   sacrifiée pour la stabilité.
4. **Tests : pytest fixtures partagées ou par fichier ?** Le repo
   utilise déjà `ml/tests/` avec quelques fixtures inline. Suivre
   cette convention.
5. **`ml/detection/` factorisation** : **décidé** — pas de fallback
   silencieux. On réutilise `scan.normalize_snap` directement ; si
   l'import tire trop de deps, on extrait `detect_circles_and_normalize()`
   dans `ml/detection/core.py` en mini-chunk préliminaire. Erreurs
   loggées explicitement, jamais masquées (R0).
6. **Stratégie d'erreur par item** : **décidé** — on continue les
   autres items du run. L'item en erreur est marqué avec un status
   d'erreur explicite (`download_error`, `detect_error`,
   `resolve_error`) et reste reprenable. Le `source_runs` log
   compte les erreurs (`n_errors`) sans faire crasher le run entier.
7. **Auto-name** : **décidé** — pas en V1, tout va en `needs_review`.
8. **Mock fixtures** : 5 obverse.jpg réels du dataset — coins
   `64`, `80`, `88`, `96`, `104` (chemin `ml/datasets/<id>/obverse.jpg`).
   Le mock adapter copie ces fichiers vers le storage pour simuler un
   download.
9. **Dry run + intégration front** : `run_pipeline(..., dry_run=True)`
   exécute Discover seulement, retourne les items qui *seraient*
   traités sans rien écrire. Exposé via :
   - CLI : `go-task ml:src:mock:run -- --dry-run` (documenté dans la
     section Commandes du front sources)
   - Front : bouton "Dry run" à côté de "Run" dans `SourceDetailPage`,
     affiche le diff (items nouveaux vs déjà connus) avant validation.

## Vérifications avant de coder

Lancer ces commandes pour confirmer que l'état attendu est là :

```bash
# Tests phase-1 base déjà écrits passent toujours
cd ml && .venv/bin/python -m pytest tests/test_sources_base.py -q

# Migration JSON déjà tournée (devrait skipper)
.venv/bin/python -m scripts.migrate_sources_runs_to_db --dry-run

# Le schéma a bien la table discovery_log
sqlite3 ml/state/training.db ".schema discovery_log"

# UDFs disponibles (devrait afficher 8)
sqlite3 ml/state/training.db <<'SQL'
.load
SELECT hamming(255, 0);
SQL
```

⚠️ La dernière commande ne marche pas en CLI sqlite3 — les UDFs
Python ne sont enregistrées que via `Store._connection()`. Pour les
tester, passer par un `python3 -c "..."` qui instancie un `Store`.

## Ce qu'on NE fait PAS dans la session 2

- **Vraie source eBay**. Le mock adapter suffit pour valider l'archi.
  eBay = chunk séparé en étape 3 du plan stratégique.
- **API FastAPI**. Les endpoints `/sources/:id/runs` etc. consomment
  ces tables, mais leur câblage est étape 4 du plan.
- **Refacto `ml/detection/`**. Trop gros pour ce chunk. Fallback
  Hough simple en 2.C.
- **Promotion `pending_quote → coin_market_quote`**. Pour V1 cette
  promotion arrive *à la review humaine*, donc le hook vit dans
  l'API review-queue (étape 4), pas dans l'orchestrateur.

## Sortie attendue

Un orchestrateur fonctionnel + testé, capable de tourner sur le mock
adapter de bout en bout (`ml:src:mock:run` task à ajouter, avec
support `--dry-run`). Le test de bout-en-bout doit produire :
- 5 rows `discovery_log` (fixtures coins 64/80/88/96/104)
- 5 rows `source_images`
- 5 rows `image_assets` avec `phash` calculé (1 crop par fixture)
- 0 `auto_name`, 5 `needs_review` (auto-name reporté)
- 5 rows `review_queue`
- Crops écrits dans `ml/state/sources/_mock/crops/` pour audit visuel

Re-runner le test sans cleanup = 0 nouveau row inséré, 0 fichier
téléchargé, 0 crop recalculé. C'est le critère de succès du dédup
en 5 couches.

## Contraintes héritées

- **R0 pas de dette technique** (CLAUDE.md) — construire proprement
  depuis le mock, pas de shortcut.
- **D-13** — pipeline étape-par-étape, jamais monolithique.
- **D-06** — Mac et PC indépendants, aucune sync inter-machine.
  L'orchestrateur n'a pas à gérer la coordination multi-host.
- Pas d'emojis dans le code.
