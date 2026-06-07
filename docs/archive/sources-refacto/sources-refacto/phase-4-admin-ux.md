# Phase 4 — Admin UX

> Page détail `/sources/:id` + cards enrichies. Spec UX détaillée :
> voir `admin-ux.md`.

## Pourquoi cette phase

- Aujourd'hui la page `/sources` montre que ça tourne, mais pas ce
  que ça produit. Une fois les nouvelles tables remplies (phases 1-3),
  on a besoin de **les voir** sans aller fouiller le disque ou la DB.
- L'admin est le tableau de bord opérationnel pour piloter les runs
  et les couvertures par source.

## Périmètre

### 4.1 Backend ML API

Nouveaux endpoints (cf. liste exhaustive dans `admin-ux.md`) :

```
GET /sources/status                 # étendu avec n_images_30d, n_quotes_30d, last_run_summary
GET /sources/:id                    # header détaillé
GET /sources/:id/runs               # liste paginée
GET /sources/:id/runs/:run_id/log   # log file
GET /sources/:id/images             # liste paginée avec filtres
GET /sources/:id/quotes             # liste paginée avec filtres
GET /sources/:id/coverage           # breakdown couverture
```

Code backend : `ml/api/sources_routes.py` (nouveau, à côté de
`lab_routes.py`).

### 4.2 Frontend `admin/packages/web/src/features/sources/`

- Refonte `useSourcesApi.ts` :
  - étendre `SourceStatus` (cf. `admin-ux.md`)
  - ajouter `fetchSourceDetail`, `fetchSourceRuns`, `fetchSourceImages`,
    `fetchSourceQuotes`, `fetchSourceCoverage`
  - garder le mock pendant le développement
- Nouvelle page `SourceDetailPage.vue` avec route `/sources/:id`
  - header commun
  - 4 onglets : Runs, Données, Couverture, Commandes
- Composants nouveaux :
  - `RunsTable.vue`
  - `ImagesGallery.vue` + `ImageDetailModal.vue`
  - `QuotesTable.vue`
  - `CoverageBreakdown.vue`
  - `CliCommandsList.vue` (extrait + amélioré de `CliHintsBlock.vue`)
- **Fusion des 3 cartes Numista en 1 carte** "Numista" avec
  sous-actions dans l'onglet Commandes.

### 4.3 Liste enrichie

- Sur les `SourceCard.vue` actuelles, afficher :
  - n_images / n_quotes du dernier run
  - Δ depuis run précédent en images (pas seulement prix)
  - bouton "Voir détails →" → `/sources/:id`

### 4.4 Routing

- Ajouter route Vue Router `/sources/:id` → `SourceDetailPage`.
- Click sur une carte Source navigue sur la page détail.

## Out of scope (phase 4)

- Boutons "Lancer le run" depuis l'admin (POST sources). V2.
- Annotation manuelle des images (review queue). Hors scope total.
- Comparaison cross-source des prix sur la page admin (graphique
  multi-source pour un eurio_id donné). Utile mais c'est une page
  produit, pas une page source — refacto séparée.

## Validation

- Pour chaque source câblée (au moins eBay + une nouvelle de la
  phase 2), la page détail montre :
  - >0 runs dans Runs
  - >0 images dans Données → Images, avec thumbs et filtres qui
    marchent
  - >0 quotes dans Données → Quotes
  - Couverture cohérente avec ce qu'a remonté `fetchSourcesStatus`
  - Commandes copiables, identiques aux tasks go-task réelles
