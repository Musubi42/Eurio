# Chunk 04 — Review filtrée par cohort

> **But** : depuis `/review`, ne reviewer que les images eBay des coins d'une
> cohort (au lieu de la queue globale de ~2258 items).

## Backend

`GET /review-queue` (`ml/api/review_queue_routes.py::list_queue`) gagne un param
optionnel **`cohort_id`**. Quand fourni : charge la cohort (`Store.get_cohort`) et
ajoute `AND s.target_eurio_id IN (<eurio_ids>)` — soit les items dont le coin
theme-matché appartient à la cohort. Cohort vide → `[]`, cohort inconnue → 404.

Filtre sur `source_images.target_eurio_id` (l'attribution du theme-matcher). Les
items à target NULL (verdict ambigu) ne sont pas inclus — ils n'appartiennent à
aucun coin précis ; reviewables via la queue globale.

**Validé** (read-only) : `?cohort_id=<mix-zone-16>` → tous les items sont des coins
de la cohort (at-2005×47, fi-2017×31, es-2016×30, fr-2008×30, fi-2016×27,
be-2011×23, de-2020×12…).

## Frontend

- `useReviewApi.fetchReviewQueue({ limit, cohortId })` → `&cohort_id=`.
- `SingleReviewView` lit `?cohort=<id>` (route query), le passe à la queue, et
  **recharge au changement** (watch). `currentIndex` remis à 0.
- `ReviewPage` : sélecteur **Cohort** dans le header (mode Single), peuplé via
  `useCohortsQuery` (lab), persisté dans l'URL (`?cohort=`). « Toutes » = global.

URL : `http://localhost:5173/review?cohort=<COHORT_ID>`.

## Limites connues (polish ultérieur, non bloquant)

- Le bandeau **stats** (`/review-queue/stats`) reste **global** (pas encore
  cohort-scopé) — le compteur « pending » ne reflète pas le filtre.
- **Lot mode** + **auto-accept** + **Claude batch** ne sont pas cohort-scopés.
  Le filtre couvre la review Single (le flow principal).

## Journal

- 2026-06-02 — backend `cohort_id` + UI sélecteur livrés, typecheck clean,
  filtre validé. Audit visuel à faire sur `/review?cohort=<id>`.
