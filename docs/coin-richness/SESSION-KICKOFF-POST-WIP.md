# Kickoff — Reprise post-session WIP (chantier D + F livrés)

> Document destiné à une **nouvelle session Claude Code** (ou Raphaël en
> reprise après pause). Lis-le **en entier** + l'audit DB §2 avant
> tout code.
>
> Date de rédaction : **2026-05-26** fin de session WIP.

---

## 1. TL;DR

La session précédente (2026-05-26) a livré le **chantier D complet**
(slug verbeux + topics multi-source + UI badges) puis le **chantier F**
(theme matcher pool topics + UI 3 sections) sur la branche
`coin-richness/p3-schema`.

**État actuel cohorte 19** :
- 19 coins, slugs verbeux dérivés de `commemorated_topic` Numista
  (ex: `fi-2017-2eur-100-years-of-independence`,
  `de-2007-2eur-50th-anniversary-of-the-treaty-of-rome`)
- Topics multi-source en DB (Numista 6 langs canon + LLM, BCE EN)
- Aliases marché LLM (69 entries)
- BCE images : 12/15 commemos matchés
- eBay run V.3 : 30 quotes, 15/15 coins
- Theme matcher pool désormais topics + titles + aliases (F.1)
- UI CoinDetailPage badges + 3 sections Localisation (F.2)

**À faire cette session** (par priorité) :

1. **V.4 tour visuel final** — pas encore fait, GO/NO-GO scale 524
2. **P10 cleanup** :
   - 3662 orphan `source_images.target_eurio_id` (pré-V.1 leftover)
   - 79 orphan `image_assets.eurio_id`
   - 8 fichiers Supabase data résiduels (cf. kickoff V.3 §7.3)
3. **Bench V.3 parametrizable** — `/bench` actuel consomme le frozen
   gold historique. Le câbler pour accepter un `run_id` arbitraire
   permettrait d'auditer chaque run live, pas juste le gold.
4. **Phase F scale 524** si GO V.4
5. **Anchor bank DINO** — rebuild post-V.1 (376 anchors pré-wipe →
   suggestions sur orphans non-cohort visibles dans review queue)

**Estimation** : V.4 ~1h, P10 ~2-3h, Phase F ~2-3h tournage + audit.

---

## 2. Audit DB cohorte 19 (état figé fin session WIP)

```bash
cd ml && .venv/bin/python /tmp/audit_session.py  # script archivé ci-dessous
```

### 2.1 Per-coin completeness

```
EURIO_ID                                                                NUM BCE I18N TOPIC ALI  MR   PR IMG_N IMG_B QEB
─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
ad-2014-2eur-standard-1st-type                                            1   0    6     0   0  25  195     2     0   0
at-2002-2eur-standard-1st-map                                             1   0    6     0   0  12   90     2     0   0
at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty                1   1    6     7   3   3    8     2     1   3
be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait             1   0    6     0   0   3   21     2     0   0
be-2011-2eur-100th-international-womens-day                               1   1    6     7   6   3    8     2     1   3
de-2007-2eur-50th-anniversary-of-the-treaty-of-rome                       1   0    6     6   4  15   40     2     0   2
de-2007-2eur-state-of-mecklenburg-vorpommern                              1   1    6     7   4  15   40     2     1   2
de-2010-2eur-state-of-bremen                                              1   1    6     7   5  15   40     2     1   2
de-2020-2eur-german-polish-reconciliation                                 1   0    6     6   5  15   39     2     0   3
es-1999-2eur-standard-juan-carlos-i-1st-type-1st-map                      1   0    6     0   0  19  168     2     0   0
es-2016-2eur-old-town-of-segovia-and-its-aqueduct                         1   1    6     7   5   3    6     2     1   2
fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright    1   1    6     7   4   2    4     2     1   2
fi-2017-2eur-100-years-of-independence                                    1   1    6     7   6   2    5     2     1   2
fr-2008-2eur-french-presidency-of-the-council-of-the-european-union       1   1    6     7   4   3    8     2     1   3
fr-2016-2eur-100th-anniversary-of-the-birth-of-francois-mitterrand        1   1    6     7   4   3    9     2     1   2
fr-2018-2eur-100th-anniversary-of-the-end-of-the-first-world-war-bleuet-de-france  1   1    6     7   7   2    2     2     1   1
fr-2018-2eur-simone-veil                                                  1   1    6     7   4   3   33     2     1   1
it-2016-2eur-2200th-anniversary-of-the-death-of-plautus                   1   0    6     6   4   3    6     2     0   1
it-2016-2eur-550th-anniversary-of-the-death-of-donatello                  1   1    6     7   4   3    7     2     1   1
```

