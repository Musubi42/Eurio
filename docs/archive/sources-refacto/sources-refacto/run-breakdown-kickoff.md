# Kickoff Run Breakdown — vue résultat de run par eurio_id

> Brief auto-suffisant pour la session "drill-down d'un run avec
> répartition par target_eurio_id". Première phase du chantier
> 3-axes admin (Sources → Review → Coins).

## Pourquoi

Aujourd'hui après un run on a deux infos : compteurs agrégés
(`source_runs.n_*`) + `filters_json` brut. Exemple typique du
2026-05-03 — un run eBay avec 10 target_eurio_ids Andorre :

```
filters_json: {"target_eurio_ids": ["ad-2014-2eur-...", ...10 ids]}
n_calls: 47, n_raws_added: 12, n_crops_added: 18,
n_review_enqueued: 6, n_quotes_added: 2
```

→ Impossible de savoir **lequel** des 10 eurio_ids a ramené quoi.
Le reviewer ne peut pas auditer le run, ni cibler son temps de
review sur ce qui en vaut la peine.

Le breakdown est entièrement **dérivable** depuis les FK existantes
(`source_images.run_id` + `target_eurio_id`, `image_assets.run_id`,
`coin_market_quotes.run_id`, `review_queue` joint). Pas de schéma
à toucher.

## Décisions

### RB-D-1 — Périmètre du breakdown : ciblés + bonus

Le tableau breakdown a **deux blocs** :

1. **Ciblés** : les eurio_ids de `filters_json.target_eurio_ids`
   (ou tous les eurio_ids référencés si pas de filtre). Toujours
   listés même si `0 listing trouvé` — c'est l'info qui manquait.
2. **Bonus** : eurio_ids résolus depuis ce run mais hors cible
   (cas eBay où un coffret contient des pièces autres que la cible).
   Listés seulement s'il y en a.

### RB-D-2 — Colonnes du tableau

Par eurio_id (ciblé ou bonus) :

| Colonne | Source SQL |
|---|---|
| eurio_id | `source_images.target_eurio_id` ou `image_assets.eurio_id` |
| Listings | `count(distinct source_images.id)` |
| Crops | `count(distinct image_assets.id)` |
| Auto résolus | `count WHERE resolution_status IN ('auto_name','auto_phash')` |
| Review single | `count(review_queue WHERE kind='single' AND status='open')` |
| Review lot | `count(review_queue WHERE kind='lot' AND status='open')` |
| Quotes | `count(coin_market_quotes WHERE run_id=X AND eurio_id=Y)` |
| Actions | liens "fiche pièce" + "reviewer" |

### RB-D-3 — Page dédiée, deeplinkable

`/sources/:id/runs/:run_id` — pas un drawer. Permet de partager
l'URL, de bookmarker un run problématique, et de revenir dessus
plus tard.

### RB-D-4 — Pas de stockage du breakdown

Tout calculé à la volée (1 requête SQL bien indexée, indexes
`idx_source_images_run` + `idx_image_assets_run` + `idx_cmq_run`
existent déjà). Si lent en V2 (>200ms), envisager un cache
matérialisé.

### RB-D-5 — Liens sortants vers les 2 autres axes

