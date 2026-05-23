# Spec — Dashboard d'opérations J1 (scrape, training-ready, bench)

> Doc spec à implémenter dans une session dédiée. ~3-4 h estimé.
>
> Rédigé 2026-05-23 après alignement sur la roadmap J1→J7 et clarification
> training/bench (cf. memory `project_training_bench_split`).

## Objectif

Piloter visuellement l'avancement vers le premier entraînement utile :
- savoir si le scrape eBay tourne en routine (J1)
- savoir si chaque classe a assez d'images pour entrer en training (J4)
- savoir si la diversité wild monte
- savoir si le bench cohorte est prêt à valider le futur modèle

Point d'entrée : nouvelle route admin **`/operations`**, accessible depuis
le menu latéral (ajouter un item "Operations" ou "Pulse").

## Modèle mental — vision corrigée

```
Training data per classe = n(Numista canonical) + n(wild scraped)
                          ├─ Numista canon → moulinette augmentation artificielle
                          └─ Wild (eBay aujourd'hui, autres demain) → variance naturelle

Bench data = cohortes physiques capturées via app Android
             (hold-out par construction)
```

**Seuil training-ready acté** : `≥ 30 images sources / classe`. Avec augmentation
×10 sur Numista canon → ~300 samples/class, raisonnable pour ArcFace.

**Tiers couleur dans le dashboard** :
- 🔴 `< 5` : red zone, classe inexploitable
- ⚠️ `5-29` : warn, training possible mais qualité incertaine
- ✅ `≥ 30` : green, target atteinte

## Layout — 4 sections

### Section 1 — Pulse eBay (J1)

Activité de scrape sur les 7 derniers jours.

```
┌─ Pulse eBay — 7 derniers jours ──────────────────────────────────┐
│                                                                  │
│  Searches lancées        Items nouveaux dédupliqués              │
│  [bar chart par jour]    [bar chart par jour]                    │
│                                                                  │
│  Par marketplace :                                               │
│  EBAY_DE : 22 searches → 859 kept (recall 72%)                  │
│  EBAY_ES : 22 searches → 664 kept (recall 76%)                  │
│                                                                  │
│  Dernière exécution : il y a 2h · run_id eb-abc123              │
│  [Voir runs] → /sources/ebay                                     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Données** :
- `discovery_searches` filtré sur `created_at >= now() - 7 days`
- agrégation par `query_filters_json.marketplace` et `date(created_at)`
- recall = `sum(n_kept_results) / sum(n_raw_results)`
- dernière exécution = `max(created_at)` joined à `source_runs`

**Queries de référence** :
```sql
SELECT date(created_at) AS day,
       json_extract(query_filters_json, '$.marketplace') AS mkt,
       count(*) AS searches,
       sum(n_raw_results) AS raw,
       sum(n_kept_results) AS kept
FROM discovery_searches
WHERE created_at >= datetime('now', '-7 days')
GROUP BY day, mkt
ORDER BY day, mkt;
```

### Section 2 — Training readiness (J4)

État des classes vis-à-vis du seuil training.

```
┌─ Training readiness — par design_group (ou eurio_id si seul) ────┐
│                                                                  │
│  Seuil : 30 sources / classe                                     │
│                                                                  │
│  ✅ Above 30      :  12 / 619 classes  ( 2%)                     │
│  ⚠️ 5-29 sources  :  47 / 619 classes  ( 8%)                     │
│  🔴 < 5 sources   : 560 / 619 classes  (90%)                     │
│                                                                  │
│  [Histogram horizontal des 3 zones]                              │
│                                                                  │
│  Liste paginable des classes 🔴 (priorité scrape) :              │
│  ┌─────────────────────────────────────────────┬────┬────┐      │
│  │ Classe / Thème                              │canon│wild│      │
│  ├─────────────────────────────────────────────┼────┼────┤      │
│  │ ad-2014-2eur-25-years-of-the-constitution   │  2 │  0 │      │
│  │ at-2007-2eur-treaty-of-rome (DG fr,de,…)    │  2 │  0 │      │
│  │ ...                                          │    │    │      │
│  └─────────────────────────────────────────────┴────┴────┘      │
│  [Voir tout] [Filtrer par pays] [Trier par n asc/desc]          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Données** :
- Pour chaque commémo 2 €, calculer `class_id = COALESCE(design_group_id, eurio_id)`.
- Comptage **canonical** : `coin_canonical_images` joinés sur l'union des `eurio_id` du design_group.
- Comptage **wild** : `source_images` (joinés sur `target_eurio_id` ∈ design_group).
- Total = canon + wild, comparé au seuil 30.

