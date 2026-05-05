# Bloc 2 — eBay strategy v2 : multi-marketplace + i18n + prix lot review (back)

> Plan figé. Implémentation à faire dans une session future.
> Préreq : bloc 1 (`ebay-postfilter-year-kickoff.md`) terminé et validé en
> production sur 1-2 runs.

## Objectifs

1. Augmenter le recall en **scrapant plusieurs marketplaces eBay**, sans
   exploser le quota ni dupliquer les données.
2. Rendre le **post-filter multilingue** en utilisant les noms officiels
   Numista en FR/EN/DE/IT/ES.
3. Préparer côté back une **API d'attribution de prix manuel pendant le
   review d'un lot**, pour ne plus perdre les prix décomposables (cas
   "3 pièces à 15€" → 5€/coin).

## Sous-chantier 2.A — Bootstrap Numista i18n

### Source

Numista expose le même contenu sous différents sous-domaines :

```
fr.numista.com/catalogue/pieces<numista_id>.html  → titre FR
en.numista.com/catalogue/pieces<numista_id>.html  → titre EN
de.numista.com/catalogue/pieces<numista_id>.html  → titre DE
it.numista.com/catalogue/pieces<numista_id>.html  → titre IT
es.numista.com/catalogue/pieces<numista_id>.html  → titre ES
```

Le titre est dans `<h1>`, robuste à scraper (HTML léger).

### Schéma DB

Option simple : nouvelle colonne `coins.names_i18n_json` (TEXT, JSON).

```sql
ALTER TABLE coins ADD COLUMN names_i18n_json TEXT;
-- Contenu : {"fr": "...", "en": "...", "de": "...", "it": "...", "es": "..."}
```

Option propre : table dédiée `coin_names_i18n (eurio_id, lang, name)`. À
choisir au moment de l'implémentation selon ce qui est cohérent avec le
schéma existant.

### Script

`ml/scripts/bootstrap_coin_names_i18n.py` — pour chaque eurio_id, scrape
les 5 sous-domaines, extrait `<h1>`, écrit en DB. Idempotent (skip si déjà
rempli sauf flag `--refresh`).

Coût : ~3000 coins × 5 langues = 15k requêtes. Numista permet ~2000/mois
en API mais le scraping HTML léger n'est pas rate-limité comme l'API.
Throttling 1-2 req/sec pour rester poli, ~2h de run total. À lancer une
seule fois.

### Utilisation downstream

Dans `queries.py`, étendre `_theme_keywords` pour intégrer les tokens
extraits des 5 noms i18n. Le post-filter `title_matches_theme` matche si
le titre eBay contient au moins un token dans n'importe quelle langue.

Cas d'école `bearded-vulture` :
- EN slug : `["bearded", "vulture"]`
- FR Numista : "Andorre - 2 euros 2025 (Gypaète barbu)" → `["gypaète", "barbu"]`
- DE : "Andorra - 2 Euro 2025 (Bartgeier)" → `["bartgeier"]`
- ES : "Andorra - 2 Euros 2025 (Quebrantahuesos)" → `["quebrantahuesos"]`

Union de tous → recall multilingue débloqué.

## Sous-chantier 2.B — Multi-marketplace

### Constat (issu de S3)

- EBAY_GB agit comme meta-marketplace (catch-all cross-border).
- EBAY_<country_origin> donne un boost massif sur les commémos du pays
  (ex: paulskirche +800% sur EBAY_DE).
- L'`item_id` est partagé entre marketplaces pour les listings
  internationaux → notre dédup `(source, source_ref)` UNIQUE filtre les
  doublons sans logique custom.

### Stratégie

Pour chaque eurio_id, faire **2 calls eBay** :
1. **Call principal** sur EBAY_GB (catch-all global, fallback robuste pour
   les pays sans marketplace dédié comme AD).
2. **Call spécialisé** sur EBAY_<country_origin> si le pays a un
   marketplace eBay dédié (FR, DE, IT, ES, NL, BE, AT, IE, …).
   - Skip si pas de marketplace (AD, MC, SM, VA → seul GB).

Coût quota : ×2 sur les commémos avec marketplace dédié. Acceptable étant
donné le quota daily=5000. À paralléliser pour minimiser la latence.