Chaque ligne du breakdown a deux flèches :
- → `/coins/:eurio_id` (vue produit, V2 — pour l'instant lien désactivé/tooltip)
- → `/review?run_id=X&eurio_id=Y` (file de travail, V1.5 disponible
  une fois la review unifiée livrée)

V1 du breakdown : flèches présentes mais juste `/review` global
si la page review unifiée n'est pas encore là.

## Architecture cible

```
ml/api/sources_routes.py
  └── GET /sources/:id/runs/:run_id/breakdown   ← NEW

admin/packages/web/src/features/sources/
  ├── pages/
  │   ├── SourceDetailPage.vue                 ← modif : runs table → click row navigue
  │   └── SourceRunDetailPage.vue              ← NEW : header run + tableau breakdown
  └── composables/
      └── useRunBreakdown.ts                   ← NEW
```

## Endpoint

`GET /sources/:id/runs/:run_id/breakdown`

Réponse :
```json
{
  "run_id": "...",
  "source_id": "ebay",
  "started_at": "2026-05-03T08:43:00",
  "status": "success",
  "filters": { "target_eurio_ids": [...] },
  "targeted": [
    {
      "eurio_id": "ad-2014-2eur-20-years-...",
      "n_listings": 3,
      "n_crops": 5,
      "n_auto_resolved": 2,
      "n_review_single": 2,
      "n_review_lot": 1,
      "n_quotes": 1
    },
    {
      "eurio_id": "ad-2015-2eur-25-years-...",
      "n_listings": 0, ...
    }
  ],
  "bonus": [
    {
      "eurio_id": "fr-2002-2eur-circulation",
      "n_listings": 0,
      "n_crops": 1,
      "n_auto_resolved": 0,
      "n_review_single": 0,
      "n_review_lot": 1,
      "n_quotes": 0,
      "via_lot": true
    }
  ]
}
```

## Pipeline de la session (chunks)

### RB.A — Endpoint backend (~80 lignes)

- `GET /sources/:id/runs/:run_id/breakdown` dans `sources_routes.py`
- Une CTE qui collecte tous les eurio_ids touchés par le run
- Joins sur `source_images`, `image_assets`, `coin_market_quotes`,
  `review_queue`
- Distinction targeted (depuis `filters_json`) vs bonus
- Test `test_run_breakdown.py` (~5 cas : run vide, run avec ciblés
  uniquement, run avec bonus, run dry, run failed)

**Livrable review** : endpoint testé, curl sur le run du 2026-05-03
montre les 10 Andorres.

### RB.B — Page Vue + nav (~150 lignes)

- Route `/sources/:id/runs/:run_id` ajoutée
- `SourceRunDetailPage.vue` : header run (réutilise composants existants)
  + tableau breakdown (deux sections : Ciblés / Bonus)
- `useRunBreakdown.ts` : fetch + types
- Modif `SourceDetailPage.vue` : table runs → click row navigue

**Livrable review** : capture d'écran de la page sur le run Andorre,
tableau lisible, deux sections distinctes.

### RB.C — Liens sortants + polish (~50 lignes)

- Bouton "Reviewer (N items)" par ligne → `/review?run_id=X&eurio_id=Y`
  (atterrit sur `/review` global pour l'instant si Review unifiée
  pas encore livrée)
- Bouton "Voir la pièce" désactivé avec tooltip "Disponible avec /coins"
- Empty state si run vide ("0 listing trouvé sur les N cibles —
  cf. log pour comprendre")
- Loading state, error state

**Livrable review** : flow complet `/sources/ebay` → click run row
→ breakdown → click "Reviewer" → `/review` filtré.

## Tests verts à conserver

```
tests/test_sources_base.py        8/8
tests/test_orchestrator.py       12/12
tests/test_bootstrap_coins.py     4/4
tests/test_ebay_adapter.py       24/24
tests/test_ebay_api.py            8/8
tests/test_resolve_lot_quote.py   9/9
                                ────
                                 65/65 ✅
```

RB.A ajoute ~5 tests : `test_run_breakdown.py`.

## Hors scope (V2)

- Export CSV du breakdown
- Comparaison de runs (run N vs run N-1 : Δ par eurio_id)
- Re-run ciblé depuis le breakdown ("re-runner les 0-listing")
- Sparkline temporelle par eurio_id sur cette source

## Contraintes héritées

- R0 pas de dette technique (CLAUDE.md)
- Pas d'emojis dans le code
- 3-axes admin acté (cf. `coins-admin-kickoff.md`)
- Tests verts requis avant chaque chunk suivant
