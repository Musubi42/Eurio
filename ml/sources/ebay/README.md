# Source eBay

Adapter eBay pour l'orchestrateur d'ingestion (D-19 → D-27).

## Vue d'ensemble

eBay est une source d'**enrichissement** : pour chaque `eurio_id` du
référentiel canonique (table `coins`), on récupère les images HD et
les prix actifs des annonces eBay FR correspondantes. Pas de
découverte — on n'invente jamais de nouveau `eurio_id`.

Voir `docs/sources-refacto/ebay-kickoff.md` pour la conception complète.

## Architecture

```
adapter.py    EbayAdapter (implémente SourceAdapter)
  ↓
queries.py    build_query() depuis la table coins SQLite
filters.py    accept_listing + is_lot_suspected (D-26)
  ↓
ml/market/ebay_client.py   client OAuth2 + tracker quota
```

## API utilisée

- **Browse API** Marketplace `EBAY_FR`, scope `api_scope`
  - `item_summary/search` — recherche listings actifs (1 call)
  - `item/{id}?fieldgroups=PRODUCT` — détail HD multi-image (D-22)
  - `item/get_items_by_item_group` — variations multi-année

Quota : **5000 calls/jour** (App Growth limit). Tracké dans
`api_call_log` SQLite via `EbayClient.QuotaTracker`.

## License & ToS

- Images : license `fair_use_research`, `redistributable=false`
  (D-10 — filtre training côté `prepare_dataset.py`)
- Pas de redistribution publique des images
- Respect du quota Browse API (5000/jour) — pas de bypass

## Lot detection (D-26)

Niveau 1 — heuristique titre (`is_lot_suspected`) :
- match sur `lot|coffret|série\b|collection\s*complète|rouleau|set\s+of|set\b`
- flag stocké dans `source_images.is_lot_suspected`

Niveau 2 — par image (n_crops > 1) : géré côté `steps/detect_crop.py` →
basule `review_queue.kind = 'lot'` pour cette image-là.

Quote eligibility : `is_lot_suspected = false` ⇒ `pending_quote` créée
au resolve. `true` ⇒ pas de quote (prix coffret non décomposable).

## Convention `source_ref`

Une listing eBay avec N images génère N rows `source_images` avec
`source_ref` :

```
ebay_<itemId>_img0
ebay_<itemId>_img1
...
```

Chaque row a son propre fichier raw, son propre `image_assets` crop.
Les métadonnées listing (title, price, …) sont dupliquées sur toutes
les rows d'une même listing — assumé.

## Filtres anti-bruit

Rejet *avant* yield (économise les `item/{id}` calls) :
- `NOISE_PATTERNS` : proof, fautée, métaux précieux, colorisée
- prix < 0.8 × face_value → `below_face`
- prix > 500 × face_value → `above_extreme`
- devise ≠ EUR → `non_eur`

## Quirks observés

- Aspect `Année` souvent rempli, parfois `Year` (anglo-saxon) — on
  utilise les deux variantes dans l'aspect_filter via le format
  `Année:{2015}` (eBay normalise par language).
- `localizedAspects['Condition']` parfois absent ; on a un fallback
  vers `aspects['État']`.
- Vendeurs pros uploadent souvent 4-12 photos (recto/verso/profil HD).
  Vendeurs particuliers : 1-3 photos basse-déf.
- Pages de variation multi-année (`primaryItemGroup.itemGroupId`)
  consomment 1 call supplémentaire chacune. On cap à top-2.

## Setup

Variables d'env requises (cf. `.envrc`) :

```
EBAY_CLIENT_ID=...
EBAY_CLIENT_SECRET=...
```

Token OAuth2 caché sur disque (`ml/.ebay_token_cache.json`, TTL ~2h).

## Référentiel pré-requis

```bash
go-task ml:bootstrap-coins
sqlite3 ml/state/training.db "SELECT count(*) FROM coins WHERE face_value=2.0 AND is_commemorative=1 AND country!='eu'"
# → 466
```

## Tests

```bash
.venv/bin/python -m pytest tests/test_ebay_adapter.py -v
```

Tests `httpx`-mocked, n'appellent jamais l'API réelle.