**Colonnes** :
- `NUM` / `BCE` : présence dans `coin_source_refs`
- `I18N` : nombre de langs dans `coin_names_i18n` (target = 6)
- `TOPIC` : rows dans `coin_topics` (Numista 6 langs + BCE EN = 7 pour les commemos matchés BCE)
- `ALI` : aliases dans `coin_aliases`
- `MR` : `coin_mint_releases` (variable selon coin)
- `PR` : `mint_release_prices`
- `IMG_N` / `IMG_B` : images Numista/BCE en DB
- `QEB` : quotes eBay (`coin_market_quotes` source='ebay_browse')

### 2.2 Coins sans BCE (3 unmatched)

- `de-2007-2eur-50th-anniversary-of-the-treaty-of-rome` — joint-issue, page BCE séparée
- `de-2020-2eur-german-polish-reconciliation` — translation "kniefall" vs "german-polish" incompatible
- `it-2016-2eur-2200th-anniversary-of-the-death-of-plautus` — "plauto" IT vs "plautus" EN

Statut : P10-B finding, géré par `MANUAL_BCE_OVERRIDES` futur.

### 2.3 Orphans (cleanup TBD)

- ✅ `coin_source_refs.target_id` : 0 orphans
- ✅ `coin_market_quotes.eurio_id` : 0 orphans
- ⚠️ `source_images.target_eurio_id` : **3662 orphans** (pré-V.1 leftover)
- ⚠️ `image_assets.eurio_id` : **79 orphans**

Pas critique pour run V.3, mais nuit à la lisibilité des stats globales.
Cleanup : `DELETE FROM source_images WHERE target_eurio_id NOT IN (SELECT
eurio_id FROM coins) AND run_id != '059dc8d90dad42558e3c6319a722fd35'`
(garder le run actif).

### 2.4 eBay run V.3 état

```
run_id        059dc8d90dad42558e3c6319a722fd35
status        success
n_calls       12
n_raws_added  3014
n_crops_added 1678
source_images 3209 (resolved=2883, NULL=326)

image_assets by resolution_status:
  needs_review           1678

review_queue:
  open  lot      1235
  open  single   443
```

**Quotes générés** : 30 (15 coins × 1-3 conditions) — voir per-coin
table §2.1 colonne QEB.

---

## 3. Ce qui marche end-to-end

### 3.1 Pipeline fetch Numista → DB
- Refetch `--nids-file state/cohort_validation_19.txt` (cache hits)
- Writer écrit : coins, mint_releases, prices, observations, images,
  i18n EN+FR, topics EN+FR, source_refs, design_groups, variants
- Future-proof : tout nouveau refetch populate i18n+topics automatiquement

### 3.2 Pipeline BCE → DB
- `python -m sources.bce.cli --force`
- Adapter `_match_entry` symmetric score : 12/15 commemos matchés
- Writer écrit : coin_canonical_images (source=bce_official),
  coin_source_refs, coin_topics (source=bce_official, lang=en)

### 3.3 Pipeline eBay → DB
- `python -m sources.cli --source ebay --batch 12`
- Discovery groupée (denom × country × year)
- Theme matcher pool **3 couches** : i18n titles + aliases + topics
  verbeux (F.1)
- Re-resolve sans re-fetch via `/tmp/reresolve_ebay.py` après
  mise à jour vocabulaire
- price_aggregate écrit `coin_market_quotes` source='ebay_browse'

### 3.4 Admin Vue
- `/coins?fv=2` — liste, card titles = `coinDisplayName(coin)` verbeux
- `/coins/{eurio_id}` :
  - H1 = topic Numista verbeux FR
  - Badge NUMISTA inline
  - Badge BCE topic ligne suivante (gold)
  - Section Localisation : 3 sections (titres / topics / aliases)
