# Décisions actées

> Choix figés au cours de la session 2026-05-02. Toute évolution
> ultérieure doit explicitement requalifier une décision ici, pas la
> contourner ailleurs dans la doc.

## D-01 — Label space = `eurio_id` (pas `design_group_id`)

`eurio_id` est la clé d'ingestion **et** la clé de training. La bascule
vers `design_group` envisagée dans `lab-prod-refacto/` est suspendue
parce qu'elle créait des classes trop lâches (cas Belgique 2 €
Albert II 2002 vs 2008 : même roi, gravure différente, regroupés à
tort).

**Conséquences** :
- `source_images.eurio_id` et `image_assets.eurio_id` référencent
  textuellement `coins.eurio_id`.
- L'index ArcFace est entraîné label = `eurio_id`.
- `design_group` reste dans le schéma pour usage futur, mais n'est
  plus dans la chaîne training/eval.

## D-02 — `eurio_id` est nullable post-fetch jusqu'à résolution

Quand un listing eBay/Catawiki ne matche aucun `eurio_id` par nom,
on **conserve** l'image avec `eurio_id IS NULL` et un statut
explicite. La donnée n'est jamais supprimée automatiquement —
seulement flaggée et envoyée en review queue.

**Pipeline de résolution à 2 niveaux** :

1. **`auto_name`** — match par nom + filtres (pays, année,
   dénomination). Disponible dès phase 1. Auto-promote si confiance
   ≥ seuil haut.
2. **`manual`** — review humaine via la queue admin. **Validation
   finale toujours humaine** pour tout ce qui n'est pas
   `auto_name` ni `auto_phash`.

**DinoV2** *(futur)* n'auto-labellise jamais. Il sert uniquement à
**pré-remplir `candidate_eurio_ids`** dans `review_queue` pour
faciliter le travail du reviewer (top-5 visuellement pertinent).
La row reste en `needs_review` jusqu'à validation humaine.

**Flux non destructif** : si une étape échoue, on n'efface rien.
La row reste avec son statut, et une étape ultérieure (DinoV2 quand
il sera dispo, ou review humaine) peut la promouvoir.

## D-03 — Multi-coin lots : on capture, on splitte, on label

Un listing avec N pièces visibles → 1 row `source_images` + N rows
`image_assets` (une par crop OpenCV/YOLO). Chaque crop suit son
propre cycle de résolution.

Conséquence prix : un listing multi-coin **ne génère pas de quote**
(`coin_market_quotes`) parce que le prix global n'est pas attribuable
par pièce. Quote uniquement si `n_crops_detected = 1`.

## D-04 — Prix et image résolus ensemble

Pour les rows `coin_market_quotes`, **`eurio_id` est NOT NULL**.
Si un listing eBay n'est pas résolu au moment du fetch, son prix est
**stocké en attente** dans `pending_quotes` (pas dans
`coin_market_quotes`) et promu vers `coin_market_quotes` quand la
review humaine résout l'image associée.

Conséquence : le pipeline review humaine résout **image + prix
simultanément** (même UI, même action).

## D-05 — Quotas et runs : SQLite, pas JSON

`ml/state/training.db` (déjà existant) devient la source unique pour :
- Quotas API (`api_call_log` existant + extension pour rate-limit
  scrapes)
- Logs de runs (table `source_runs` SQL, remplace
  `ml/state/sources_runs.json`)
- Tables de la refacto (`source_images`, `image_assets`,
  `coin_market_quotes`, `pending_quotes`, `review_queue`)

`ml/state/sources_runs.json` est déprécié. Migration scriptée
one-shot puis fichier supprimé.

## D-06 — Machines indépendantes, aucun état partagé

- Mac M4 et PC 1080 Ti sont **deux installations totalement
  indépendantes**. Chacune clone le repo, a sa propre SQLite locale,
  ses propres scrapes, ses propres datasets sur disque.
- Pas de sync, pas de merge, pas d'export inter-machine.
- Chacune scrape selon le besoin et entraîne selon ses capacités
  (Mac = petits tests, PC = gros entraînements).
- `.gitignore` strict : tout ce qui est généré localement reste
  local — DB, datasets, snapshots, logs.

