# Refacto ML — vision

> Dossier de cadrage pour un **chantier futur** : rationaliser `ml/` en services cohérents.
> **Discussion ouverte** — rien n'est tranché. Voir [`kickoff.md`](./kickoff.md) pour démarrer une session.
> Créé 2026-06-07.

## Le problème

`ml/` est devenu un fourre-tout qui mélange des responsabilités très différentes :

- **scrap** (sources eBay/BCE/LMDLP/JO/Numista, orchestrateur, pipeline 6 étapes)
- **crop / détection** (Hough, YOLO, bbox refine, normalize_snap, census)
- **augmentation** (recipes, bake-on-disk)
- **training** (ArcFace, DINOv2 foundation, embeddings, compute)
- **review / référentiel** (review_queue, lot-review, auto_validate, fix-proposals)
- **API** (FastAPI `ml/serving/` qui sert tout l'admin + déclenche les jobs)

Tout cohabite dans un seul process FastAPI + un paquet de scripts. Pas de frontières de service
claires, du couplage fort (cf. graphify : `Store` = god node à 176 edges), des responsabilités qui
se chevauchent. **Ça devient ingérable.**

## La douleur concrète qui déclenche le chantier

> Quand je code le back-end ML et que je **sauvegarde un fichier**, l'API FastAPI **hot-reload** →
> **les jobs en cours s'annulent** (un scrape, un crop, un training qui tournait est tué).

**Exigence n°1 : l'API doit pouvoir redémarrer sans tuer les jobs en cours.**
Le travail de fond (scrape/crop/train) doit survivre à un reload du serveur de dev.

## Objectif

Rationaliser `ml/` en **services / unités cohérents**, avec une frontière nette entre :
- le **serving** (API mince, stateless, rechargeable à volonté),
- le **travail de fond** (jobs longs, isolés du cycle de vie de l'API),
- les **domaines** (scrap, crop, augmentation, training, review) bien séparés.

« En faire une API » est une formulation — la solution peut être autre (workers + queue, services
dockerisés, etc.). **C'est précisément ce qu'on veut discuter.**

## Pistes de solution à débattre (non tranchées)

1. **Job runner persistant** — généraliser le pattern **déjà adopté** pour le recrop cohorte
   (subprocess détaché qui possède son entrée `cohort_jobs`, reaper par `pid`). Une table `jobs` +
   un worker daemon qui poll, découplé de l'API. L'API ne fait que *enqueue* et *lire le statut*.
   → règle directement l'exigence n°1.
2. **Task queue** dédiée (Dramatiq / RQ / Celery + broker) vs. le job-runner maison ci-dessus
   (plus simple, zéro dépendance broker, cohérent avec la doctrine zero-infra).
3. **Découpage en services par domaine** : `sources` (scrap+enrich), `vision` (crop+detect+normalize),
   `training` (augment+train+embeddings), `review` (queue+lot+auto-validate), `serving` (API mince).
   Frontières à valider via les **communautés graphify** (= clusters naturels du code).
4. **Dockerisation** : conteneurs séparés (API / worker(s) / MinIO / accès eurio.db) pour isoler
   les cycles de vie et reproduire l'env. À peser vs. la simplicité Nix actuelle (cf. `cross-platform-setup.md`).
5. **Découpler scrape ↔ crop** (déjà identifié dans `roadmap.md` livrable #13) : mode download-only,
   crop déclenché séparément — s'inscrit naturellement dans le découpage par service.

## Comment graphify aide ce chantier

`ml/` est **déjà indexé** dans le graphe (14 988 nodes AST). Avant de découper :
- `graphify query "comment X appelle Y"` / `graphify explain "Store"` pour cartographier le couplage.
- Les **god nodes** (Store, SourceQuery…) = les points de couplage à casser en priorité.
- Les **communautés** = candidats naturels de frontières de service.
- Les **cycles d'import** signalés = dette structurelle à résoudre.

→ Recommandation d'indexation : voir [`kickoff.md`](./kickoff.md) §indexation.
