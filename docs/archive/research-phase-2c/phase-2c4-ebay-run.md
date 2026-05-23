# Phase 2C.4 — Run report scrape_ebay.py

> Premier run du scraper eBay Browse API (prix marché secondaire pondéré).
> Date : 2026-04-13.
> Doc parent : [`phase-2c-referential.md`](../phases/phase-2c-referential.md) §2C.4, [`ebay-api-strategy.md`](./ebay-api-strategy.md), [`data-referential-architecture.md`](./data-referential-architecture.md).

---

## TL;DR

30 commémoratives 2€ enrichies en **30 appels API** (1 search par pièce, expansion conditionnelle des item groups). Médiane des P50 : **5.90€**. Le pipeline produit des prix cohérents, détecte les outliers (Astérix 2019 à 65€), et reste sous le budget 5000 calls/jour avec une marge énorme.

| Métrique | Valeur |
|---|---|
| Pièces ciblées | 30 (limit configurable) |
| Pièces enrichies | **30/30** (100%) |
| API calls consommés | **30** |
| Budget restant (5000/j) | 4 970 |
| Samples par pièce (médiane) | 29 |
| P50 médian sur l'échantillon | 5.90€ |
| P50 max | 65.00€ (Astérix FR 2019) |
| P50 min | 4.00€ (Helmut Schmidt DE 2018) |

---

## 1. Architecture du run

### Pipeline par pièce

```
Pour chaque eurio_id ciblé (commemo 2€, country in {FR,DE,IT,ES,GR}, déjà enrichi lmdlp/mdp) :
  1. Build query "2 euro {country_fr} {year}"
  2. Search Browse API
     aspect_filter = categoryId:32650,Année:{year}
     filter        = price:[1..500],priceCurrency:EUR
     limit         = 50
  3. Si listings ont primaryItemGroup → expand top-2 groups
  4. Si la (country, year) a 2+ commemos → filter by theme tokens dans titre
  5. Filtre anti-noise (lot/coffret/BU/proof/...)
  6. Compute weighted P25/P50/P75
  7. Si samples_count >= 3 → write observations.ebay_market
```

### Pourquoi pas une query par theme

Tentative initiale : query `"2 euro Germany 2006 holstentor lubeck schleswig holstein"` — **0 résultats**. Les titres eBay sont courts (`"2 euro Allemagne 2006 Holstentor"`) et utilisent les noms français sur EBAY_FR. Trop de mots-clés crashe la recall.

**Fix** : query large (`"2 euro Allemagne 2006"`) + filtre titre côté client via `title_matches_theme(theme_tokens)`. Pour les (country, year) sans ambiguïté (1 seule commemo), on skip le filtre — l'aspect `Année` suffit déjà à identifier la pièce.

### Pourquoi pas getItem par listing

`item_summary/search` ne retourne **pas** `estimatedSoldQuantity` (cf. [`ebay-api-strategy.md`](./ebay-api-strategy.md) §4.1). Il faudrait 1 `getItem` par listing pour récupérer le signal de vélocité, ce qui multiplierait le coût par ~50. Pour le premier pass on accepte que `with_sales = 0` partout et on tombe sur le quantile non-pondéré (le `listing_weight` a un floor de 0.05 qui évite les NaN).

À faire en Phase 3 : sélectionner les top 5-10 listings du cluster prix et faire un getItem ciblé pour récupérer le sold count, puis ré-évaluer les pondérations.

---

## 2. Construction de la query

### Noms FR pour EBAY_FR