## D-07 — Dédup par `pHash` intra-source

Colonne `phash bigint` sur `image_assets`, indexée. Deux images de
la même source (ou de sources différentes) avec même pHash et
`distance_hamming ≤ 4` sont considérées comme identiques.

**Effet bonus** : si une image vient d'être résolue manuellement,
toute nouvelle image avec un pHash identique peut être promue
automatiquement (`resolution_status = 'auto_phash'`) sans repasser
par la review.

## D-08 — Anti-leakage : bench protégé

Le bench (eval set) **n'inclut jamais** de rows avec
`resolution_status='auto_phash'`. Seuls les labels validés humainement
sont admis :
- `numista_canonical` (image de naissance)
- `cohort_capture` (capture humaine via le flow cohortes)
- `manual` (review humaine a posteriori)

Avec D-02 refiné (DinoV2 = aide review, pas auto-label), il n'y a
plus de risque de leakage par le modèle d'embedding. Seul `auto_phash`
reste exclu du bench (propagation algorithmique non validée
humainement, donc à isoler de l'eval).

## D-09 — Review queue dès phase 1 (version minimale)

Une page admin minimaliste mais fonctionnelle est livrée avec phase 1
(table `review_queue` + page Vue avec list + filtres pays/dénomination
+ top-5 candidats + sélecteur libre). Une vision plus aboutie est
documentée dans `review-queue.md` et développée à part.

Sans cette UI, les rows non résolues stagnent sans valeur. Le coût
de la livrer minimale dès phase 1 est inférieur au coût d'opportunité
de la repousser.

## D-10 — `redistributable=false` filtré au training

Filtre explicite dans `prepare_dataset.py` : assertion qui log et
exclut toute row `redistributable=false` lors de la préparation d'un
dataset destiné à un modèle qui pourrait être distribué publiquement.
V1 : tout est `fair_use_research` non distribuable, donc la loop
training reste interne — mais le filtre est codé dès phase 3 pour
éviter une fuite future.

## D-11 — `face='obverse'` par défaut pour le training

Tous les filtres training côté `prepare_dataset.py` excluent
`face != 'obverse'`. Cohérent avec la mémoire feedback "ArcFace ne
s'entraîne QUE sur obverse.jpg".

## D-13 — Pipeline étape-par-étape (pas monolithique)

L'orchestrateur exécute 6 étapes séquentielles : Discover → Persist
raw → Download → Detect & crop → Resolve → Enqueue review. Toute
l'étape N termine avant de passer à N+1.

**Pourquoi** : idempotence par étape (chaque étape upsert),
batch-friendly (YOLO warmup une fois pour 500 images), reprise après
crash, étapes peuvent devenir des commandes séparées plus tard.

Voir `orchestration.md`.

## D-14 — Triggers en CLI uniquement (V1)

Tous les fetches passent par `go-task ml:src:<source>:run` en CLI.
L'admin Vue est read-only + review queue. **Pas de
`POST /sources/:id/run`** en V1.

**Pourquoi** : évite la complexité workers/locks/concurrence en V1.
Triggers HTTP repoussés en V2 quand le pipeline est stable.

## D-15 — Prix d'un lot stocké en audit, jamais promu

Un listing multi-pièces (`n_crops_detected > 1`) ne génère pas de
quote (D-03). Mais le `listing.price` global est conservé dans
`source_images.listing_price` pour audit historique. Il n'est jamais
promu vers `coin_market_quotes`.

## D-12 — Schéma split à deux tables image

- `source_images` : 1 row par fichier physique téléchargé (raw,
  unique par `(source, source_ref)`).
- `image_assets` : 1 row par crop pièce dérivé d'un raw (FK
  `source_image_id`). C'est cette table qui porte `eurio_id`,
  `face`, `quality_score`, etc.

Détails : voir `schema.md`.

## D-16 — Pas de batch review par multi-select manuel

Le batch review **ne se construit jamais à la main** par sélection
d'items consécutifs dans le flow single-item. Raison : en single-item,
le reviewer ne voit qu'un crop à la fois, il ne peut donc pas
*anticiper* la similarité avec les items suivants pour les grouper.

