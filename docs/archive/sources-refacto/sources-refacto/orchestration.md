# Orchestration

> Architecture en 4 couches : qui appelle quoi, où ça tourne, comment
> l'admin observe et agit. Document figé après alignement
> 2026-05-02.
>
> **Pré-requis** : avoir lu `decisions.md` et `schema.md`.

## Principes

- **CLI-driven en V1** : tout fetch passe par `go-task ml:src:<source>:run`.
  L'admin n'a pas de bouton "lancer un run" en V1 (read-only +
  review queue uniquement). Triggers HTTP repoussés en V2.
- **Étape-par-étape** : un run exécute 6 étapes séquentielles, chacune
  idempotente. On peut couper et reprendre.
- **DB SQLite locale** = source de vérité unique. La Vue lit via
  l'API FastAPI, jamais directement.
- **Aucun état partagé** entre Mac et PC (D-06). Chaque machine est
  autonome.

## Les 4 couches

```
┌────────────────────────────────────────────────────────────────────┐
│  Couche 4 — Admin Vue (read + actions humaines)                    │
│   /sources/*           /review                /coins/*              │
│   (status, runs)       (queue + decide)       (sélecteur)           │
└──────────┬─────────────────────────────────────┬───────────────────┘
           │ HTTP GET/POST                        │
           ▼                                       │
┌────────────────────────────────────────────────────────────────────┐
│  Couche 3 — ML FastAPI (`ml/api/`)                                 │
│   sources_routes  review_routes  coins_routes  resolution_routes    │
│   (read-only V1, triggers en V2)                                    │
└──────────┬─────────────────────────────────────┬───────────────────┘
           │ lit/écrit                            │ lit/écrit
           ▼                                       ▼
┌────────────────────────────────────────────────────────────────────┐
│  Couche 2 — SQLite (`ml/state/training.db`) — source de vérité     │
│   source_images · image_assets · coin_market_quotes · pending_quotes│
│   review_queue · source_runs · api_call_log                         │
└──────────▲─────────────────────────────────────────────────────────┘
           │ écrit
           │
┌────────────────────────────────────────────────────────────────────┐
│  Couche 1 — Workers fetch + résolution (CLI go-task)               │
│                                                                    │
│   ml/sources/<source>/ → fetch.run(ctx, filters)                  │
│     └─ orchestrator.py : 6 étapes pipelined                       │
│                                                                    │
│   ml/resolution/ → name_match · phash_propagate · dino_suggest     │
│   ml/detection/ → yolo + hough → crops                             │
└────────────────────────────────────────────────────────────────────┘
```

**Règle d'or** : la couche 4 ne parle jamais directement à la couche 1.

## Pipeline d'un run en 6 étapes

L'orchestrateur exécute pour chaque source les **6 mêmes étapes**, dans
l'ordre. Étape-par-étape (toute l'étape 1 d'abord, puis toute la 2,
etc.) plutôt que monolithique (1→6 par listing) — ça permet de
batcher YOLO en étape 4 et de couper/reprendre sans incohérence.

```
┌─ run_logger.start(source, kind, filters) → run_id
│
├─ Étape 1 — Discover            (API/scrape)
│    Pour chaque target eurio_id (ou query libre) :
│      → quota_guard.check_and_decrement()
│      → http.get(query) → list[listing_summary]
│
├─ Étape 2 — Persist raw         (DB)
│    Pour chaque listing :
│      → source_images.upsert((source, source_ref))
│      → si listing.has_price && listing semble mono-pièce
│          → pending_quotes.insert()
│      → si listing est un lot (multi-coin probable)
│          → on stocke listing.price dans source_images.listing_price
│            pour audit, mais pas de pending_quote (D-03 + D-15)
│
├─ Étape 3 — Download images     (IO, parallélisable)
│    Pour chaque source_image sans fichier local :
│      → http.download(image_url)
│        → ml/datasets/sources/<source>/<source_ref>/raw_<hash>.jpg
│      → source_images.update(storage_path, sha256, dimensions)
│
├─ Étape 4 — Detect & crop       (CPU, batch friendly)
│    Pour chaque source_image fraîchement téléchargé :
│      → detection.detect_coins(raw_path) → list[bbox]
│      → pour chaque bbox :
│          → image_assets.upsert((source_image_id, crop_index))
│          → storage.write_crop()
│          → status = 'pending_match'
│
├─ Étape 5 — Resolve auto        (matching cheap)
│    Pour chaque crop en 'pending_match' :
│      → name_match.resolve(crop, source_image.listing_metadata)
│         → si confidence ≥ 0.85 → status='auto_name', eurio_id assigné
│         → sinon → status='needs_review', candidate_eurio_ids=top5
│      → phash.try_propagate(crop) → si pHash match déjà résolu
│         → status='auto_phash', eurio_id propagé
│
├─ Étape 6 — Enqueue review      (DB)
│    Pour chaque crop en 'needs_review' :
│      → review_queue.insert(image_asset_id, priority=calc(...), candidates)
│
└─ run_logger.end(run_id, status='success'|'partial'|'failed', counters)
```

### Pourquoi étape-par-étape

1. **Idempotence par étape** : chaque étape upsert. On peut crash au
   milieu de la 4 et la rerun sans dupliquer rien.
2. **Batch CPU** : étape 4 (YOLO) bénéficie d'un seul warmup pour
   500 images vs 500 warmups si on monolithisait.
3. **Découplage futur** : chaque étape peut devenir une commande
   séparée (`ml:detect:pending`, `ml:resolve:rerun-name`,
   `ml:resolve:rerun-phash`, `ml:queue:enqueue-pending`) sans
   réécrire l'orchestrateur.