- `/sources/ebay/runs/{run_id}` :
  - Tab Breakdown : per-eurio table avec couverture multi-source
  - Tab Logs/Entonnoir : funnel + drill-down rejets
- `/bench` (post-V.1 historique frozen, pas le run V.3)

### 3.5 Tests
- `cd ml && .venv/bin/python -m pytest tests/ -q -k "numista or cohort or i18n or topic or theme or matcher"` → tous verts
- Note : 3 tests pré-existants cassent (test_lab_api, augmentation) —
  résidus Supabase P10-C, pas lié au chantier D/F

---

## 4. Sources of truth (rappel architectural)

### 4.1 Trois couches vocabulaire theme matcher

| Couche | Table | Source-of-truth | Volume cohorte 19 |
|---|---|---|---|
| Titres i18n | `coin_names_i18n` | Numista API FR+EN canon + LLM DE/IT/ES/NL | 114 rows |
| Topics verbeux | `coin_topics` | Numista commemorated_topic FR+EN + LLM DE/IT/ES/NL + BCE feature EN | 102 rows |
| Aliases marché | `coin_aliases` | LLM market vocab + acronymes mined | 69 rows |

**Toutes les 3 sont poolées par `_theme_match_state`** (F.1).

### 4.2 Images canoniques

- Numista : URLs en DB (`coin_canonical_images.url`), pas de local files
- BCE : binaires WebP local sous `ml/canonical_images/{eurio_id}/obverse_bce.webp`
  + row DB avec `local_path` (depuis chantier 1)
- Service via `/referential/canonical/{eurio_id}/{role}` avec fallback
  chain numista_api → bce_official → bce_comm → unknown

### 4.3 Multi-source tables (FK source_registry)

`coin_canonical_images`, `coin_source_refs`, `coin_credits`,
`coin_observations`, `coin_market_quotes`, `coin_aliases`,
`coin_names_i18n`, `coin_topics` — toutes ont `source` FK
`source_registry(id) ON DELETE RESTRICT`.

10 registry entries seedées (`numista_api`, `bce_official`, `mdp`,
`lmdlp`, `wikipedia`, `ebay_browse`, `2euros_org`, `bundesbank`,
`eurio_derived`, `manual`).

---

## 5. Ordre de lecture

1. Ce kickoff (5 min)
2. `ROADMAP-DB.md` §0 progress log (5 min)
3. `SESSION-KICKOFF-V3-V4.md` §4-5 V.3/V.4 (5 min) — encore valide
4. Mémoires :
   - `feedback_sqlite_only_doctrine.md`
   - `feedback_chunk_audit_flow.md` — chunk-by-chunk validation
   - `project_coin_richness_prep_done.md`
   - `project_coin_richness.md`

---

## 6. Findings non bloquants (P10-*)

### 6.1 Bench page consomme frozen gold uniquement (P10-F)

`/bench` lit `state/discovery_bench/theme_match_gold.jsonl` (gold
figé BE 2017-2021, 196 listings). Ne consomme PAS un `run_id`
paramétrable.

**Chantier potentiel** : refactor `bench_routes.py` pour accepter un
`?run_id=X` qui remplace le gold path. Permet d'auditer le run V.3
en live au lieu d'un gold historique.

### 6.2 Review queue thumbs vides pour orphans hors-cohorte (P10-G)

`/review/manual` montre des DINO suggestions avec thumbs vides pour
des coins absent de cohorte 19 (ex: `ad-2023-2eur-summer-solstice-...`).

**Cause** : le DINO anchor bank `foundation_anchors_2eur_commemo.npz`
contient 376 anchors d'une cohorte pré-wipe. Le SELECT sur `coins`
ne trouve pas → `obverse_url=None` → thumb vide.

**Fix** : rebuild anchor bank depuis cohorte 19 actuelle :
```bash
go-task ml:dino-anchors:build -- --force
```

Ou attendre Phase F (scale 524) qui couvrira le bank entier.

### 6.3 BCE adapter scrape uniquement .en.html (P10-H)

