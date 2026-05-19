# Vision — eBay multi-marketplace

> Pourquoi on bascule de single-marketplace `EBAY_FR` vers GB-global +
> marketplace natif selon l'origine de la pièce, et ce qu'on attend en
> sortie. Lire avant tout autre fichier du dossier.

## Cible end-state

Pour chaque `eurio_id` du référentiel canonique, le pipeline eBay :

1. Fait **toujours** un call sur **EBAY_GB** (catch-all global, sellers
   cross-border y listent en anglais).
2. Fait **en parallèle** un call sur le marketplace de la **langue native
   du pays d'origine** quand cette langue est servie par un marketplace
   eBay dédié (voir `marketplace-map.md`).
3. Dédupe les `itemId` qui apparaissent sur les deux marketplaces (gratuit
   via la contrainte `UNIQUE (source, source_ref)` existante).
4. Construit la query `q` dans la langue native de chaque marketplace
   (FR pour EBAY_FR, DE pour EBAY_DE, …), avec le nom du pays traduit dans
   cette langue.
5. Applique le post-filter theme avec une union d'aliases dans **toutes
   les langues servies** (issues du bootstrap Numista i18n, cf. `language-probe.md`).
6. Journalise 1 row `discovery_searches` par (eurio_id × marketplace) avec
   funnel complet, marketplace utilisé, et URL Browse reconstructible.
7. Affiche côté admin : la stratégie courante dans le pilote, le détail
   par-marketplace dans la run-detail, et le rappel des règles actives
   (NOISE_PATTERNS, prix×face, year policy, theme tokens).

## Constat probe S3 — pourquoi c'est urgent

Le probe `ml/state/probe_ebay_query_strategies_20260504T212313Z.json`
montre sur 5 eurio_ids variés :

| eurio_id | EBAY_FR (baseline) | EBAY_GB | EBAY_DE |
|---|---:|---:|---:|
| `ad-2025-2eur-bearded-vulture` | 49 | **1128** | 1426 |
| `be-2006-2eur-renovation-of-the-atomium-in-brussels` | 83 | **2609** | 98 |
| `fr-2012-2eur-100th-birthday-of-abbe-pierre` | 316 | **7874** | 2302 |
| `de-2024-2eur-175th-anniversary-of-the-paulskirche-constitution` | 184 | 1698 | **81323** |
| `sk-2024-2eur-100-years-of-kosice-peace-marathon` | 65 | **1622** | 285 |

Lecture :
- **EBAY_GB est dominant** pour tout le monde sauf DE (où EBAY_DE écrase
  tout : 81 k vs 1.7 k).
- **EBAY_FR seul** rate 90-99 % des annonces actives selon la pièce.
- Le `total` n'est pas le `recall utile` (beaucoup de bruit avant
  post-filter), mais l'ordre de grandeur prouve qu'on coupe les jambes à
  l'extract en restant sur un seul marketplace.

## Principes non négociables

### P1 — GB toujours, natif si applicable

EBAY_GB est l'épine dorsale. Tout coin reçoit au moins ce call. C'est ce
qui rattrape les pays sans marketplace dédié (AD, MC, SM, VA, …) et les
listings de sellers internationaux qui ciblent un public anglophone.

### P2 — Pas plus de 2 calls de discovery par eurio_id

Quota = 5000 calls/jour. Avec D-22 (`item/{id}` HD systématique), un
eurio_id coûte déjà ~7-10 calls (1 search + 6-9 item/{id}). Multiplier
par 3-4 marketplaces casserait le freshness queue. **Limit V1 = 2 calls
de discovery max** (GB + natif). Pas de US, pas de marketplaces multiples
au-delà.

### P3 — Langue de la requête = langue du marketplace

Pas de query EN sur EBAY_FR (le probe V2_name_en S3 a montré que ça
*dégrade* le recall : BE 2006 passe de 83 à 7). La query suit la langue
native du marketplace ciblé :

- EBAY_FR → `2 euro <pays-FR> <année>`
- EBAY_DE → `2 euro <pays-DE> <jahr>`
- EBAY_IT → `2 euro <pays-IT> <anno>`
- EBAY_ES → `2 euro <pays-ES> <año>`
- EBAY_NL → `2 euro <pays-NL> <jaar>`
- EBAY_GB → `2 euro <pays-EN> <year>` (catch-all)