4. **Reprise de run** : `run_logger` connaît la dernière étape
   complète, on peut reprendre proprement.

### Concurrence

- SQLite WAL : 1 writer + N readers. Compatible avec un run en
  arrière-plan + admin qui review en même temps.
- **Anti-double-run** : `run_logger.start()` refuse de démarrer si
  une row `running` existe déjà pour la même source (sauf `--force`).
- Pas de coordination cross-machine (D-06).

### Seuils de résolution (V1, à ajuster empiriquement)

| Confidence `auto_name` | Action |
|---|---|
| ≥ 0.85 | auto-promote `auto_name`, eurio_id assigné |
| ∈ [0.55, 0.85[ | enqueue review avec top-5 du name_match |
| < 0.55 | enqueue review sans top-5 garanti (ou top-5 best-effort) |

Ces valeurs sont arbitraires en V1. Calibration à faire sur un
échantillon de 100 listings labellisés à la main après quelques runs.

## Modules et responsabilités

```
ml/sources/
├── _base/
│   ├── __init__.py
│   ├── orchestrator.py         ← pipeline 6 étapes générique
│   ├── run_logger.py
│   ├── quota_guard.py          ← wrapper SQLite api_call_log
│   ├── dedup.py                ← upsert helpers
│   ├── storage.py              ← write raw / write crop / chemins
│   ├── http.py                 ← session retry/backoff/UA
│   ├── license_map.py
│   ├── condition_map.py
│   └── sources_registry.py
│
├── ebay/
│   ├── __init__.py
│   ├── fetch.py                ← discover + extract listing eBay
│   ├── filters.py              ← EbayFilters dataclass
│   ├── cli.py                  ← entrypoint go-task
│   └── README.md
└── …

ml/detection/                   ← factorisation depuis ml/scan/
├── __init__.py
├── detector.py                 ← détecte 1..N pièces dans une image
└── crop.py

ml/resolution/
├── __init__.py
├── name_match.py
├── phash_propagate.py
└── dino_suggest.py             ← (futur) top-5 candidates pour review

ml/review_queue/
├── __init__.py
└── enqueue.py                  ← calcul priority + candidates
```

**Principe** : `ml/sources/<source>/fetch.py` ne contient **que** ce
qui est spécifique à la source. Tout le reste — détection, résolution,
dédup, persistence, queue — est en module générique.

## API surface (V1)

```
# Lecture sources
GET  /sources/status                          # cards (étendu)
GET  /sources/:id                             # header détail
GET  /sources/:id/runs?limit=50               # source_runs filtré
GET  /sources/:id/runs/:run_id                # 1 run + log

# Lecture data ingérée
GET  /sources/:id/raws?status=...&page=...    # source_images
GET  /sources/:id/crops?status=...&page=...   # image_assets
GET  /sources/:id/quotes?page=...             # coin_market_quotes

# Review queue
GET  /review-queue?status=open&limit=20&order=priority
GET  /review-queue/:id                        # crop + raw + top-5 + context
POST /review-queue/:id/decide                 # body: eurio_id, face, variant, notes
POST /review-queue/:id/skip                   # priority +50, status=open
POST /review-queue/:id/reject

# Sélecteur libre review
GET  /coins/search?country=BE&denomination=2&year=&limit=24
```

**Pas de POST /sources/:id/run en V1.** CLI uniquement.

## Statut "live" d'un run en cours

Polling depuis l'admin :

```
GET /sources/:id/runs/:run_id  toutes les 2s
→ retourne {status: 'running', n_calls: 234, n_raws_added: 12, ... step: 'detect'}
```

Pas de WebSocket en V1 — le polling 2s est suffisant pour l'usage.

## Séquence review humaine

```
[user clique sur /review]
  → Vue.fetch GET /review-queue?status=open
  → API SELECT * FROM review_queue WHERE status='open' ORDER BY priority LIMIT 20

[Vue détail]
  → GET /review-queue/:id
  → API charge: image_assets + source_images parent + candidate_eurio_ids
  → API charge thumbs des candidats (depuis coins.images.obverse via Supabase)

[user appuie '1']
  → POST /review-queue/:id/decide
       { eurio_id: 'BE-2EUR-2002', face: 'obverse', variant_kind: 'in_hand' }
  → API transaction:
       UPDATE image_assets SET eurio_id=?, resolution_status='manual', resolved_at=now()
       UPDATE review_queue SET status='done', decided_eurio_id=?, decided_at=now()
       SI pending_quotes existe POUR source_image_id ET source_image n_crops=1:
         INSERT coin_market_quotes (source, eurio_id, condition_raw, p50, ...)
         DELETE pending_quotes
       SI pHash propagation possible:
         UPDATE autres image_assets WHERE phash=? AND status='needs_review'
           SET resolution_status='auto_phash', eurio_id=?
  → Vue refresh, passe à row suivante
```

## Évolutions V2+ (hors phase 1)

- **POST `/sources/:id/run`** : trigger un run depuis l'admin (lance
  go-task en subprocess avec lock).
- **WebSocket** pour progress live au lieu de polling 2s.
- **Multi-reviewer** : `assigned_to`, conflits, audit complet.
- **DinoV2 candidates** : worker async qui enrichit
  `candidate_eurio_ids` sur les rows `needs_review` sans top-5.
- **Quality pipeline** : worker async séparé qui score
  `image_assets`, ne participe pas à l'orchestrateur fetch.