**Queries de référence** :
```sql
WITH class_map AS (
  SELECT eurio_id, COALESCE(design_group_id, eurio_id) AS class_id
  FROM coins WHERE face_value=2.0 AND is_commemorative=1
),
canon AS (
  SELECT m.class_id, count(*) AS n_canon
  FROM coin_canonical_images c JOIN class_map m ON m.eurio_id=c.eurio_id
  GROUP BY m.class_id
),
wild AS (
  SELECT m.class_id, count(*) AS n_wild
  FROM source_images s JOIN class_map m ON m.eurio_id=s.target_eurio_id
  GROUP BY m.class_id
)
SELECT m.class_id,
       COALESCE(canon.n_canon, 0) AS n_canon,
       COALESCE(wild.n_wild, 0)  AS n_wild,
       COALESCE(canon.n_canon, 0) + COALESCE(wild.n_wild, 0) AS n_total
FROM (SELECT DISTINCT class_id FROM class_map) m
LEFT JOIN canon USING (class_id)
LEFT JOIN wild  USING (class_id)
ORDER BY n_total ASC;
```

**Conventions visuelles** :
- Bandeau couleur en tête (proportion par tier)
- Histogram horizontal log-scale (la queue très chargée à 0)
- Lien direct `class_id → /coins/<eurio_id>` (ou page design_group si UI existe)

### Section 3 — Diversité wild (qualité sourcing)

Combien de marketplaces × pays origin contribuent à chaque classe.

```
┌─ Diversité wild — n_marketplaces_contributing                    │
│                                                                  │
│  Distribution :                                                  │
│  0 marketplaces (jamais vu)   : 510 classes                      │
│  1 marketplace                : 12 classes                       │
│  2 marketplaces (DE + ES)     : 92 classes                       │
│                                                                  │
│  Top contributing marketplaces (sur 7j) :                        │
│  EBAY_DE : 859 items kept                                        │
│  EBAY_ES : 664 items kept                                        │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Données** :
- Par classe, distinct marketplaces dans `source_images.marketplace` (joinés via class_map).
- Si une classe a `n_marketplaces = 1` mais `n_wild > 30`, c'est un signal d'over-fitting au sourcing → flag jaune.

### Section 4 — Bench cohort status

Avancement des cohortes physiques capturées dans l'app Android.

```
┌─ Bench cohort status                                             │
│                                                                  │
│  Cohortes actives    : 3 (status='draft')                        │
│  Cohortes frozen     : 1 (status='frozen', prêtes pour bench)    │
│                                                                  │
│  Liste :                                                         │
│  ┌──────────────────────┬─────────┬──────────┬───────┐          │
│  │ Cohort               │ Status  │ Members  │ Captures│         │
│  ├──────────────────────┼─────────┼──────────┼───────┤          │
│  │ q1-2026-test         │ frozen  │ 24       │  240  │          │
│  │ confusion-zone-red   │ draft   │ 12       │   48  │          │
│  │ ...                  │         │          │       │          │
│  └──────────────────────┴─────────┴──────────┴───────┘          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Données** :
- `experiment_cohorts` : id, name, status, frozen_at
- `cohort_members` : count par cohort_id
- Captures : à clarifier. Si stockées côté Android local, on n'a pas
  encore la donnée centralisée. Sinon `image_assets` filtré sur un tag
  `cohort_capture` ? → **À résoudre avant build** (cf. open questions).

**Open question** : où sont stockées les captures cohort ? Si elles ne
sont pas accessibles via Supabase / eurio.db, la 4e section doit se
limiter au statut des cohortes (members count, frozen/draft).

## Effort estimé

| Composant | Effort |
|---|---|
| Route `/operations` + skeleton page Vue | 30 min |
| Section 1 — Pulse eBay (queries + chart simple) | 1 h |
| Section 2 — Training readiness (queries + tiers + table) | 1 h 30 |
| Section 3 — Diversité wild | 30 min |
| Section 4 — Bench cohort (limited si données not centralisées) | 30 min |
| Polish + tests visuels | 30 min |
| **Total MVP** | **~4-4 h 30** |

## Pré-requis avant build (à résoudre en amont)

1. **Threshold confirmé** : 30 sources / classe, tiers 🔴<5 ⚠️5-29 ✅≥30.
2. **Captures cohort accessibles** : trancher si on peut requêter ou si Section 4
   se limite à statut cohortes seul. Recommandation : ouvrir une session courte
   pour clarifier la pipeline cohort → centralised store.
3. **Charts** : la stack admin web a-t-elle déjà une lib chart ? Si oui (Chart.js,
   ApexCharts, etc.), utiliser. Sinon, démarrer avec tableaux simples + sparklines
   custom et chart lib en chunk séparé.

## Anti-objectifs

- ❌ Pas de bouton "Lancer un scrape" depuis le dashboard (manual on-demand
  reste côté CLI / `go-task ml:ebay:discover-...`). Le dashboard observe,
  ne pilote pas.
- ❌ Pas de visu temps réel (websocket / polling agressif). Refresh à
  l'ouverture suffit, F5 pour actualiser.
- ❌ Pas de section "model classes embeddings" (vit dans `/training` déjà).

## Liens connexes

- Vision globale J1→J7 : voir conversation 2026-05-23, ou re-générer un
  `docs/roadmap.md` actualisé.
- Memory : `project_training_bench_split`, `project_ebay_api_strategy`,
  `project_discovery_groupee`.
- Code adapter discovery eBay : `ml/sources/ebay/adapter.py`, `marketplaces.py`.
- Decision marketplace policy DE+ES seuls : `ml/sources/ebay/marketplaces.py`
  (header docstring + benchmark routing 2026-05-21).
