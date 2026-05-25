# Référentiel — Pipeline de fixes (apply-fix)

> Chantier ouvert 2026-05-25. Trackeur pour résoudre les **mauvais liens
> data** entre `coins.eurio_id`, `coins.numista_id` et les sources externes
> (BCE sidecar, Supabase, Storage). Suit l'investigation du cas LV 2018
> Zemgale qui a révélé un problème systémique.

## TL;DR

Le bootstrap initial a créé **1 row par (country, year)** alors que ~13
(country, year) ont plusieurs 2 € commémo. Conséquence : 9 numista_id
orphelins en catalogue + 9 rows existantes qui pointent vers le mauvais
numista_id, avec des sources externes (BCE/LMDLP) collées en cascade sur
la mauvaise row.

Le pipeline apply-fix doit :
1. **Discover** les cas automatiquement
2. **Preview** dans la console admin avant/après
3. **Apply** la cascade complète en un geste : eurio.db + image fetch +
   Supabase + Storage cleanup

## Cause racine

| Symptôme | Mécanisme |
|---|---|
| `audit_referential` : count_mismatch +1 sur 9 (pays, année) | Le bootstrap a inséré 1 row au lieu de 2+ pour ces (country, year) avec 2 commémo Numista |
| `audit_referential` : catalog_unlinked 9 | Le numista_id de la 2ème commémo (manquante en DB) reste orphelin en `referential_catalog` |
| `/referential/divergences` : 144 soft, dont des sim < 0.05 | BCE matcher slug a collé son sidecar sur l'unique row disponible pour (country, year), même si sémantiquement c'est l'autre coin |

Les coins existants ont gardé l'identité **bonne** dans `coins.theme` et
`coins.design_description` (issus de leur slug eurio_id), mais leur
**liaisons externes** (`coins.numista_id`, observations.bce_comm,
observations.lmdlp_variants) pointent vers le coin sœur manquant.

## Les 9 cas identifiés (par discovery 2026-05-25)

Discovery a **9/9 Shape B** (swap + new row), aucun pur Shape A. Stockés
dans `ml/state/referential_fix_proposals.json`.

| Pays Année | Confidence | Existing row (swap) | Orphan reçu | New row à créer (displaced) | Joint group |
|---|---|---|---|---|---|
| ES 2012 | high | `burgos-cathedral` (was 28193) | 30072 Burgos | `10-years-of-euro-cash` (28193) | `eu-euro-cash-2012` ✓ |
| FR 2014 | medium | `world-aids-day` (was 67424) | 67264 AIDS Day | `world-aids-day-BU…` (67424) | — |
| BE 2015 | high | `european-year-for-development` (was 77181) | 76630 EYD | `philippe-30-years-of-european-union-flag` (77181) | `eu-eu-flag-2015` ✓ |
| DE 2015 | high | `25-years-of-german-unity` (was 284594) | 69264 Unity | `bundeslander-hessen-pattern` (284594) | — |
| LT 2015 | high | `lithuanian-language` (was 76640) | 78191 Lang | `30-years-of-european-union-flag` (76640) | `eu-eu-flag-2015` ✓ |
| LV 2016 | high | `vidzeme` (was 85889) | 95462 Vidzeme | `latvian-farming-and-countryside` (85889) | — |
| ES 2018 | high | `old-town-of-santiago-de-compostela` (was 131882) | 131881 Santiago | `felipe-vi-50th-birthday-of-king-felipe-vi` (131882) | — |
| FR 2018 | medium | `bleuet-de-france` (was 134283) | 134685 Bleuet | `bleuet-de-france-coloured` (134283) | — |
| LV 2018 | high | `zemgale` (was 132943) | 143883 Zemgale | `100th-anniversary-of-the-baltic-states` (132943) | **à créer** `eu-baltic-states-2018` |

**Insights majeurs** :
- 5 cas sur 9 sont des joints existants ou à créer → ces new rows
  doivent être rattachées à un `design_group_id`.
- BCE sidecar : attribution recommandée par fuzzy = `existing` pour la
  plupart, mais 2 cas (LV 2016 Vidzeme, LV 2018 Zemgale) suggèrent que
  le BCE actuel décrit la **new row**, pas l'existing → migration FS.
- Toutes les nouvelles rows ont leur `design_description` héritée du
  `referential_catalog.raw_json.obverse_description` Numista.

Plus 4 cas 2026 (CY/HR/IE/EE) en Δ-1 — hors scope de ce pipeline
(résolus par Discover Numista quand le catalogue 2026 sera complet).

Plus 4 cas 2026 (CY/HR/IE/EE) où l'inverse est vrai : on a une row dans
`coins` mais Numista catalogue ne la connaît pas encore (Δ-1). Ces 4-là
ne sont **pas** dans le périmètre du pipeline — ils se résoudront via
Discover Numista quand les pièces 2026 seront référencées.

## Shapes de fix

### Shape A — Missing row only

Le numista_id orphelin a un titre Numista qui ne correspond à aucun slug
eurio_id existant en (country, year). Geste : créer une nouvelle row
avec slug auto-généré depuis le titre.

