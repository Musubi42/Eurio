# Admin UX — page Sources étendue

> Évolutions de la page `/sources` existante + spec de la nouvelle
> page détail `/sources/:id`.

## Principes

1. **Une carte par source** (pas par run, pas par sous-fonction).
   Numista API qui fait match + enrichissement + images reste **une**
   source côté UX, avec sous-tâches en interne. NB : aujourd'hui la
   page admin présente Numista en 3 cartes — à fusionner en 1 carte
   "Numista" avec des sous-actions.
2. **Cards = vue synthétique**, page détail = drill-down.
3. **Mock-first** comme la page actuelle (V1 sans backend), avec
   contrat aligné sur ce que `GET /sources/status` et
   `GET /sources/:id` exposeront.

## Page liste `/sources` — cards enrichies

Champs additionnels par card par rapport à l'existant :

```
┌─ Catawiki ──────────────────────────────────── 🟢 healthy ─┐
│ Scrape · cadence 14j                                       │
│                                                            │
│  Coverage : 234 / 517 commémos enrichies (45%)             │
│  Quota    : rate-limit 1 req/2s · pas de hard cap          │
│                                                            │
│  Dernier run : il y a 2j · 47 images, 23 quotes ajoutés    │
│                                                            │
│  Δ depuis dernier : +12 images, +8 quotes                  │
│                                                            │
│  [Voir détails →]                                          │
└────────────────────────────────────────────────────────────┘
```

Nouveaux éléments vs aujourd'hui :
- ligne **"images, quotes ajoutés au dernier run"** (sortie de `source_runs`)
- Δ depuis le run précédent en images/quotes (pas seulement prix)
- bouton "Voir détails →" → `/sources/:id`

## Page détail `/sources/:id`

Layout 4 onglets, header commun :

```
┌─ Catawiki ─────────────────────────────────────────────────┐
│ Scrape HTML · enchères · license fair_use_research         │
│ 🟢 healthy · cadence cible 14j                              │
│                                                            │
│ [Runs] [Données] [Couverture] [Commandes]                  │
└────────────────────────────────────────────────────────────┘
```

### Onglet 1 — Runs

Table chrono (last 50, filtre par status) :

| started_at | kind | duration | n_calls | n_images | n_quotes | n_errors | status | filters | logs |
|---|---|---|---|---|---|---|---|---|---|
| 2026-04-30 14:02 | run | 14m32s | 487 | 47 | 23 | 1 | success | `{}` | [view] |
| 2026-04-30 13:50 | dry | 2s | 0 | 0 | 0 | 0 | success | `{limit:5}` | [view] |
| 2026-04-25 09:10 | run | 12m08s | 401 | 35 | 18 | 0 | success | `{}` | [view] |

Click sur "view" → modal avec les 200 dernières lignes du log file
(`source_runs.log_path`).

Click sur une ligne → drill-down sur les rows produites par ce run
(filtre `image_assets.run_id = X`).

### Onglet 2 — Données

Deux sous-sections :

**Images** (galerie, pagination 24/page) :
- thumb 120×120, hover affiche `eurio_id`, `variant_kind`,
  `quality_score`, `training_eligible`
- filtres : `eurio_id`, `variant_kind`, `training_eligible`,
  période fetched
- click → modal avec image full + payload brut

**Quotes** (table) :

| eurio_id | condition | p10 | p50 | p90 | n | period | fetched |
|---|---|---|---|---|---|---|---|
| de-2020-2eur-kniefall | UNC | 4.50 | 6.20 | 9.80 | 14 | 2026-04 | il y a 2j |

### Onglet 3 — Couverture

- progress bar globale (déjà existante)
- breakdown par dimension pertinente à la source :
  - eBay : par pays, par année, par dénomination
  - Catawiki : par catégorie d'enchère, par condition déclarée
  - Numista : par pays, par valeur faciale
- liste des `eurio_id` **non couverts** (pour cibler les prochains runs)

### Onglet 4 — Commandes

Reprend les `cli_hints` existants mais avec :
- bouton "Copier" sur chaque commande
- explication de l'`expected_outcome`
- avertissement si la commande est destructive (reset)
- (V2 / opt-in) bouton "Lancer" pour exécuter via l'API ML —
  **désactivé par défaut**, à câbler explicitement par source.

## Endpoints attendus côté ML API

```
GET  /sources/status                          # liste, déjà mock
GET  /sources/:id                             # détail header + counts
GET  /sources/:id/runs?limit=50&status=…      # onglet Runs
GET  /sources/:id/runs/:run_id/log            # log file content
GET  /sources/:id/images?page=…&filters=…     # onglet Données → Images
GET  /sources/:id/quotes?page=…&filters=…     # onglet Données → Quotes
GET  /sources/:id/coverage                    # onglet Couverture
```

Pas de POST dans le V1 admin (read-only, comme les autres pages).
Le déclenchement de runs reste via `go-task` localement.

## Évolution de `useSourcesApi.ts`

- Étendre `SourceStatus` avec :
  - `n_images_30d: number`
  - `n_quotes_30d: number`
  - `last_run_summary: { n_images: number, n_quotes: number, status: string }`
- Ajouter `fetchSourceDetail(id)`, `fetchSourceRuns(id, opts)`, etc.
- Garder le mock pendant la phase 1, brancher sur l'API réelle
  quand les endpoints existent.

## Impact sur la page actuelle

- **Numista** passe de 3 cards à 1 carte avec sous-actions dans
  l'onglet Commandes (`match`, `enrich`, `images`).
- **Cards génériques** : code factorise mieux quand toutes les
  sources suivent le même contrat.
- **Future sources** (Wikipedia, Catawiki, NumisCorner, CGB) :
  entrées `is_future: true` au début, deviennent normales quand
  câblées.
