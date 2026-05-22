# Front UX — visibilité multi-marketplace + règles de filtrage

> Spec des changements admin (`packages/web`) pour que (1) la stratégie
> multi-marketplace soit lisible à l'œil nu et (2) les règles de filtrage
> qui ont rejeté une annonce soient explicitement listées, pas devinées.
>
> Référentiels actuels :
> - Pilote eBay : `admin/packages/web/src/features/sources/components/EbayPilotPanel.vue`
> - Run breakdown : `admin/packages/web/src/features/sources/pages/SourceRunDetailPage.vue`
> - Run listings : `admin/packages/web/src/features/sources/pages/SourceRunListingsPage.vue`
> - Coin detail : `admin/packages/web/src/features/coins/pages/CoinDetailPage.vue`
> - Enrichment gallery : `admin/packages/web/src/features/coins/components/EnrichmentGallery.vue`

## Surface 1 — Pilote eBay (`EbayPilotPanel.vue`)

### État actuel

KPI quota + freshness buckets + slider batch + preview batch.

### Ajouts

**Bandeau "Stratégie d'extraction" en haut du panel** (au-dessus des
KPI, juste sous le header) :

```
┌─ Stratégie d'extraction ────────────────────────────────────────┐
│ Marketplace global : EBAY_GB (catch-all)                         │
│ + marketplace natif selon le pays d'origine                      │
│   AT→DE/EBAY_AT · BE→FR/EBAY_BE · DE→DE/EBAY_DE · ES→ES/EBAY_ES │
│   FR→FR/EBAY_FR · IT→IT/EBAY_IT · NL→NL/EBAY_NL · IE→EN/EBAY_IE │
│   AD,MC,LU→EBAY_FR · SM,VA→EBAY_IT · PT→EBAY_ES                  │
│   Autres → EBAY_GB only                                          │
│ Coût quota moyen : ~1.7 search calls/eurio_id (vs 1.0 avant)     │
│ [voir la table complète]                                         │
└──────────────────────────────────────────────────────────────────┘
```

- "voir la table complète" → modal qui affiche la table de
  `marketplace-map.md` rendue depuis l'endpoint
  `GET /sources/ebay/marketplace-map` (renvoie le dict statique).