### Implémentation côté code

- `ebay_client.py` : retirer la constante hardcodée `MARKETPLACE = "EBAY_FR"`.
  Passer le marketplace en paramètre du constructeur ou par appel.
- `EBAY_COUNTRY_TO_MARKETPLACE` map (cf. `coin.country` → marketplace) :
  ```python
  {
    "FR": "EBAY_FR", "DE": "EBAY_DE", "IT": "EBAY_IT", "ES": "EBAY_ES",
    "GB": "EBAY_GB", "NL": "EBAY_NL", "BE": "EBAY_FR",  # BE pas de marketplace, fallback FR
    "AT": "EBAY_AT", "IE": "EBAY_IE", "PL": "EBAY_PL",
    # AD, MC, SM, VA, CY, MT, EE, LV, LT, SK, SI, FI, GR, PT, BG, HR, LU →
    # pas de marketplace dédié, fallback GB
  }
  ```
- Adapter eBay : faire les 2 calls, merger les results, dédup item_id en
  mémoire avant retour à l'orchestrateur.

### Logging

Une row `discovery_searches` **par marketplace appelé**. Rendre `endpoint`
plus expressif : `"ebay.browse.search.gb"`, `"ebay.browse.search.de"`.
Counters distincts dans la trace = plus facile à debugger.

## Sous-chantier 2.C — API decide_lot_with_price

### Contexte

Aujourd'hui : un review de lot assigne `crop X → eurio_id Y` mais ne
permet pas de saisir un prix. Conséquence : pour les lots décomposables
("3 fois la même pièce à 15€"), le prix par pièce n'est pas capturé. La
review-queue `decide_lot` API actuelle (`api/review_queue_routes.py`)
prend `{asset_id, eurio_id|reject}`.

### Extension API

Étendre le payload `decide_lot` pour accepter un prix optionnel par crop :

```jsonc
{
  "decisions": [
    {
      "asset_id": "...",
      "eurio_id": "fr-2012-2eur-abbe-pierre",
      "price": 5.0,           // optionnel, en EUR
      "currency": "EUR",      // optionnel, default EUR
      "condition_raw": "..."  // optionnel, hérité du listing si absent
    },
    { "asset_id": "...", "action": "reject", "reason": "non-2€" },
    { "asset_id": "...", "action": "skip" }
  ]
}
```

Côté back :
- Si `price` fourni → INSERT dans `coin_market_quotes` avec
  `(source='ebay', eurio_id, period_start, condition_raw, price, currency)`.
- Idempotence via UNIQUE existante `(source, eurio_id, period_start, condition_raw)`.
- Si `price` absent → comportement actuel (pas de quote pour les lots).

### Schéma à vérifier

`coin_market_quotes` a déjà tous les champs requis. Pas de migration
nécessaire. Juste ajouter le champ `price` optionnel dans le model
Pydantic et la logique de la route.

### Validation

- `price > 0` et `< 10000` (sanity)
- `currency` ∈ {EUR, USD, GBP, …} (whitelist short)

### Impact

Côté front, ce sera l'objet du **bloc 3** (drawer review lot avec input
prix par crop). Le back sera prêt avant.

## Découpage en chunks (proposé)

- **Chunk 2.A.1** : schema (colonne ou table i18n) + migration idempotente.
- **Chunk 2.A.2** : script bootstrap Numista i18n + premier run.
- **Chunk 2.A.3** : refactor `_theme_keywords` + `title_matches_theme`
  pour utiliser les tokens i18n. Tests.
- **Chunk 2.B.1** : refacto `EbayClient` pour passer marketplace en param.
  Map country→marketplace.
- **Chunk 2.B.2** : adapter eBay multi-call + dédup mémoire. Logging
  endpoint distinct.
- **Chunk 2.B.3** : run prod sur 5 eurio_ids variés, vérification
  recall + pas de duplication.
- **Chunk 2.C.1** : extension API `decide_lot` avec champ price.
  Validation + idempotence.
- **Chunk 2.C.2** : tests end-to-end (POST decide_lot avec mix
  price/no-price/reject).

Pas de dépendance entre 2.A, 2.B, 2.C — ordre libre selon disponibilité.