Le batch est **toujours suggéré par la machine**, jamais composé par
l'humain. Deux mécanismes admis (V2+, gated sur backend) :

1. **Cluster pHash** (cf. D-07) — au moment de la décision sur l'item A,
   le backend renvoie la liste des images avec pHash identique
   (Hamming ≤ 4). Une bascule "Appliquer la même décision aux N
   semblables" permet de propager en 1 clic.
2. **Vue grille parallèle** — alternative au single-item. N items
   visibles d'un coup avec multi-select visuel pour les rejects
   massifs sur trash visible. Endpoint batch
   (`POST /review-queue/batch/...`) requis.

V1 livre **uniquement** le single-item. Aucune UI de multi-select
préparatoire (ni checkbox, ni mode "ajouter au batch") — ça induirait
en erreur sur la sémantique du flow.

## D-17 — Pas de fallback silencieux dans `detect_crop`

L'étape 4 du pipeline (`scan.normalize_studio_path`) appelée par
`steps/detect_crop.py` **n'a pas de fallback de récupération**. Si la
détection échoue (ni `contour` ni `hough` ne trouvent un cercle), on :

1. logge l'erreur explicitement (`logger.error` avec `source_ref`,
   `method` final et `debug` du résultat) ;
2. bump `source_runs.n_errors` ;
3. laisse l'item à `discovery_log.pipeline_state='downloaded'` —
   reprocessable sur la prochaine run sans intervention.

**Raison** : un fallback bidon (Hough lâche) qui sort un crop random
pollue silencieusement le training set. Mieux vaut une erreur visible
qu'une donnée pourrie. R0 (pas de dette technique) tranche : on
réutilise `scan.normalize_studio` directement, on n'invente pas une
détection alternative.

## D-18 — Pas d'auto-name en V1

Initialement prévu en `steps/resolve.py` avec un seuil de confiance
≥ 0.85, l'auto-name regex (extraction pays/année/dénom du title eBay
+ lookup `coins`) est **différé**. Tous les crops vont en
`needs_review`.

**Raison** : extraire des features fiables d'un titre eBay est
notoirement bruité ; à 0.85 on auto-namerait régulièrement des trucs
faux, ce qui pollue le training set et oblige un audit manuel
ex-post. Mieux vaut 100 % en review humaine pour V1, puis réintroduire
l'auto-name une fois qu'on a des stats sur de vraies données pour
calibrer un seuil défendable.

**Conséquence** : `n_auto_resolved` ne grimpe que via `auto_phash`
(dédup C4), jamais via `auto_name`, tant que ce chunk n'est pas
re-livré. Le couplage `priority -30 if target_eurio_id` reste actif
(les fetchs ciblés sortent en haut de la queue).

## D-19 — Sources d'enrichissement pilotées par `eurio_id`

Les sources d'enrichissement (eBay, MdP, BCE, LMDLP, Catawiki,
NumisCorner, CGB, Wikipedia) **n'utilisent pas les cohorts**. Leur
seul axe de pilotage est la liste des `eurio_id` du référentiel
canonique (issu de Numista).

**Pourquoi** : la dichotomie "Référentiel canonique" / "Enrichissement"
de la page `/sources` admin reflète la séparation produit. Une cohort
est un concept *training-side* (sélection figée pour entraîner un
modèle, capturer manuellement) ; mélanger les deux confond ingestion
et entraînement.

**Conséquence sur `SourceQuery`** : pour ces sources, `country`,
`year`, `denomination` sont **inertes**. Seul `target_eurio_ids`
(pluriel, ajout 3.A) compte. L'ergonomie front (page `/sources/ebay`)
expose une freshness queue, pas un sélecteur cohort.

## D-20 — Freshness queue en vue SQL pure (V1) — pré-requis : table `coins` SQLite

Le référentiel canonique vit aujourd'hui dans `ml/datasets/eurio_referential.json`
(2628 entrées dont 466 commémos 2€ non-EU). Pour rendre une **vraie vue SQL**
possible, on canonicalise le référentiel dans une table SQLite `coins` :

