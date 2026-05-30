# LMDLP — schéma de données exploitable (analyse live)

> Source : **La Monnaie de la Pièce** — `https://lamonnaiedelapiece.com`
> Boutique communautaire FR vendant des 2 € commémoratives neuves (UNC / BU / BE)
> par qualité. API publique WooCommerce **Store API** (JSON, pas d'auth).
>
> Analyse réalisée le 2026-05-30 (Chunk 1 du rebuild). Scope retenu :
> **prix + qualité uniquement** → `coin_market_quotes` + `coin_source_refs`.
> Pas de tirage (déjà couvert ailleurs), pas d'image, pas d'observation.

## 1. Endpoint & filtre

```
GET https://lamonnaiedelapiece.com/wp-json/wc/store/v1/products
    ?per_page=100
    &page={n}
    &attributes[0][attribute]=pa_nominale-waarde
    &attributes[0][slug]=2-euro-fr
```

- Filtre **serveur** sur l'attribut « Valeur faciale = 2 € » (le slug technique
  `pa_nominale-waarde` est néerlandais — la boutique est d'origine NL ; le slug
  `2-euro-fr` cible bien les 2 €). Le filtre fonctionne : 851 produits renvoyés.
- Réponse = liste JSON de produits. Pas d'auth, pas de clé.
- User-Agent : `Eurio/0.1 lmdlp-scraper (https://github.com/Musubi42/Eurio)`.

### Pagination & volume

| Header | Valeur (2026-05-30) |
|---|---|
| `X-WP-Total` | **851** produits 2 € |
| `X-WP-TotalPages` | 9 pages à `per_page=100` |

- Paginer jusqu'à `page >= X-WP-TotalPages`. Une page vide (`[]`) coupe aussi.
- **Politesse** (boutique communautaire) : `sleep` 0.3–1 s entre pages.
  ~9 requêtes pour tout le catalogue → coût négligeable, mais on **cache le
  snapshot par jour** (cf. §6) pour qu'un refresh par coin ne re-tape pas 9×.

### Rate-limit / robots

- Aucun header `Retry-After` / `X-RateLimit-*` observé. Pas de quota annoncé.
- Pas de signal de throttling sur l'échantillon. On reste gentil par principe.

## 2. Structure d'un produit (champs exploités)

Exemple réel (`sku=hr2026raunc`) — champs **retenus** en gras :

```jsonc
{
  "id": 12345,
  "name": "2 euros Croatie 2026 &#8211; Radio croate UNC",   // ⚠ entités HTML à unescape
  "sku":  "hr2026raunc",                                      // cryptique (pays+année+thème+qualité)
  "slug": "2-euros-croatie-2026-radio-croate-unc",
  "permalink": "https://lamonnaiedelapiece.com/fr/product/.../",  // ← coin_source_refs
  "type": "simple",            // jamais 'variable' : 1 qualité = 1 produit simple
  "has_options": false,
  "variations": [],            // ⇒ PAS de variations Woo ; le groupage est à NOUS
  "is_purchasable": true,
  "is_in_stock": true,
  "prices": {
    "price": "1999",           // ← entier en unité mineure
    "currency_code": "EUR",
    "currency_minor_unit": 2   // ⇒ 1999 / 10^2 = 19,99 €
  },
  "categories": [              // ← identité : année + pays (libellé FR)
    {"name": "2026"},          // année (4 chiffres)
    {"name": "Pièces / année"},// méta — à ignorer
    {"name": "Pièces / pays"}, // méta — à ignorer
    {"name": "Croatie"}        // pays (nom FR → ISO2)
  ],
  "attributes": [
    {"name": "Qualité",        "terms": [{"name": "UNC"}]},                    // ← condition_raw
    {"name": "Valeur faciale", "terms": [{"name": "2 euro"}]},
    {"name": "Tirage",         "terms": [{"name": "190.000"}]},               // hors scope
    {"name": "Type",           "terms": [{"name": "Pièce 2 euros commémorative"}]}, // ← filtre commemo
    {"name": "Date d'émission","terms": [{"name": "juillet 2026"}]}            // hors scope
  ],
  "images": [{"src": "https://.../...-unc.jpg"}]   // hors scope (pas d'image LMDLP)
}
```

## 3. Identité d'une pièce → matching eurio_id

LMDLP n'expose **pas** d'`eurio_id` ni de `numista_id`. On reconstruit le triplet :

| Dimension | Source dans le produit |
|---|---|
| **country** (ISO2) | catégorie dont le nom ∈ noms de pays FR → ISO2 |
| **year** (int) | catégorie dont le nom matche `^(19\|20)\d{2}$` ; fallback : 4 chiffres dans le SKU |
| **theme_slug** | `name` unescapé, retrait du préfixe « 2 euros {pays} {année} – » + retrait du suffixe qualité, puis `slugify` |

Le **SKU** (`hr2026raunc`) est trop cryptique pour matcher fiablement — on s'en
sert seulement comme `source_ref` / id natif, pas pour l'identité.

- Map FR → ISO2 : **inverser `ml/sources/ebay/queries.py:ISO2_TO_NAME_FR`**
  (tree `sources/`, maintenu) — ne PAS importer `referential/eurio_referential.py`
  (module legacy de l'ancienne archi JSON).
- Matching = **`SlugGroupMatcher` partagé** (extrait de `BceAdapter` au Chunk 2),
  assignation **one-to-one par (country, year)** : N produits LMDLP d'une même
  (pays, année) ↔ au plus N eurio_id distincts, pas de vol d'identité.

## 4. Qualités (le 2ᵉ axe que tu veux : prix **par qualité**)

L'attribut `Qualité` est propre (4 valeurs sur l'échantillon p.1, n=100) :