- **Source du chiffre `~1.7`** : calcul **a priori** côté front à partir
  du dict `marketplace-map` et du mix pays du batch preview courant.
  Formule : `sum(1 if route_for(coin.country).primary is None else 2 for
  coin in batch) / len(batch)`. Pas de tracker runtime, pas de migration
  `api_quota.py` (le quota tracker continue à compter les appels post-hoc
  comme avant — il n'a pas à connaître la stratégie). Pour le batch
  global cross-pays, l'affichage `~1.7` est une **estimation type
  eurozone répartie uniformément**, recalculée live dès qu'un batch
  preview est généré.

**Modification du preview batch** : chaque ligne preview affiche
maintenant un mini-tag du couple de marketplaces qui sera appelé :

```
 never  ad-2025-2eur-bearded-vulture        [ES][GB]  0 img · 0 crops
 stale  be-2014-2eur-150-years-of-red-cross [BE][GB]  4 img · 3 crops
```

## Surface 2 — Run breakdown (`SourceRunDetailPage.vue`)

### État actuel

Tableau par eurio_id avec colonnes List/Crops/Auto/Rev.S/Rev.L/Pend/Rej/
Attr/Quotes + lot flag + lien review.

### Ajouts

**Colonne `Mkts`** entre `eurio_id` et `List.` : badges des marketplaces
qui ont produit au moins 1 listing pour cet eurio_id.

```
eurio_id                              Mkts      List.  Crops  Auto  ...
ad-2025-2eur-bearded-vulture          [ES] [GB]    12      8     6
de-2024-2eur-paulskirche              [DE] [GB]    23     14    11
fr-2012-2eur-abbe-pierre              [FR] [GB]    47     19    15
sk-2024-2eur-kosice                    [GB]        8      3      2
```

- Badge coloré par marketplace (palette stable : FR=bleu, DE=jaune,
  IT=vert, ES=rouge, GB=indigo, NL=orange, AT=violet, IE=cyan, BE=teal).
- Hover badge → tooltip "N listings depuis EBAY_DE".

## Surface 3 — Run listings (`SourceRunListingsPage.vue`)

C'est l'endroit où le user veut voir le **détail de la requête** et les
**règles de filtrage actives**. Deux changements majeurs.

### 3.A — Section "Discovery searches" enrichie

État actuel : 1 row par eurio_id avec funnel N0→N1→N2→N3 + filters JSON
expand.

Nouvelle structure : **1 row par (eurio_id × marketplace)** avec funnel
ventilé et plus de meta.

```
▼ Discovery searches · 17 calls

  ▶ [✓ ok]    ad-2025-2eur-bearded-vulture · EBAY_ES · 32→32→32→8 kept · 1.2s
  ▶ [✓ ok]    ad-2025-2eur-bearded-vulture · EBAY_GB · 50→52→52→12 kept · 0.9s
  ▶ [○ empty] sk-2024-2eur-kosice · EBAY_GB · 0→0→0→0 kept · 0.7s
  ...

  ─ Expand row 1 ─
  marketplace      EBAY_ES
  accept_language  es-ES
  endpoint         ebay.browse.search.es
  q                2 euro Andorra 2025
  filters          {
                     "aspect_filter": "categoryId:32650",
                     "theme_tokens_used_langs": ["es", "en"],
                     "theme_tokens_used": ["quebrantahuesos","bearded","vulture"],
                     "ambiguous": false,
                     "search_limit": 50
                   }
  browse_url       https://api.ebay.com/buy/browse/v1/item_summary/...
                   [📋 copier]  [🔗 ouvrir]
  http_status      200
  duration         1234 ms
```

Le `browse_url` reconstructible est nouveau, persisté dans
`query_filters_json.browse_url` (cf. `schema.md`).

### 3.B — Nouveau panel "Règles de filtrage actives"

Bouton `[i] Règles actives` à côté du header de la page (à côté de
"Listings rejetés pré-ingestion"). Ouvre un drawer/modal :

```
┌─ Règles actives sur ce run ─────────────────────────────────────┐
│                                                                  │
│ ★ Filtres pré-ingestion (accept_listing)                         │
│                                                                  │
│ 1. noise_title                                                   │
│    Reject si le titre matche : proof|épreuve|argent|or|silver|   │
│                               gold|plaqué|colorisée|erreur|fautée │
│    Stats run : 124 rejets                                        │
│                                                                  │
│ 2. below_face                                                    │
│    Reject si prix < face × 0.8  (= 1.60 € pour les 2€)          │
│    Stats run : 8 rejets                                          │
│                                                                  │
│ 3. above_extreme                                                 │
│    Reject si prix > face × 500  (= 1000 € pour les 2€)          │
│    Stats run : 2 rejets                                          │
│                                                                  │
│ 4. non_eur                                                       │
│    Reject si currency != EUR                                     │
│    Stats run : 17 rejets                                         │
│                                                                  │
│ 5. year_mismatch (commemo only)                                  │
│    Reject si année trouvée dans le titre ≠ année attendue        │
│    Policy : accept-on-missing                                    │
│    Stats run : 31 rejets                                         │
│                                                                  │
│ 6. theme_mismatch (commemo only, ambiguous country/year)         │
│    Reject si aucun théme-token (multilingue) n'apparaît          │
│    dans le titre                                                 │
│    Stats run : 9 rejets                                          │
│                                                                  │
│ ★ Flags non-rejetants                                            │
│                                                                  │
│ • is_lot_suspected                                               │
│   Match titre : lot|coffret|série|rouleau|set                    │
│   Route → review-queue kind='lot' (gardé, pas rejeté)            │
│   Stats run : 23 flags                                           │
│                                                                  │
│ ★ Source du code                                                 │
│   ml/sources/ebay/filters.py (accept_listing + is_lot_suspected) │
└──────────────────────────────────────────────────────────────────┘
```

- Les stats par règle viennent de `discarded_listings.reason` GROUP BY.
- Les valeurs (0.8, 500, regex full) viennent d'un endpoint
  `GET /sources/ebay/filter-config` qui réflexionne le contenu de
  `ml/sources/ebay/filters.py` (constantes exportées).
- Lien "Source du code" → ouvre le fichier dans un nouveau tab (file://
  ou repo URL ; on lit la config from-runtime, pas hard-codée côté front).

Idée : les valeurs ne sont **pas** modifiables depuis le front (V1).
C'est de la visualisation pour comprendre pourquoi une annonce a été
rejetée. Toute modif passe par PR + redéploiement (les filtres sont des
décisions produit qui méritent un review humain).

### 3.C — Section "Listings rejetés" existante : ajout colonne marketplace

Dans le rejected-list (déjà existant), ajouter la marketplace d'origine
de chaque listing rejeté :

```
 [non_eur]    ad-2025-...  · EBAY_GB · Andorra 1 Euro Coin 2 EU 1¢  · 2.50 USD
 [year_mis]   fr-2012-...  · EBAY_FR · 2 euros France 2010 abbé Pierre · 4.50 EUR
```

## Surface 4 — Coin detail (`CoinDetailPage.vue` + `EnrichmentGallery.vue`)

> **❌ ABANDONNÉE (2026-05-22).** Cette surface (badge marketplace par
> thumbnail enrichment) supposait le routing per-origine de la spec
> initiale (9 marketplaces). Le chunk C0 (2026-05-21) a basculé sur un
> routing **uniforme `{EBAY_DE, EBAY_ES}`** : le marketplace n'est plus
> qu'un canal de découverte 50/50, pas une info produit. Mesure sur
> `training.db` : un listing n'est vu sur les 2 marketplaces que dans
> **1,6 %** des cas (requêtes DE/ES en langues différentes → résultats
> quasi-disjoints). Un badge per-thumb serait soit quasi-constant, soit
> quasi-invisible — sans valeur. La section ci-dessous est conservée pour
> mémoire mais n'est pas implémentée.

### État actuel

Galerie enrichment sous les thumbs canoniques. Chaque thumb affiche le
status (auto/needs_review/rejected) en label discret.

### Ajout : badge marketplace par thumb

Sur chaque thumb enrichment, ajouter un mini-badge en coin (en
plus du status existant) :

```
┌────────┐
│   img  │
│  [DE]  │  ← mini-badge marketplace
│        │
│ [auto] │  ← status existant (bottom)
└────────┘
```

- 2-char badge, fond translucide, position top-right.
- Hover : tooltip "Trouvé sur EBAY_DE le 2026-05-18".
- Color-mapped au même palette que dans run breakdown (cohérence).

### Endpoint side

`GET /coins/:eurio_id/assets` (déjà existant côté
`useCoinAssets.ts`) doit retourner pour chaque asset :
- `marketplace` (depuis `source_images.marketplace`).
- `marketplace_found` (depuis `source_images.marketplace_found_json`)
  pour les listings vus sur 2 marketplaces.

Composable `useCoinAssets` à étendre côté types :

```ts
export interface CoinAsset {
  // ... champs existants
  marketplace: string | null;          // 'EBAY_DE', null pour pre-bascule
  marketplaces_found: string[] | null; // ['EBAY_DE','EBAY_GB'] si overlap
}
```

## Récap palette marketplaces

| Mkt | Couleur (var tokens.css) | Badge text |
|---|---|---|
| `EBAY_FR` | `--blue-500` | `FR` |
| `EBAY_GB` | `--indigo-700` | `GB` |
| `EBAY_DE` | `--gold-600` | `DE` |
| `EBAY_IT` | `--success` | `IT` |
| `EBAY_ES` | `--danger` | `ES` |
| `EBAY_NL` | `--warning` | `NL` |
| `EBAY_AT` | `--purple-500` (si dispo, sinon mix indigo) | `AT` |
| `EBAY_IE` | `--cyan-500` (id) | `IE` |
| `EBAY_BE` | `--teal-500` (id) | `BE` |

À valider contre `shared/tokens.css` au moment du chunk front — créer
les tokens manquants si nécessaire (R2 du CLAUDE.md : edit tokens.css
puis `go-task tokens:generate`).

## Anti-objectifs UX

- **Pas de marketplace switcher** côté pilote. La stratégie est figée,
  l'utilisateur n'a pas à choisir.
- **Pas de comparison côte-à-côte** des deux marketplaces dans la
  coin-detail. Une seule galerie unifiée, badge marketplace en discret.
- **Pas de filtre côté `/review`** par marketplace. La review est
  agnostique de la source du listing — un crop est un crop.