```sql
CREATE TABLE coins (
  eurio_id          TEXT PRIMARY KEY,
  country           TEXT NOT NULL,         -- ISO2
  country_name      TEXT,
  year              INTEGER NOT NULL,
  face_value        REAL NOT NULL,
  is_commemorative  INTEGER NOT NULL DEFAULT 0,
  theme             TEXT,
  numista_id        INTEGER,
  raw_payload_json  TEXT,                  -- entrée JSON complète pour audit
  imported_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Bootstrap explicite via **`go-task ml:bootstrap-coins`** (pas auto au boot du
Store : éviter "la DB se modifie toute seule"). Le script lit
`eurio_referential.json` et fait `INSERT OR REPLACE` par `eurio_id`. Idempotent.
Le `Store._bootstrap()` vérifie `SELECT count(*) FROM coins` et logge un warning
si vide (pas un raise — l'orchestrateur peut tourner sur du mock sans le
référentiel canonique chargé).

Vue freshness :

```sql
CREATE VIEW v_ebay_freshness AS
SELECT
  c.eurio_id,
  c.country,
  c.year,
  MAX(si.fetched_at) AS last_enriched_at,
  COUNT(DISTINCT si.id) AS n_images,
  COUNT(DISTINCT ia.id) AS n_crops
FROM coins c
LEFT JOIN source_images si
  ON si.target_eurio_id = c.eurio_id AND si.source = 'ebay'