Tous les autres coins existants en (country, year) ont leur numista_id
correctement lié → aucun swap nécessaire.

### Shape B — Swap + missing row

Un eurio_id existant a un numista_id dont le titre Numista ne matche
PAS son propre slug (fuzzy similarity faible). Le numista_id orphelin du
catalog, lui, matche le slug.

Geste :
1. Swap : `existing_row.numista_id = orphan_numista_id` (le bon)
2. New row : créer une row pour le numista_id "déplacé" avec slug
   auto-généré depuis son titre
3. Migrer les observations externes (bce_comm, lmdlp_variants) qui
   appartiennent en réalité à la new row (elles ont été collées sur
   `existing_row` par cascade)

C'est le cas LV 2018 Zemgale.

## Architecture du pipeline

```
┌──────────────────────────────────────────────────────────────┐
│  scripts/discover_referential_fixes.py                       │
│  Lit audit + fuzzy match titres ↔ slugs                      │
│  → ml/state/referential_fix_proposals.json                   │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  GET  /referential/fix-proposals                             │
│  POST /referential/fix-proposals/{case_id}/apply             │
│  (api/referential_routes.py)                                 │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  Page admin /referential/fixes                               │
│  Preview avant/après + bouton Apply                          │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  Cascade Apply (côté backend) :                              │
│   1. Backup eurio.db                                         │
│   2. INSERT/UPDATE coins                                     │
│   3. Move FS sidecars BCE si applicable                      │
│   4. Fetch image Numista pour new numista_id                 │
│   5. INSERT coin_canonical_images                            │
│   6. Push Supabase Storage (upload + DELETE orphan path)     │
│   7. Push Supabase coins/observations                        │
│   8. Verify : audit_referential + /divergences               │
└──────────────────────────────────────────────────────────────┘
```

## Décisions actées (2026-05-25)

| Question | Décision |
|---|---|
| Source de l'image fetch | **Numista API directe** (idempotent : skip si déjà téléchargé) |
| Génération du slug new row | **Auto depuis le titre Numista** (kebab-case `{country}-{year}-2eur-{title-kebab}`) |
| Workflow apply | **UI admin one-by-one** (preview puis bouton, pas de bulk auto) |
| Layers à pusher | eurio.db + `coin_canonical_images` + Supabase coins + Supabase Storage. Cleanup orphan Storage explicite. |

## Suivi par chunk

| Chunk | Statut | Livré | Notes |
|---|---|---|---|
| 0 — Investigation LV 2018 | ✅ 2026-05-25 | Diagnostic clair, fix manuel testé puis reverté pour repartir clean | |
| 1 — Doc + Discovery script | ✅ 2026-05-25 | `scripts/discover_referential_fixes.py` + JSON output + cette doc | Discovery 9/9 Shape B |
| 2 — Apply endpoint + cascade backend | ⏳ next session | POST `/fix-proposals/{case_id}/apply` qui déroule la cascade en 8 étapes | À faire |
| 3 — UI admin `/referential/fixes` | ⏳ next session | Preview avant/après + bouton apply + audit visuel | À faire |
| 4 — Validation visuelle sur LV 2018 | ⏳ | Run pipeline sur Zemgale + vérif `/coins/lv-...` affiche bien Zemgale image | Test pilote |
| 5 — Apply sur les 8 cas restants | ⏳ | Un par un via UI | Après validation pilote |
| 6 — Création design_groups manquants | ⏳ | `eu-baltic-states-2018` au minimum | Hors scope direct, mais à enchaîner |

## Endpoints / artefacts existants à réutiliser

- `python -m scripts.audit_referential` → JSON dans `ml/datasets/referential_audit.json`
- `python -m scripts.push_to_supabase [--dry-run] [--skip-storage]` → push eurio.db → Supabase
- `GET /referential/coverage` → gaps (mais ignore les BCE FS — patch fait dans `/zero-canon`)
- `GET /referential/divergences` → détecteur BCE↔Numista, mesure d'effet post-fix
- `ml/sources/numista/` → fetcher Numista par id (existant pour le bootstrap initial)

## Risques connus

- **Quota Numista** : 9 fetches d'image pour les 9 cas, ~20 calls API total. Largement dans le budget free (~2000/mois).
- **Race condition Supabase Storage** : si le push échoue après upload mais avant DELETE orphan, on a un fichier en doublon. Pas critique (l'URL canonique pointe vers le bon path, l'orphan reste invisible). Cleanup script séparé peut le détecter (HEAD check sur paths non-référencés).
- **Cas où le fuzzy match du discovery est ambigu** : Shape A vs Shape B mal classé. Mitigation : la UI admin montre le score de similarité, l'éditeur peut refuser le diagnostic avant apply.

## Hors scope du pipeline

- Joint issues design_groups (`eu-baltic-states-2018` etc.) : à attaquer dans
  un autre chantier après que les rows existent (cf. roadmap §"Joint
  issues — 20 variants manquants").
- Refactoring du bootstrap initial pour qu'il ne reproduise plus le bug :
  pas urgent, le bootstrap est rarement re-run.
- Cas inverse Δ-1 (4 cas 2026) : résolus par Discover Numista séparé.
