# Vue debug per-listing dans `sources/:id/runs/:run_id`

> Kickoff figé le 2026-05-04. Ce document est le plan d'implémentation, pas un état des lieux vivant.

## Objectif

Permettre de drill-down depuis le tableau agrégé par `eurio_id` (vue actuelle d'un run) vers la liste des **listings individuels** scrapés, afin de **debugger les décisions du pipeline** : pourquoi tel listing a été classé lot, pourquoi tel autre est en review, pourquoi tel download a échoué, etc.

**Non-objectif** : faire de la review ici. La review reste dans `/review`. Cette vue est en lecture seule, orientée debug pipeline.

## Schéma SQLite — additions sur `source_images`

```sql
ALTER TABLE source_images ADD COLUMN download_endpoint    TEXT;     -- string sémantique, ex 'ebay.browse.getItem'
ALTER TABLE source_images ADD COLUMN download_status      TEXT;     -- 'success' | 'failed' | 'skipped'
ALTER TABLE source_images ADD COLUMN download_error       TEXT;
ALTER TABLE source_images ADD COLUMN download_http_status INTEGER;

ALTER TABLE source_images ADD COLUMN crop_status          TEXT;     -- 'success' | 'zero_crops' | 'error' | 'skipped'
ALTER TABLE source_images ADD COLUMN crop_error           TEXT;
ALTER TABLE source_images ADD COLUMN n_crops_detected     INTEGER;

ALTER TABLE source_images ADD COLUMN route_decision       TEXT;     -- 'auto_resolved' | 'review_single' | 'review_lot' | 'rejected' | 'pending'
ALTER TABLE source_images ADD COLUMN route_reason         TEXT;     -- 'is_lot_suspected' | 'multi_coin_photo' | 'single_unmatched' | etc
```

`source_url` (URL listing eBay côté user) et `raw_payload` (jsonb du retour API) existent déjà — on n'y touche pas. L'URL HTTP réelle hit reste dans `raw_payload`, pas dupliquée en colonne.

**Pas de backfill** : les colonnes restent NULL pour les runs passés. On instrumente uniquement les runs futurs.

## Pipeline — qui écrit quoi

| Step | Écrit |
|---|---|
| 1 Discover | (déjà) `is_lot_suspected`, `source_url`, métadonnées listing |
| 2 Persist | rien de nouveau |
| **3 Download** | `download_endpoint`, `download_status`, `download_http_status`, `download_error` |
| **4 Detect_crop** | `crop_status`, `crop_error`, `n_crops_detected` |
| 5 Resolve | rien (les statuts par crop sont déjà sur `image_assets`) |
| **6 Enqueue** | `route_decision`, `route_reason` agrégés par listing |

Règle d'agrégation `route_decision` (un listing = N crops) :
- tous `auto_resolved` → `auto_resolved`
- ≥1 `review_lot` → `review_lot`
- sinon ≥1 `review_single` → `review_single`
- tous `rejected` → `rejected`
- sinon → `pending`

## API

`GET /sources/{slug}/runs/{run_id}/listings?eurio_id=<optional>`

Réponse :
```json
{
  "run_id": "...",
  "listings": [
    {
      "source_image_id": "...",
      "source_ref": "ebay_listing_195832104221",
      "source_url": "https://www.ebay.fr/itm/...",
      "target_eurio_id": "ad-2017-2eur-100-years...",
      "listing_title": "...",
      "listing_country": "FR",
      "listing_year": 2017,
      "listing_price": 12.5,
      "seller_id": "...",
      "is_lot_suspected": true,
      "download": { "endpoint": "ebay.browse.getItem", "status": "success", "http_status": 200, "error": null },
      "crop":     { "status": "success", "n_detected": 3, "error": null },
      "route":    { "decision": "review_lot", "reason": "is_lot_suspected" },
      "crops": [
        { "crop_index": 0, "asset_id": "...", "resolution_status": "needs_review", "kind": "lot", "review_id": "..." }
      ]
    }
  ]
}
```

`crops[]` joint `image_assets` + `review_queue` + `pending_quotes`.

## Frontend

### Routes

- `sources/:id/runs/:run_id` — page actuelle (agrégée par `eurio_id`), inchangée sauf : **lignes cliquables** → vers vue listings filtrée
- `sources/:id/runs/:run_id/listings` (nouveau) — vue listings du run
  - query `?eurio_id=…` pour filtrer (chip removable côté UI)
  - sans param : tous les listings du run

### UX

- Cards verticales (pas tableau), une card par listing.
- Style : `shared/tokens.css` uniquement. Pas de couleurs/spacings hardcodés.
- Chaque card :
  - thumb du raw si `download.status=success`, sinon placeholder erreur
  - titre listing, prix, pays, year, vendeur
  - badges status : `lot suspected`, `download:failed`, `crops:0`, `route:review_lot`, etc, cliquables pour détail (endpoint, error)
  - mini-thumbs des crops avec leur statut individuel (`auto` / `review` / `rejected`)
  - lien sortant vers `source_url`
  - **pas de bouton review** (lecture seule)
- Header : breadcrumb run + chip filtre eurio_id + compteurs (X success, Y failed, Z zero_crops)

Listings sans crop (run avec 0 résultats eBay sur un eurio_id) : hors scope, pas d'entrée dans `source_images`, ne s'affichent pas. Le debug "pourquoi 0 listings" est un autre sujet (search queries).

## Découpage en chunks

Règle "chunk-by-chunk avec audit visuel" : je rends la main entre chaque chunk.

- **Chunk 1 — schema** : migration idempotente des 9 colonnes. Audit : tu inspectes la table.
- **Chunk 2 — instrumentation pipeline** : steps 3, 4, 6 écrivent les colonnes. Audit : tu lances un run et inspectes la DB.
- **Chunk 3 — endpoint API** `/listings` + test manuel. Audit : tu hits l'endpoint.
- **Chunk 4 — vue Vue.js** + clic depuis la page agrégée. Audit visuel dans le navigateur.