BCE topic en DB est en EN uniquement. La page FR (`.fr.html`)
contient des features traduits ("Dessin commémoratif : 100e
anniversaire..."). Future : scrape les deux pages, populate
`coin_topics` source=bce_official lang=fr.

Pour l'instant le LLM ne traduit PAS les BCE topics (workflow
existant ne fait que Numista). À étendre si nécessaire.

### 6.4 8 fichiers Vue résiduels Supabase (P10-C)

Toujours pendant. Cf. `SESSION-KICKOFF-V3-V4.md` §7.3 :
```
features/coins/composables/useArbitrage.ts
features/augmentation/composables/useStagedCoins.ts
features/confusion/composables/useConfusionMap.ts
features/audit/pages/AuditPage.vue
features/review/composables/useCoinsSearch.ts
features/sets/composables/useCoinSeries.ts
features/sets/composables/useCriteriaPreview.ts
features/sets/components/CuratedMembersPicker.vue
```

Plus l'auth (Login, AuthCallback, router.ts).

---

## 7. Commits notables session WIP (2026-05-26)

```
68dc290  E.1 schema coin_topics
4e5c574  E.2 slug verbeux + Numista topic
6b8dd32  E.3a-b wipe + refetch + remap + re-promote BCE
a7eb378  E.4 BCE pipeline écrit coin_topics
19f2573  E.5 (commit message — manual i18n LLM topics)
b59b633  Phase B+C i18n LLM 4 langs + re-resolve eBay
ee9259f  E.6 UI CoinDetailPage badges multi-source topics
da6d75e  E.7 display_name verbose du Numista topic
2e6dc3e  E.8 aliases cohorte 19 + cleanup orphans i18n
00c005b  F.1 theme matcher pool coin_topics
7305af0  F.2 UI 3 sections (titres/topics/aliases)
```

Branche : `coin-richness/p3-schema`.
Backup : `ml/state/eurio.db.bak-pre-chantier-d-2026-05-26T13-39-07Z`.

---

## 8. Commandes utiles

```bash
# Audit DB cohorte 19
cd ml && .venv/bin/python /tmp/audit_session.py    # script ad-hoc

# Refetch Numista (cache hits)
.venv/bin/python -m scripts.refetch_numista_2eur \
  --nids-file state/cohort_validation_19.txt --apply

# Re-promote BCE
.venv/bin/python -m sources.bce.cli --force

# eBay run (groupée par discovery group)
.venv/bin/python -m sources.cli --source ebay --batch 12 --force

# Re-resolve eBay sur source_images existants (sans re-fetch)
.venv/bin/python /tmp/reresolve_ebay.py
.venv/bin/python /tmp/reprice.py

# Imports LLM
.venv/bin/python -m scripts.import_llm_translations
.venv/bin/python -m scripts.import_llm_topics

# Mine aliases
.venv/bin/python -m scripts.mine_coin_aliases
.venv/bin/python -m scripts.llm_coin_aliases ingest

# Tests par scope
.venv/bin/python -m pytest tests/ -q -k "numista or cohort or i18n or topic or theme"
```

---

## 9. URLs admin

```
http://localhost:5173/coins?fv=2                       # liste
http://localhost:5173/coins/{eurio_id}                 # détail (H1 verbose + badges)
http://localhost:5173/sources/ebay/runs/059dc8d90dad42558e3c6319a722fd35   # run V.3 breakdown + funnel
http://localhost:5173/bench                            # bench gold frozen historique
http://localhost:5173/review/manual                    # review queue (thumbs vides pour orphans = normal)
```

---

## 10. Mémoires à sauver (post-session)

- `feedback_chantier_d_recipe.md` — Pattern wipe+refetch+remap pour
  renames eurio_id (mapping JSON + UPDATE non-FK colonnes + cascade
  delete + re-INSERT).
- `project_coin_richness_chantier_d_done.md` — Slug verbeux + topics
  multi-source + UI badges livrés. Theme matcher pool 3 couches.

---

## 11. État final attendu fin session prochaine

- ✅ V.4 tour visuel réalisé + décision GO/NO-GO scale 524
- ✅ Au moins 1 P10 cleanup (orphans OU anchor bank rebuild)
- ✅ Optionnel : `/bench` paramétrable run_id (P10-F)
- ✅ ROADMAP §0 updated
- ✅ Backup post-tour visuel posé
