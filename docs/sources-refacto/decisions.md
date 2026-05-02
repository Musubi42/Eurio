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