Le mot "euro" est multilingue accidentellement (idem token chez tous nos
marketplaces cibles).

### P4 — Dédup au niveau item_id, pas au niveau image

`itemId` eBay est stable cross-marketplace (un listing italien apparaît
avec le même id sur EBAY_GB et EBAY_IT). La contrainte
`UNIQUE (source, source_ref)` sur `source_images` filtre déjà les
doublons : la 2e insertion d'un même `ebay_<itemId>_img<N>` est rejetée
par SQLite. On garde juste une trace côté `discovery_searches.found_in`
(quelles marketplaces ont yieldé l'item) pour le debug.

### P5 — Théme-tokens multilingues via Numista i18n

Le bilingual matcher actuel (`THEME_TOKEN_FR_ALIASES` dans
`ml/sources/ebay/queries.py:88`) est hand-curated → fragile et incomplet.
On le remplace par un dict construit à partir du scraping Numista 5
sub-domains (fr/en/de/it/es). Cf. `language-probe.md` §"Bootstrap i18n".

## Anti-objectifs (V1 strict)

- **Pas d'EBAY_US**. Catalogue US-centric, shipping et devises complexes,
  peu de sellers EU y listent leurs euros. Recall marginal, complexité
  importante.
- **Pas plus de 2 marketplaces simultanés**. On peut élargir en V2 si
  signal mesuré (KPI recall encore plafonné après bascule).
- **Pas de bascule marketplace dynamique en fonction du quota**. Si
  remaining < seuil, on stoppe le run via le pre-flight existant (D-27),
  on ne dégrade pas vers GB-only à mi-batch.
- **Pas de probing live des langues**. La langue par marketplace est
  fixée dans `marketplace-map.md` et confirmée par le probe ponctuel
  (`language-probe.md`). Pas de heuristique live qui change selon les
  résultats.
- **Pas de prix multi-devise**. Le filtre `currency != EUR` reste
  (cf. `ml/sources/ebay/filters.py:140`). Un listing sur EBAY_GB en GBP
  sera rejeté `non_eur`. C'est OK — on enrichit les images, le prix EUR
  des sellers continentaux suffit.

## KPI cibles

- **Recall annonces actives** (mesuré sur les 5 eurio_ids du probe S3) :
  ≥ ×5 sur la médiane vs baseline FR-only.
- **Quota par run de 10 eurio_ids** : ≤ 200 calls/run en stationnaire
  (1 search ×2 mkt + 8 item/{id} en moyenne, pas tous activés en mkt
  natif).
- **% de listings dédoublés** : tracker `discovery_searches.found_in`
  pour mesurer l'overlap GB ↔ natif. Si > 70 % overlap, le natif n'apporte
  rien et il faut reconsidérer la stratégie.
- **Front clarté** : un dev qui ouvre une run-detail comprend en < 10 s
  quelle marketplace a tiré combien d'annonces et quelle règle a rejeté
  quoi. Pas de "magic" caché.

## Scope strict de ce chantier

Inclus :
- Refacto `EbayClient` pour marketplace paramétrique.
- Map pays → (marketplace primaire, langue, fallback GB).
- Query builder multilingue (`queries.py` étendu).
- Bootstrap Numista i18n (1 script, 1 run, ~3000 coins × 5 langues).
- Theme matcher multilingue (consomme la i18n).
- Migration schema : `marketplace` sur `source_images` et
  `discovery_searches` + `found_in` JSON.
- Step `discover` : double call paralléle + dédup item_id + persistence
  searches par marketplace.
- Front : pilote (rappel stratégie), run-detail (funnel par marketplace),
  panel règles actives.

Exclus (orthogonaux) :
- Pagination > 50 (cf. `ebay-strategy-v3-kickoff.md` §3.A).
- Lot review price (cf. `ebay-strategy-v3-kickoff.md` §3.B).
- Pièces standards millésimées (cf. `ebay-strategy-v3-kickoff.md` §3.C).
- Velocity weighting prix (cf. D-24, vue SQL post-hoc).
