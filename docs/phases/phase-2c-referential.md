# Phase 2C — Référentiel de données canonique

> Objectif : construire le référentiel canonique des pièces euro d'Eurio, indépendant de toute source externe, et la pipeline de matching multi-sources qui l'enrichit.
> **Prérequis** : avoir lu [`docs/research/data-referential-architecture.md`](../research/data-referential-architecture.md) — c'est le document d'architecture complet. Cette phase est son implémentation.

---

## Contexte

Eurio a besoin d'une source de vérité pour identifier les pièces. Les sources externes (Numista, eBay, lamonnaiedelapiece, Monnaie de Paris) sont hétérogènes et peuvent disparaître. Le référentiel Eurio est :

- **Canonique** : bootstrapé depuis la liste officielle BCE/JOUE
- **Indépendant** : aucune source externe ne peut l'invalider
- **Résilient** : si une source disparaît, le reste continue
- **Enrichi** : chaque source ajoute ses propres observations sans écraser les autres
- **Auditable** : chaque décision de matching est loggée

Cette phase doit être terminée **avant** la Phase 3 (coffre), parce que le coffre s'appuie sur les prix, qui s'appuient sur le référentiel.

---

## 2C.1 — Bootstrap du référentiel

### Contexte

Recherche préparatoire terminée — voir [`docs/research/referential-bootstrap-research.md`](../research/referential-bootstrap-research.md). Conclusions :
- **Wikipedia est la source primaire** (plus complet, couvre 2026, intègre micro-états, wikitables ingérables en une ligne via `pandas.read_html`)
- **BCE est source de validation** (autorité, descriptions officielles, URLs images)
- **Scope réel ~3 600 entrées**, pas 500 — la circulation standard représente 85% du volume
- **5 émissions communes** au total : 2007, 2009, 2012, 2015, 2022 (aucune en 2025/2026)

Le bootstrap est **splitté en deux sous-phases** pour livrer rapidement les commémoratives et débloquer les scrapers suivants, puis compléter avec la circulation.

---

### 2C.1a — Bootstrap commémoratives + communes + états tiers

#### Livrable
`ml/datasets/eurio_referential.json` contenant ~610 entrées : toutes les 2€ commémoratives 2004-2026 (21 pays + 4 états tiers) + 5 entrées canoniques pour les émissions communes.

#### Étapes

1. **Script `ml/bootstrap_referential.py`**
   - Fetch `https://en.wikipedia.org/wiki/2_euro_commemorative_coins` avec User-Agent Eurio identifié
   - Sauver le HTML brut dans `ml/datasets/sources/wikipedia_commemo_YYYY-MM-DD.html`
   - Parser via BeautifulSoup : identifier les sections annuelles, extraire les wikitables par année
   - Pour chaque entrée : extraire pays, thème, volume, date d'émission, description
   - Compute `eurio_id` canonique via `ml/eurio_referential.py::compute_eurio_id()`

2. **Modélisation des émissions communes — Option A retenue**
   - 5 entrées canoniques `eu-YYYY-2eur-{slug}` uniques
   - `identity.national_variants` = liste des pays participants (ex: `["AT", "BE", "DE", ...]`)
   - Les volumes par pays iront dans `observations.mintage.by_country` quand disponibles
   - **Pas** d'entrées filles par pays (évite d'alourdir le référentiel inutilement)

3. **États tiers**
   - Vatican, Monaco, Saint-Marin, Andorre intégrés dans la même table Wikipedia
   - Flag `identity.collector_only = true` pour Vatican/Monaco (volumes circulation quasi nuls)