| `Qualité` (condition_raw) | Sens | n (éch.) |
|---|---|---|
| `UNC` | Uncirculated (sortie de rouleau) | 37 |
| `BU FDC` | Brilliant Uncirculated / FDC (coincard) | 37 |
| `BE Proof` | Belle Épreuve / Proof | 20 |
| `BE Polissage inversé` | Proof polissage inversé | 6 |

→ On lit **l'attribut `Qualité`**, pas le nom (le nom contient parfois
« Coincard » / « Blister » = packaging, bruit pour la qualité).

**Toutes ces qualités sont des états neufs/proof** (jamais circulé). Décision
actée : `condition_normalized = 'unknown'` (on ne fond PAS le prix boutique neuf
dans l'agrégation marché-secondaire eBay `UNC/TTB/TB`). Le label fin vit dans
`condition_raw` et pilote l'affichage « prix boutique par qualité ».

## 5. Filtrage (single commemo)

Rejeter (repris du vieux script, validé) :
- `is_purchasable=false`
- `Type` ne contient pas « commémorative » (vu : 1 « Monnaie normale » à exclure)
- nom préfixé `N x 2 euros…` (multipack), ou deux thèmes séparés par ` + ` (bundle)
- nom/catégorie blacklist : coffret, rouleau, série, set, blister, liste

## 6. Mapping vers le data model (scope prix + qualité)

| Cible | Contenu | Clé / contrainte |
|---|---|---|
| `coin_market_quotes` | **1 row par qualité** : `p50` = prix boutique (`p10=p90=p50`), `sample_size=1`, `condition_raw` = label `Qualité`, `condition_normalized='unknown'`, `source='lmdlp'`, `source_ref`=SKU, `currency='EUR'` | `UNIQUE(source, eurio_id, period_start, condition_raw)` ⇒ 1 pièce = N qualités = N rows |
| `coin_source_refs` | lien identité `source='lmdlp'`, `target_kind='coin'`, `target_id=eurio_id`, ref native = SKU + permalink | axe `refs` de `derive_lmdlp` |

Pas d'agrégation par percentiles (≠ eBay listings→price_aggregate) : la quote LMDLP
est un **prix boutique direct**, écrit tel quel. `period_start/end` = date du run.

### Idempotence / snapshot

- Snapshot brut journalier : `ml/datasets/sources/lmdlp_{YYYY-MM-DD}.json`
  (immutable, ré-parsable offline ; un refresh par coin le même jour réutilise le
  cache plutôt que re-paginer le shop — calque sur le cache HTML BCE).

## 6bis. Matching (mini-chantier 2026-05-30)

### Leviers appliqués

1. **Slugs candidats FR auxiliaires** (`RefCoin.aux_slugs`, additif au matcher
   partagé) : LMDLP libelle en FR abrégé (`10-ans-uem`, `seniors`) là où
   l'`eurio_id` est dérivé de l'anglais. On ajoute, par eurio_id, les slugs des
   titres FR (`coin_names_i18n`), topics (`coin_topics`) et descriptions
   (`coin_descriptions_i18n`) en `lang='fr%'`. Le score d'un candidat = max sur
   tous ses slugs. → 62 % → ~82 %.
2. **Normalisation marque d'atelier allemande** : les 5 ateliers A/D/F/G/J (et le
   combo `ADFGJ`) sont la **même pièce canonique** (1 eurio_id, pas de variante
   atelier au référentiel). On retire le marqueur (préfixe/suffixe) du thème pour
   que tous les ateliers produisent la même clé `(pays, année, thème)` et
   fusionnent leurs prix. → ~82 % → ~94 %.

### Taux réel (one-to-one, dry-run 2026-05-30)

**851** produits → **748** single-commemo → **351 pièces distinctes** (après
fusion ateliers) :

| Issue | n | % |
|---|---|---|
| **Matchées** (eurio_id) | 332 | **94 %** |
| Trou de référentiel (aucun candidat) | 5 | 1 % |
| Échec matching (candidat présent) | 14 | 4 % |

677/709 produits exploitables → quotes. Le matching est **one-to-one strict** :
un eurio_id n'est réclamé que par une clé (pas de double-attribution).

### Résidu (14 échecs) — irréductible au token-overlap

Acronymes / libellés familiers FR sans recouvrement avec aucun candidat
(EN *ni* FR formel) : `uebl`, `10-ans-uem`, `onu`, `seniors`, `erasme`,
`autonomie`, `double-portrait`, `premier-vol`, `jeux-olympiques-tokyo`,
`traite-de-tartu`, `presidence-conseil-ue`, `90-ans-cite-du-vatican`,
`hambourg` (ambigu normal vs mule). → cible d'une petite table d'overrides
manuels (`LmdlpAdapter.overrides`, déjà supportée) ou d'un pass LLM.

Comportement : une pièce non matchée n'a **pas** de quote LMDLP (dégradation
propre, jamais de prix attaché au mauvais eurio_id). Pas de cap silencieux : le
manifest du run liste les eurio_id matchés.

## 7. Observabilité (déjà pré-câblé)

- `backfill_coin_source_status.py:derive_lmdlp` → axes `quotes` + `refs` (déjà écrit,
  valide ce data model).
- `coins_routes.py` → `lmdlp` déjà dans `DISPLAYED_SOURCES` + `has_lmdlp` + panneau.
- **Manque** (Chunks 3-4) : l'adapter `ml/sources/lmdlp/`, `lmdlp_axes()` dans
  `source_status.py`, `refresh_lmdlp_coin` + dispatch `source=='lmdlp'`.
