# Phase 1 — Fondations

> Tables, base modulaire, refacto eBay vers le nouveau contrat,
> review queue minimale.
> **Bloque toutes les phases suivantes.**
>
> ⚠️ Lire `decisions.md` avant tout — les choix structurants
> (eurio_id nullable, split images, SQLite, multi-coin, pHash, review
> queue dès phase 1, anti-leakage) sont actés là.

## Pourquoi cette phase

- Sans tables, rien n'a où atterrir.
- Sans `_base/`, chaque nouveau scraper réinvente la roue.
- eBay est le bon premier candidat (existe déjà, gros gisement
  images).
- **Sans review queue**, les rows non-résolues s'empilent sans
  valeur — on livre la V0 minimale dès phase 1 (D-09).

## Périmètre

### 1.1 Schéma DB (SQLite)

Migration `ml/state/schema_extensions/sources_refacto.sql` qui ajoute
à `ml/state/training.db` :

- `source_images`
- `image_assets`
- `coin_market_quotes`
- `pending_quotes`
- `review_queue`
- `source_runs`

Voir `schema.md` pour le DDL complet. Pas de touch à Supabase
`coins` / `coin_images` / `coin_market_prices` legacy.

### 1.2 Base modulaire `ml/sources/_base/`

À créer :

- `sources_registry.py` — `SourceSpec` listant chaque source
  (id, kind, quota, license, cadence, default_variant_kind).
- `run_logger.py` — context manager qui ouvre/ferme `source_runs`
  (start, bump, end).
- `quota_guard.py` — wrapper sur `ml/api_quota.py` SQLite existant
  (D-05). Pas de fichier JSON.
- `dedup.py` — `upsert_source_image`, `upsert_crop`, `upsert_quote`,
  `try_propagate_phash`.
- `storage.py` — calcule `storage_path`, écrit le fichier seulement
  si nouveau hash.
- `license_map.py` — source → license + redistributable.
- `condition_map.py` — raw → enum normalisée (mapping versionné).
- `http.py` — session requests partagée (UA, retry, backoff).
- `detector.py` — wrapper YOLO+Hough pour cropper un raw → N crops
  (réutilise le pipeline scan, mode CPU acceptable).
- `name_match.py` — algo de résolution `auto_name` v1 :
  - extraction `(country, year, denomination, theme)` depuis
    `listing_title` + `listing_country` + `listing_year`
  - matching contre `coins` filtrés
  - retourne `top_k=5` candidats avec scores
- `phash.py` — calcul perceptual hash + dédup helper.

### 1.3 Refacto eBay vers `ml/sources/ebay/`

- Déplacer `ml/market/ebay_client.py` + `scrape_ebay.py` vers
  `ml/sources/ebay/`.
- Adapter `fetch.run(ctx, EbayFilters)` au nouveau contrat (voir
  `module-contract.md`).
- **Capturer les images** : pour chaque listing, créer une row
  `source_images` + télécharger jusqu'à 3 images (l'imageUrl du
  summary + 2 du `getItem` quand quota le permet, configurable).
  Cf. critique #5 — coût quota explicite documenté dans le module.
- **Détecter et cropper** : YOLO + Hough sur chaque raw → N
  `image_assets` enfants.
- **Tenter `auto_name`** sur chaque crop. Si fail → enqueue review.
- **Quotes** : pour les listings mono-pièce, écrire `pending_quotes`.
  Promu vers `coin_market_quotes` quand l'image_asset est résolu.
  Pour les lots multi-pièces, **pas de quote** (D-03).
- **Conserver l'écriture legacy** dans `coin_market_prices` Supabase
  pendant la transition (flag `--legacy-mirror`), retiré quand
  l'admin lit `coin_market_quotes` (couplé à un sous-bout de phase 4).

### 1.4 Review queue V0

- Endpoints (cf. `review-queue.md` § Version minimale) :
  - `GET /review-queue?status=open&limit=20`
  - `GET /review-queue/:id`
  - `POST /review-queue/:id/decide`
  - `POST /review-queue/:id/reject`
  - `GET /coins/search?country=BE&denomination=2`
- Page Vue `admin/packages/web/src/features/review/ReviewPage.vue` :
  - liste paginée triée `priority`
  - vue détail : crop + top-5 candidats (thumbs Numista) + sélecteur
    libre minimal (pays + dénomination)
  - raccourcis 1-5, Enter, R
- Logique de promotion : sur `decide`, si `pending_quotes` existe
  pour le `source_image_id` ET `n_crops_detected = 1`, créer la row
  `coin_market_quotes` correspondante et delete `pending_quotes`.

### 1.5 Tasks go-task

- Renommer / aliaser :
  - `ml:scrape-ebay` → alias de `ml:src:ebay:run`
  - `ml:scrape-ebay-dry` → alias de `ml:src:ebay:dry`
- Ajouter `ml:src:ebay:status`, `ml:src:ebay:limit`.
- Ajouter `ml:resolve:name --since=...` (re-tenter name-match sur des
  pending).

### 1.6 Migration legacy

- One-shot `ml:migrate:sources-runs-json-to-sqlite` qui rejoue
  `ml/state/sources_runs.json` dans la table `source_runs`. Le
  fichier reste en place jusqu'à validation, puis suppression.
- `.gitignore` étendu (D-06) :
  ```
  ml/state/*.db
  ml/state/*.db-shm
  ml/state/*.db-wal
  ml/datasets/sources/
  ml/state/sources_runs.json
  ml/state/quotas/
  ml/state/price_snapshots/
  ```

### 1.7 Tests

- `tests/sources/_base/test_dedup.py` — ON CONFLICT marche, fichier
  pas réécrit si même hash, pHash propagation OK.
- `tests/sources/_base/test_quota.py` — quota se décrémente, raise
  quand épuisé.
- `tests/sources/_base/test_name_match.py` — fixtures titres typiques
  (FR/EN/DE), vérifie top-5 cohérent + score raisonnable.
- `tests/sources/ebay/test_fetch_smoke.py` — dry run ne touche ni
  DB ni disque.
- `tests/review_queue/test_decide.py` — decide promote `pending_quotes`
  vers `coin_market_quotes` si mono-pièce.

## Out of scope (phase 1)

- Migration Numista, BCE, MdP, LMDLP vers `ml/sources/` (phase 2/3).
- Pipeline qualité photos avancé (phase 3).
- Page détail admin Sources (phase 4).
- Review queue UX évoluée (`review-queue.md` § Évolutions futures).
- DinoV2 cousinage `auto_dino` (futur).

## Ordre d'attaque

1. Migration DB SQLite + .gitignore + tests de la base
2. `_base/` complet avec tests unitaires (dedup, quota, name_match,
   phash, detector wrapper)
3. Refacto eBay, tests smoke
4. Review queue V0 (endpoints + page Vue)
5. Validation manuelle E2E :
   - `go-task ml:src:ebay:limit -- 5` produit 5 source_images +
     ~10-15 image_assets (crops) + quelques quotes ou pendings
   - quelques rows en review queue, je peux les résoudre via la page
     `/review`, les pending quotes sont promues
6. Tag git `sources-refacto-phase1` quand tout vert.