4. **Bulgarie 2026**
   - Doit apparaître dans Wikipedia (première année d'émission BG)
   - À vérifier dans le snapshot

5. **Cross-validation BCE (optionnelle à ce stade)**
   - Fetch les pages BCE `comm_YYYY.en.html` pour les années où elles existent (2004-2025)
   - Comparer volumes et descriptions
   - Logger les divergences dans `ml/datasets/sources/divergences_YYYY-MM-DD.jsonl`
   - Résolution : BCE fait foi pour les volumes, Wikipedia pour la couverture 2026

#### Critères d'acceptation

- [ ] `ml/datasets/eurio_referential.json` créé avec ~610 entrées
- [ ] Toutes les 21 nationalités zone euro + 4 états tiers représentées
- [ ] 5 émissions communes cataloguées avec `national_variants`
- [ ] Bulgarie 2026 présente (au moins une commémo)
- [ ] Chaque entrée a `identity` complet, `provenance.first_seen`
- [ ] Zéro entrée avec `needs_review=true`
- [ ] Snapshot HTML brut sauvegardé et versionné dans `sources/`

---

### 2C.1b — Bootstrap circulation standard

#### Livrable
Enrichissement de `eurio_referential.json` avec ~3 000 entrées de pièces de circulation standard (8 dénominations × 21 pays × millésimes disponibles).

#### Étapes

1. **Sources** : 25 pages Wikipedia `{country}_euro_coins` (une par pays/état tiers)
   - Patterns : `French_euro_coins`, `German_euro_coins`, `Bulgarian_euro_coins`, `Vatican_euro_coins`, etc.
   - Mapping complet dans `ml/datasets/country_mapping.json`

2. **Script `ml/bootstrap_circulation.py`**
   - Fetch chaque page (parallélisé avec `httpx.AsyncClient`, max 5 concurrents par politesse)
   - Parser la table "Circulating mintage quantities" (volumes par année × dénomination)
   - Pour chaque (pays, année, dénomination) avec volume > 0 : créer une entrée `{country}-{year}-{face_code}-standard`

3. **Cas spéciaux**
   - Pièces à variantes d'atelier (Allemagne 5 ateliers A/D/F/G/J) : **une seule entrée par (pays, année, dénomination)**, les variantes d'atelier vont dans `identity.mint_variants` si pertinent
   - Pays à deux séries (France change de design 1€/2€) : entrées distinctes avec `design_slug` différent
   - Micro-états : seulement les combinaisons qui existent réellement dans la table mintage

4. **Merge dans le référentiel existant** (créé en 2C.1a)
   - Conserver toutes les entrées commémoratives déjà présentes
   - Ajouter les entrées circulation en conservant leur `provenance.first_seen`
   - Ne jamais écraser une entrée existante

#### Critères d'acceptation

- [ ] ~3 000 entrées circulation ajoutées au référentiel
- [ ] Tous les pays zone euro + états tiers couverts
- [ ] Pas de produit cartésien mécanique (micro-états gérés via table mintage réelle)
- [ ] Variantes de design France (deux séries) distinguées
- [ ] Référentiel total ~3 600 entrées final

---

## 2C.2 — Scraper lamonnaiedelapiece.com

### Livrable
`ml/scrape_lmdlp.py` qui paginate l'API WooCommerce Store et enrichit le référentiel.

### Étapes

1. **Exploration de l'API**
   - Endpoint : `https://lamonnaiedelapiece.com/wp-json/wc/store/v1/products?per_page=100&page=N`
   - Paginate jusqu'à épuisement
   - Sauver le dump complet brut dans `ml/datasets/sources/lmdlp_YYYY-MM-DD.json`

2. **Filtrage**
   - Garder : `is_purchasable=true`, catégorie contient "2 euros" OU attributs Nominal Value = "2€"
   - Exclure : séries complètes (nom contient "série", "set", "BU Set"), pièces or/argent d'investissement, blisters multi-pays

3. **Extraction identity**
   - `country` : depuis `categories` (match sur liste des 21 pays)
   - `year` : depuis `categories` (catégorie millésime) OU depuis SKU (`hr2025amphitheatre` → 2025)
   - `face_value` : depuis `attributes` (Nominal Value)
   - `theme_slug` : depuis le nom du produit (slugification)
   - `mintage` : depuis description HTML (fallback fetch page si besoin)

4. **Matching pipeline**
   - **Stage 1** : chercher un cross-ref Numista dans la description ou attributs (improbable mais on essaie)
   - **Stage 2** : chercher dans le référentiel par `(country, year, face_value)`. Si 1 seul candidat → match
   - **Stage 3** : si 2 candidats (Allemagne 2022 Erasmus + Traité Élysée par ex) → fuzzy match sur le design slug
   - **Stage 5** (Stage 4 désactivé avant Phase 2B) : si pas trancé → push vers `review_queue.json`

5. **Écriture**
   - Pour chaque match réussi : update `cross_refs.lmdlp_sku`, `cross_refs.lmdlp_url`, `observations.lmdlp_current`, `observations.mintage` si présent
   - Écrire une ligne dans `ml/datasets/matching_log.jsonl` pour chaque décision
   - Ne **jamais** modifier `identity` sauf si vide (enrichissement autorisé seulement pour les champs vides)

### Critères d'acceptation

- [ ] Script exécutable one-shot : `python ml/scrape_lmdlp.py`
- [ ] Snapshot immuable écrit dans `ml/datasets/sources/lmdlp_YYYY-MM-DD.json`
- [ ] Référentiel enrichi avec `cross_refs.lmdlp_*` et `observations.lmdlp_current`
- [ ] `matching_log.jsonl` contient une ligne par produit traité
- [ ] `review_queue.json` contient les cas non-résolus avec leur raison
- [ ] Rapport final : nb produits traités, nb matches par stage, nb rejets, nb escalades humaines

---

## 2C.3 — Scraper Monnaie de Paris

### Livrable
`ml/scrape_monnaiedeparis.py` qui enrichit le référentiel avec les prix d'émission officiels français.

### Étapes

1. **Fetch le sitemap XML**
   - `https://www.monnaiedeparis.fr/media/sitemap/sitemap_mdp_fr.xml`
   - Extraire toutes les URLs produit (celles avec `priority=1.0` matchant un pattern coin)

2. **Filtrer**
   - Garder celles qui matchent `2eur-commemorative` OU `euro-commemorative`
   - Garder celles avec `yeardate-YYYY` dans le slug

3. **Scrape chaque fiche**
   - Fetch HTML
   - Extraire le bloc `<script type="application/ld+json">` (Product schema)
   - Parser : name, price, priceCurrency, availability, sku (depuis image filename)

4. **Matching**
   - Même pipeline que 2C.2 (Stages 1, 2, 3, 5)
   - Spécificité : distinguer qualité BU vs BE (Proof) depuis le slug URL
   - Stocker `observations.monnaiedeparis_issue` (prix d'émission, jamais écrasé)

5. **Rate limiting**
   - Ajouter un `time.sleep(0.5)` entre les fetches (politesse)
   - Si 429 ou 5xx, exponential backoff

### Critères d'acceptation

- [ ] Tous les 2€ commémoratives françaises actives sont dans le référentiel avec prix d'émission
- [ ] Prix d'émission BU et BE (Proof) distingués
- [ ] Aucune entrée canonique française créée (toutes doivent matcher le bootstrap JOUE)
- [ ] Cas UNICEF et autres coéditions correctement matchés

---

## 2C.4 — Port du pipeline eBay vers le référentiel

### Livrable
Mise à jour des scripts eBay (`ml/test_ebay*.py` → `ml/scrape_ebay.py`) pour écrire dans le référentiel Eurio.

### Étapes

1. **Réorganiser les scripts eBay**
   - `ml/test_ebay*.py` deviennent `ml/scrape_ebay.py` (script consolidé, propre)
   - Garder une fonction `get_app_token()` réutilisable
   - Fonction `search_ebay(query, aspect_filter, limit)` qui retourne les items bruts

2. **Ajouter le matching**
   - Pour chaque item eBay retourné : essayer de matcher vers le référentiel
   - Challenges : les titres eBay sont sales, manquent de structure
   - Utiliser `aspect_filter=Année:{...}` pour récupérer l'année côté serveur
   - Le pays vient souvent de `categories` ou doit être extrait du titre (regex sur noms de pays)

3. **Agrégation des prix**
   - Pour chaque `eurio_id` touché : collecter N listings (Stages 1-3 + review)
   - Appliquer filtres anti-bruit (lot/coffret/BU/proof dans le titre, P5/P95)
   - Enrichissement top-10 via `getItem` (confirmer sold quantity, itemOriginDate)
   - Calcul `sales_per_year = soldQuantity / age_listing_years`
   - Pondération prix × log(1+sales_per_year) × seller_trust
   - Stocker `observations.ebay_market = {p25, p50, p75, samples_count, sampled_at}`

4. **Limites de budget API**
   - Target : ≤ 4500 appels/jour (buffer sur les 5000 limite)
   - Prioriser les pièces du catalogue POC d'abord, étendre progressivement

### Critères d'acceptation

- [ ] `ml/scrape_ebay.py` existe et remplace les scripts `test_ebay*.py`
- [ ] Pour chaque pièce matchée : `observations.ebay_market` rempli avec P25/P50/P75
- [ ] Taux de matching mesuré et loggé (% items eBay qui trouvent un `eurio_id`)
- [ ] Budget API consommé documenté dans le rapport de run
- [ ] Les scripts `test_ebay*.py` peuvent être supprimés (archivés dans git)

---

## 2C.5 — Review queue et workflow humain

### Livrable
`ml/review_queue.py` — script CLI interactif pour résoudre les cas en escalade.

### Étapes

1. **Format de `review_queue.json`**
   ```json
   [
     {
       "id": "uuid",
       "source": "lmdlp",
       "source_native_id": "de2022erasmus",
       "raw_payload": { ... },
       "candidates": ["de-2022-2eur-erasmus", "de-2022-2eur-traite-elysee"],
       "reason": "stage3_fuzzy_too_close (scores 0.82, 0.79)",
       "created_at": "2026-04-13T...",
       "resolved": false
     }
   ]
   ```

2. **Script interactif**
   - Liste les entrées non-résolues
   - Pour chaque : affiche le produit source, les candidats, les scores, ouvre les URLs dans le navigateur
   - Propose 3 actions : (1) choisir un candidat, (2) créer nouvelle entrée, (3) marquer comme "skip" (produit non-pertinent)
   - Écrit la résolution dans le référentiel + `matching_decisions`
   - Marque l'entrée resolved=true

3. **Pas de UI web pour le POC** — CLI suffit pour un volume attendu < 50 entrées

### Critères d'acceptation

- [ ] `review_queue.json` structuré et versionné
- [ ] Script CLI fonctionnel qui traite les entrées une par une
- [ ] Les résolutions mettent à jour le référentiel et loggent la décision
- [ ] Documentation d'usage dans `ml/README.md`

---

## 2C.6 — Activation Stage 4 (après Phase 2B)

### Prérequis
Phase 2B terminée — modèle ArcFace entraîné et exporté en TFLite.

### Livrable
Module `ml/matching/visual_stage.py` qui compute la similarité visuelle entre images produit.

### Étapes

1. **Charger le modèle entraîné**
   - Réutiliser le même modèle MobileNetV3 + ArcFace que pour le scan utilisateur
   - Batch inference côté CPU (pas besoin de GPU pour le matching offline)

2. **Pipeline visuelle**
   - Pour chaque escalade Stage 3 → avant de partir en Stage 5 :
     - Télécharger l'image de la source
     - Télécharger les images des candidats du référentiel
     - Compute embeddings
     - Cosine similarity
     - Si max > 0.85 et unique → match, sinon → Stage 5

3. **Cache des embeddings candidats**
   - Pré-calculer les embeddings de toutes les images du référentiel
   - Stocker dans `ml/datasets/referential_embeddings.npy`
   - Recharger à chaque run pour éviter de re-computer

### Critères d'acceptation

- [ ] Stage 4 activé dans la pipeline de matching
- [ ] Taux d'escalade Stage 5 réduit mesurablement (avant/après comparé)
- [ ] Cache embeddings fonctionnel
- [ ] Tests sur 10 cas connus avec vérité terrain manuelle

---

## 2C.7 — Sync vers Supabase (une fois schema stable)

### Livrable
`ml/sync_to_supabase.py` qui pousse le référentiel JSON vers les tables Supabase.

### Étapes

1. **Créer les tables Supabase** (migration SQL — schema dans le doc d'architecture)
2. **Script de sync** qui lit le JSON et `upsert` dans les tables
3. **Tester l'accès depuis l'app Kotlin** via Supabase client
4. **Définir la cadence de sync** : hebdo manuel pour le POC, cron Edge Function plus tard

### Critères d'acceptation

- [ ] Tables `coins`, `source_observations`, `matching_decisions`, `review_queue` créées dans Supabase
- [ ] Script de sync idempotent (re-run = pas de duplicates)
- [ ] L'app peut lire le référentiel depuis Supabase

---

## Estimation d'effort

| Sous-phase | Effort | Bloquant |
|---|---|---|
| 2C.1 Bootstrap JOUE | 1-2 jours | non |
| 2C.2 Scraper lmdlp | 1 jour | 2C.1 |
| 2C.3 Scraper Monnaie de Paris | 0.5 jour | 2C.1 |
| 2C.4 Port eBay vers référentiel | 1 jour | 2C.1, 2C.2 |
| 2C.5 Review queue CLI | 0.5 jour | 2C.2 |
| 2C.6 Stage 4 visuel | 0.5 jour | **Phase 2B terminée** |
| 2C.7 Sync Supabase | 0.5 jour | Schema stable (~2C.5 terminé) |
| **Total effort** | **~5-6 jours** | |

L'estimation suppose que l'architecture est claire (elle l'est, doc d'architecture écrit), que les APIs externes ne posent pas de surprise majeure, et que Stage 4 n'est activé que plus tard.

---

## Risques

| Risque | Impact | Mitigation |
|---|---|---|
| Le JOUE n'a pas de format scrapable propre | Moyen | Bootstrap manuel depuis Wikipedia "2 euro commemorative coins" en fallback |
| lamonnaiedelapiece change son API WooCommerce | Faible | On a le snapshot brut, on peut re-parser |
| Taux d'escalade Stage 5 trop élevé (>20%) | Moyen | Attendre Stage 4 (visuel) ; entretemps, traiter manuellement |
| Schema JSON évolue souvent pendant le POC | Faible | Git versioné, migration par script Python one-shot si besoin |
| Supabase free tier saturé | Faible | 50k rows de marge, catalogue initial ~1000 rows, marge massive |

---

## Ce que cette phase permet

Une fois Phase 2C terminée :
- **Phase 3 (coffre)** peut s'appuyer sur un référentiel propre pour afficher les prix
- **Phase 4 (gamification)** peut se baser sur les IDs canoniques pour les achievements
- **Phase 5 (polish + beta)** bénéficie d'un backend data robuste et indépendant des sources externes
- **Le scan utilisateur** (phase 2B) peut écrire `collected_eurio_id` dans la collection au lieu d'un ID Numista