LEFT JOIN image_assets ia ON ia.source_image_id = si.id
WHERE c.face_value = 2.0 AND c.is_commemorative = 1 AND c.country != 'eu'
GROUP BY c.eurio_id;
```

`ORDER BY last_enriched_at ASC NULLS FIRST` est appliqué au `SELECT` qui
consomme la vue, pas dans la vue elle-même (compat SQLite).

**Pourquoi** : O(N) sur ~500 commemos = négligeable. La table `coins`
canonicalise une donnée déjà canonique mais qui vivait en JSON ;
sans elle, chaque consommateur rechargeait le JSON en RAM (11+ modules
dans le repo). Bénéfice cross-cutting au-delà d'eBay.

**Limite admise** : si on monte à 10k+ eurio_ids, la vue devient
lente, on bascule sur une table matérialisée
`source_enrichment_state(source, eurio_id, last_enriched_at, n_*)`.

## D-21 — 1 run = 1 batch de N eurio_ids (default 10)

Un run eBay traite un *batch* de N eurio_ids ; `source_runs.filters_json`
archive la liste exacte. Default `N = 10`, configurable via
`--batch` CLI ou slider front (range 5-30).

**Pourquoi 10** : compromis entre granularité (audit facile dans
`source_runs`), durée (~1 min visible dans le live counter), et risque
de blast radius (si fail mid-batch, on perd au pire 9 eurio_ids
partiellement fetchés — récupérables par idempotence).

**Pourquoi pas plus** : 50 eurio_ids × ~10 images chacun × ~5 secondes
download = ~40 min. Trop long pour un run interactif, et risque
"comportement spam" côté CDN ebayimg.

## D-22 — Tout télécharger en HD

Pour chaque listing eBay accepté, on récupère **toutes les images
disponibles en HD** :
- 1 call `item/{id}?fieldgroups=PRODUCT` pour avoir `image.imageUrl`
  + `additionalImages[*].imageUrl` en pleine résolution
- N downloads CDN ebayimg (hors quota Browse, gratuits)

**Pourquoi** : les images sont le gisement training. Filtrer en V1
serait prématuré ; on stocke tout, le filtre qualité (quality_score
+ training_eligible) opère en aval.

**Coût** : multiplie par ~7 le quota par eurio_id vs legacy
(1 search + 1 item/{id} + parfois 1 group expansion = ~3 calls/eurio
en moyenne empirique attendue). Estimation pour batch de 10 : ~30 calls.

## D-23 — Pagination `limit=50` no-paginate (V1)

Chaque search eBay capture les 50 premiers résultats triés par
`bestMatch`. Pas de pagination. Si `total > 50`, on logge le `total`
dans `source_runs.filters_json` pour audit ("on a vu 47 sur 132").

**Pourquoi** : paginer pousse le coût à `(total/50) × calls`, on n'a
pas le quota. Les 50 premiers résultats `bestMatch` couvrent les cas
courants (commémos populaires).

## D-24 — Velocity weighting → vue SQL post-hoc

Le legacy `scrape_ebay.py` calculait P25/P50/P75 pondérés au moment
du fetch (`listing_weight = log(1 + sales/year) × seller_trust`).
Le nouveau flow stocke 1 row brute par listing dans `coin_market_quotes`
(price + sold_count + seller_id + seller_fb_pct + listed_at + fetched_at)
et calcule les percentiles dans une vue SQL `v_coin_market_quotes_weighted`
à la lecture.

**Pourquoi** : schéma de pondération évolutif sans re-scraper.
Granularité maximale conservée. Cohérent avec D-15 et la décision
"max granularité" du user.

**Statut V1** : la vue n'est PAS livrée en V1 (parking lot). On stocke
brut, le consommateur (admin/app) calcule sa propre agrégation en
attendant.

## D-25 — Quota stop = run partial, recovery par idempotence

Si `EbayClient.QuotaTracker` lève `QuotaExhausted` au milieu d'un
batch, l'orchestrateur :
1. attrape l'exception, marque le run `status='partial'`,
   `error_summary='quota_exhausted_mid_batch'`
2. ne nettoie rien — les rows partielles restent en place

Le lendemain (quota reset), un nouveau batch lit la freshness queue,
les eurio_ids partiellement fetchés sont en tête (`MAX(fetched_at)`
peu avancé), discover() re-yield les listings, les 5 couches de dédup
(C1-C5 prouvées en session 2026-05-03) skippent ce qui existe et
fetchent uniquement le manquant.

**Pas de SAVEPOINT, pas de rollback explicite.** L'idempotence du
pipeline suffit.

## D-26 — Lot detection à 2 niveaux

Un listing eBay peut vendre 1 ou N pièces. Le legacy résolvait le
problème par rejet pur (regex `lot|coffret|série|rouleau` →
`accept_listing` retourne False). Pour le nouveau flow on garde la
data — c'est un gisement training — mais on la route correctement.

**Niveau 1 — Heuristique titre** : `is_lot_suspected(title) -> bool`
basée sur regex `lot|coffret|série\b|collection complète|rouleau|set\b`.
Le résultat est stocké dans `source_images.is_lot_suspected` (nouvelle
colonne, default `false`).

**Niveau 2 — Détection par image** : `detect_crop` produit N crops
par source_image. Si N > 1 sur une image donnée, **cette image
spécifique** bascule en review `kind='lot'` (pas tout le listing —
les autres images du même listing avec N=1 restent en review normale).

**Quote eligibility** : `is_lot_suspected = false` ⇒ pending_quote
créée pour le listing (1 prix attribuable à `target_eurio_id`).
`is_lot_suspected = true` ⇒ pas de pending_quote (prix coffret non
décomposable).

**Routage review** : la table `review_queue.kind text default 'single'`
(nouvelle colonne) prend `'single'` ou `'lot'`. La page `/review`
existante affiche les `single` ; une page `/review/lots` dédiée
(parking lot V1.5) affichera les `lot`.

## D-27 — Pre-flight quota check avant batch

`POST /sources/ebay/runs` exécute un check **avant** de spawn le thread :

```
estimate = avg_calls_per_eurio_id_last_5_runs × len(target_eurio_ids)
remaining = 5000 - api_call_log.count_today('ebay')
if remaining < estimate × 1.3:   # marge sécurité 30%
    return 409 { error: "quota_insufficient",
                 estimate, remaining,
                 max_safe_batch: floor(remaining / avg / 1.3) }
```

Bootstrap (avant 3 runs eBay terminés en historique) : `avg = 7`
hardcodé.

**Pourquoi** : impossible de fail un batch *par épuisement quota*
en cours de route. Le user voit côté front la décision (refuse +
suggestion `max_safe_batch`) avant de déclencher.

**Conséquence** : les fails restants en cours de batch sont uniquement
HTTP 5xx eBay / timeout réseau / listing pourri — gérés par
`n_errors` non bloquant (continuer les autres items).