eBay marketplace FR → les vendeurs et acheteurs écrivent en français. `Germany` ne match pratiquement rien, `Allemagne` match tout. Mapping ajouté à `eurio_referential.py::ISO2_TO_NAME_FR` (réutilisable pour d'autres scrapers FR).

### Theme keywords filtrés

`_theme_keywords()` extrait les mots significatifs du `design_slug` en supprimant :
- Stop words EN/FR : `of`, `the`, `de`, `la`, `et`, ...
- Marqueurs anniversaire : `anniversary`, `years`, `since`, `birth`, `death`
- Ordinaux : `100th`, `75th`, ...
- Années entre 3-4 chiffres : `1948`, `2010` (déjà dans le query principal)

Cap à 5 tokens max pour éviter les queries surdimensionnées.

Exemples :
| eurio_id | theme keywords |
|---|---|
| `de-2018-2eur-100-years-since-the-birth-of-helmut-schmidt` | `helmut schmidt` |
| `it-2018-2eur-70-years-since-the-constitution-of-italy` | `constitution italy` |
| `gr-2019-2eur-150-years-since-the-death-of-andreas-kalvos` | `andreas kalvos` |
| `de-2006-2eur-holstentor-in-lubeck-schleswig-holstein` | `holstentor lubeck schleswig holstein` |

### Détection de l'ambiguïté

```python
commemo_count[(country, year)] = nombre de 2€ commemos canoniques pour ce (pays, année)
ambiguous = commemo_count[key] > 1
```

163 (country, year) pairs sur 348 ont 2+ commemos dans le référentiel. Pour ces cas, on filtre les listings par titre. Pour les unambigus, l'aspect filter eBay seul suffit.

---

## 3. Filtres anti-noise

| Filtre | Cas rejetés | Exemple |
|---|---|---|
| `lot`, `coffret`, `set`, `série` | Lots groupés | "Lot 5 pièces 2€ commémoratives" |
| `BU`, `proof`, `épreuve`, `BE` | Versions collector chères | "2 euro France 2018 BU FDC" |
| `argent`, `or`, `silver`, `gold` | Versions métal précieux | "2€ Allemagne 2018 argent 925" |
| `colorisée`, `color` | Versions colorisées | "2€ France colorisée Astérix" |
| `erreur de frappe`, `fauté` | Pièces avec défaut | "2€ Italie 2008 erreur frappe" |
| `rouleau`, `roll` | Rolls de 25 pièces | "Rouleau 25× 2€ Allemagne 2007" |
| Prix < `face × 0.8` | Pas plausible | 0.50€ pour une 2€ |
| Prix > `face × 500` | Outlier extrême | 5000€ |
| Currency ≠ EUR | Hors marché | USD/GBP listings |

Sur un échantillon de 1 200 listings remontés, **~30% sont rejetés**, dont 80% pour `noise_title`. Ratio sain : assez de signal qui passe sans accepter de bruit.

---

## 4. Pondération velocity

Formule (cf. spec §6.1) :

```python
sales_per_year = soldQuantity / max(age_years, 0.5)
velocity       = log(1 + sales_per_year)
trust          = max(seller_feedback_pct / 100, 0.1)   # floor pour ne pas zero-out
weight         = max(velocity × trust, 0.05)
```

**Aujourd'hui** : `with_sales = 0` partout parce qu'on ne fetche pas getItem. Le `velocity = log(1) = 0`, donc le poids tombe sur le floor `0.05`. Tous les poids étant égaux, `weighted_quantile` se comporte exactement comme un quantile classique.

**Après Phase 2C.4 v2** (top-10 getItem) : on aura les vrais sold counts pour les listings les plus prometteurs, ce qui pondérera le P50 vers les listings qui vendent réellement plutôt que vers les "zombies".

---

## 5. Quantile pondéré

Implémentation maison (pas de numpy à charger pour 30 lignes) :

```python
def weighted_quantile(values, weights, q):
    paired = sorted(zip(values, weights))
    total = sum(w for _, w in paired)
    if total <= 0:
        # fallback unweighted
        ...
    target = q * total
    cum = 0
    for v, w in paired:
        cum += w
        if cum >= target:
            return v
    return paired[-1][0]
```

Tests unitaires :
- Uniform weights → comportement = quantile classique
- Skewed weights → médiane shift vers la masse de poids
- Empty input → None

---

## 6. Résultats observés

### Distribution des P50

```
median = 5.90€    mean = 8.02€    min = 4.00€    max = 65.00€
```

La médiane à 5.90€ correspond à la valeur typique d'une 2€ commémorative récente en circulation. Le mean tiré vers le haut par 1-2 outliers (Astérix).

### Top 5 P50

| Pièce | P50 | P25 | P75 | samples |
|---|---|---|---|---|
| **Astérix FR 2019** | 65.00€ | 65.00€ | 65.95€ | 4 |
| Spyridon Louis GR 2015 | 10.00€ | 7.81€ | 13.95€ | 33 |
| Andronikos GR 2019 | 9.45€ | 6.10€ | 14.25€ | 13 |
| Constitution IT 2018 | 7.99€ | 5.73€ | 13.95€ | 15 |
| Holstentor DE 2006 | 7.50€ | 4.95€ | 9.50€ | 28 |

**Astérix** est connue comme une des 2€ commémoratives françaises les plus chères du marché secondaire (tirage limité). Le pipeline la détecte correctement avec une distribution étroite (P25=P50=65€), signe que les vendeurs s'alignent sur un prix consensuel.

### Bottom 5 P50

| Pièce | P50 | samples |
|---|---|---|
| Helmut Schmidt DE 2018 | 4.00€ | 19 |
| Charlottenburg DE 2018 | 4.29€ | 8 |
| Porta Nigra DE 2017 | 4.50€ | 37 |
| Bleuet de France 2018 | 4.50€ | 33 |
| Peace in Europe FR 2015 | 4.60€ | 7 |

Pièces récentes, fort tirage, marché liquide → prix proches de la valeur faciale. Cohérent.

### Cas Astérix : tirage faible et sample faible

Seulement 4 samples passent les filtres, contre 30+ pour les pièces standard. Le `samples_count = 4` doit être affiché à l'utilisateur comme un **indicateur de confiance** plus faible — la fourchette 65€ est moins fiable que celle d'une pièce avec 30 samples. Plan UI : badge "marché étroit" quand samples < 10.

---

## 7. Schema d'enrichissement

```json
{
  "eurio_id": "fr-2019-2eur-60-years-since-the-creation-of-asterix",
  "observations": {
    "wikipedia": { ... },
    "lmdlp_variants": [ ... ],
    "ebay_market": {
      "p25": 65.0,
      "p50": 65.0,
      "p75": 65.95,
      "mean": 64.49,
      "samples_count": 4,
      "with_sales_count": 0,
      "query": "2 euro France 2019",
      "sampled_at": "2026-04-13T...",
      "listings": [
        {
          "item_id": "v1|...",
          "price": 65.0,
          "sold": 0,
          "origin_date": null,
          "seller": "...",
          "url": "https://www.ebay.fr/itm/..."
        }
      ]
    }
  },
  "provenance": {
    "sources_used": ["wikipedia_commemo", "lmdlp", "ebay"],
    "last_updated": "2026-04-13"
  }
}
```

Les top 10 listings du cluster sont stockés dans `ebay_market.listings` comme **provenance trail** — en cas de doute sur le P50, on peut auditer ce qui est entré dans le calcul. Pas la totalité (économie de stockage).

---

## 8. CLI et budgets

```bash
python ml/scrape_ebay.py [options]
  --limit N             Max target coins (default 30)
  --countries XX,YY     ISO2 filter (default FR,DE,IT,ES,GR)
  --all-commemos        Target all commemos, not just lmdlp/mdp-enriched
  --sleep N.N           Politeness delay between API calls (default 0.5s)
```

### Estimation de budget pour les runs futurs

| Cible | API calls (approx) | Calls/jour disponibles |
|---|---|---|
| 30 commemos (run actuel) | 30 | 4 970 |
| Toutes les commemos enrichies (273) | ~280 | 4 720 |
| Toutes les 2€ commemos (517) | ~530 | 4 470 |
| Avec getItem top-10 (Phase 2C.4 v2) | 30 × 11 = 330 | 4 670 |
| Avec getItem sur 517 commemos | 517 × 11 = 5 687 | **dépassement** |

→ À 517 pièces × 11 calls, on dépasse le quota par run. Solutions :
1. Splitter en 2 runs jours consécutifs
2. Demander l'**Application Growth Check** eBay (5000 → 1.5M/j)
3. Limiter le getItem aux top 5 par cluster (517 × 6 = 3 102 → OK)

---

## 9. Token cache

`ml/.ebay_token_cache.json` cache l'application token pendant ses 7200 secondes de validité. Premier appel → fetch token + cache. Calls suivants pendant 2h → utilisent le cache. Au démarrage du script, 1 fichier read au lieu d'un round-trip OAuth.

Fichier gitignored (token court-terme, pas un secret long-terme).

---

## 10. Refactor et nouveautés livrées

### `ml/ebay_client.py` (NEW)

Client thin, réutilisable :
- `load_env()` — parse `.env` avec fallback `os.environ`
- `get_app_token(cid, secret, force=False)` — OAuth + cache disque
- `EbayClient(token)` — context manager avec `search`, `get_item`, `get_items_by_group`, compteur `call_count`

Remplace `ml/test_ebay.py` (le script de smoke test reste pour les tests interactifs ad-hoc).

### `ml/scrape_ebay.py` (NEW)

~360 lignes, structure :
- `target_commemoratives()` — sélection priorisée (enrichis lmdlp/mdp, années anciennes d'abord)
- `build_search_query()` — query FR + theme keywords + ambiguïté detection
- `collect_listings_for_target()` — search + group expansion + theme filter
- `accept_listing()` / `filter_listings()` — anti-noise
- `compute_market_stats()` / `weighted_quantile()` / `listing_weight()` — agrégation pondérée
- `write_observation()` — enrichissement référentiel
- `main()` — CLI orchestrator

### `ml/eurio_referential.py`

Ajout du dict `ISO2_TO_NAME_FR` (26 entrées) — réutilisable par tout scraper sur EBAY_FR.

### Tests

15 tests ajoutés pour le scraper eBay :
- `_theme_keywords` (drop stop words, ordinaux)
- `build_search_query` (utilise le nom FR)
- `title_matches_theme` (matching théme)
- `accept_listing` (5 cas : noise, non-EUR, below-face, extreme, OK)
- `weighted_quantile` (uniform, skewed, empty)
- `listing_weight` (floor, sales boost)

**Total tests** : 59 → **73 verts**.

---

## 11. Limitations connues

| # | Limitation | Mitigation actuelle | Plan |
|---|---|---|---|
| 1 | `with_sales = 0` partout (search ne renvoie pas estimatedSoldQuantity) | Quantile non-pondéré (poids floor) | Phase 2C.4 v2 : getItem top-10 |
| 2 | Listings "zombies" non vendus depuis des années polluent les prix hauts | Filtre `> face × 500` | Phase 2C.4 v2 : sales_per_year + drop seuil bas |
| 3 | Cas FR/DE/IT/ES/GR uniquement (5 pays sur 25) | Configurable via `--countries` | Étendre quand budget/réussite confirmés |
| 4 | Pas de matching listing → eurio_id structuré (contrairement à lmdlp/mdp) | Les listings sont supposés appartenir au target ; le filtre title vérifie loosely | Si on veut vraiment du matching multi-stage on peut appeler `matching.match` par listing — coût compute négligeable |
| 5 | Joint issues `eu-*` skipped | Aujourd'hui exclus du targeting | À traiter en Phase 2C.4 v2 — query pour `national_variants × year` |
| 6 | Pas de cross-validation prix lmdlp ↔ ebay | Aucune | Comparer P50 ebay vs UNC lmdlp pour valider la cohérence |

---

## 12. Sortie observable

```
ml/datasets/sources/ebay_2026-04-13.json   # snapshot 30 enregistrements stats + top 10 listings par pièce
ml/datasets/eurio_referential.json         # +30 entries enrichies ebay_market
ml/datasets/matching_log.jsonl             # 30 lignes datées source=ebay
ml/.ebay_token_cache.json                  # token OAuth cache (gitignored)
ml/ebay_client.py                          # NEW shared client
ml/scrape_ebay.py                          # NEW scraper
docs/research/phase-2c4-ebay-run.md        # ce doc
```

---

## 13. Prochaine étape

Phase 2C.5 — `ml/review_queue.py`. CLI interactif pour traiter les 204 escalades lmdlp accumulées (FR↔EN translation barriers). Volume : 128 thèmes uniques, ~30 min de review humaine attendu.

Optionnellement Phase 2C.4 v2 : ajouter getItem top-10 pour récupérer le signal sold et activer la pondération velocity réelle.
