# Supabase app-facing schema (V2) — projection de `eurio.db`

> **Statut** : ✅ **IMPLÉMENTÉ** (P1-P6, 2026-06-02). Schéma migré, exporteur
> `eurio.db → Supabase` en place, images en Storage, core offline `app_core.db`/
> `app_core.json` généré, proto + Android repointés. Commit `feat(data): refonte
> couche données app`. Décidé en session du 2026-06-01 avec Raphaël.
> **Supersede** la partie Supabase de `docs/design/_shared/data-contracts.md`.

---

## 1. Contexte & problème

`ml/state/eurio.db` (SQLite) est **la source de vérité** du référentiel (doctrine
`feedback_sqlite_only_doctrine`). Il a beaucoup grossi et s'est enrichi ; Supabase
est resté un **squelette V1 + V2-partiel** issu du pipeline d'enrichissement, qui :

- **manque des catégories entières** dont l'app a besoin : caractéristiques
  physiques (diamètre/poids/compo/tranche/lettrage…), descriptions i18n 24 langues,
  topics, crédits (designers) ;
- **traîne des colonnes admin** mortes côté app (`needs_review`, `review_payload`,
  `has_bce/has_wikipedia/...`, `cross_refs` jsonb…) et des tables pipeline
  (review_queue, discovery_*, training_*, source_runs, matching_*) ;
- a des **shapes drifté** vs le canon (prix, images jsonb inline vs table dédiée).

Gap mesuré (session 2026-06-01) :

| Besoin app | `eurio.db` (canon) | Supabase actuel |
|---|---|---|
| Titre i18n | `coin_names_i18n` 4126 / 6 langues | 3936 (drifté) |
| Description i18n | `coin_descriptions_i18n` 11345 / **24 langues** | ❌ absent |
| Caractéristiques | `coin_observations` typé, ~689 coins | ❌ absent |
| Mint / atelier | `mints` + `coin_mint_releases` 3312 | 676 (drifté) |
| Prix par état | `coin_market_quotes` (eBay, gradé) + `mint_release_prices` 12161 | 624 + 1633 (drifté) |
| Images | `coin_canonical_images` 1924 (url + local_path) | `coins.images` jsonb, Storage vide |
| Crédits / topics | `coin_credits` 1350 / `coin_topics` 1795 | ❌ absent |

## 2. Décision de principe

> **Supabase = couche de service en lecture seule, projection « app-shaped » de
> `eurio.db`. Pas un second canon.**

On **dessine le schéma à l'envers depuis les écrans de l'app**, puis un **exporter
déterministe** `eurio.db → Supabase` (qui remplace/étend `ml/export/sync_to_supabase.py`)
le peuple. On ne mirroe que le sous-ensemble app-facing — pas les tables pipeline,
pas les colonnes admin.

### 2.1. Surensemble : Supabase contient AUSSI la donnée du core offline (décidé 2026-06-01)

Précision clé : **Supabase est un surensemble du core offline (C3), pas son
complément.** La donnée embarquée dans l'app (titre, description, caractéristiques,
mintage, prix baseline…) vit **AUSSI dans Supabase, en tables propres normalisées** —
jamais comme un blob. L'exporteur peuple Supabase intégralement (tout l'app-facing),
**puis dérive le core offline (C3) comme une projection/sous-requête de ces mêmes
tables**. Une correction (mintage erroné, nouvelle pièce) se propage donc partout.

```
eurio.db ──exporteur unique──► Supabase (tables propres, TOUT l'app-facing)   ← C2
                                   │
                                   └─ projection C3 ─► SQLite pré-buildée (APK/Room)
                                                       + app_core.json (proto)
                                                       + images côté commun packagées
```

L'app lit :
- un **core packagé** dans l'APK (SQLite pré-buildée, 100 % offline),
- **Supabase** pour le delta + l'on-demand (refresh prix, packs de langues,
  image avers haute-déf).

Le **proto mime l'app** : il lit le core projeté (`app_core.json`) **et** fetch le
**vrai Supabase** (clé anon read-only).

### 2.2. Read-surface canonique = le contrat `src/api/` du proto Vue (2026-06-02)

Le proto Vue formalise **la surface exacte que l'app CONSOMME** dans
`admin/packages/proto/src/api/` — c'est le **contrat de lecture** dont ce schéma
Supabase est la projection physique. Correspondance directe à respecter en mode
live :

| Contrat api (`src/api/types.ts`) | Projection Supabase (§3) |
|---|---|
| `RawCoin` (shape de `app_core.json`, `loadSnapshot()`) | `coin` à plat + jointures aplaties à l'export |
| `Coin` (entité normalisée, `normaliseCoin`) | dérivée de `coin` + `coin_name_i18n` (titre langue système) |
| `Market` (`getMarket` → p25/p50/p75, grades UNC/TTB/TB, rarity) | `coin_price` `kind='market'` agrégé par grade |
| `Reveal` (`getReveal` → tier/mintage/grades/completion) | `coin` (mintage) + `coin_price` + sets (completion) |
| `Recit` (`getRecit`) | dérivé `coin` (theme/design_description/year/country) — pas de table dédiée |
| `SetPreview`/`SetDetail` (`getSets`/`getSet`) | `sets` + `set_members` (créés, peuplés plus tard) |
| `Coin3DAssets` (`getCoin3DAssets`) | `shared_reverse` (revers packagé) + `coin_image` (avers Storage) |
| `CountryProgress`/`CountryPlanche` | **démo** (fixtures) → jointure store `owned` au cutover |

> **Frontière stricte** (identique côté proto et live) : l'api ne renvoie
> **jamais** `owned`/`condition`/`addedAt` — ça vit dans le store local (Room côté
> Android). Le point de bascule fixtures↔live est `src/api/loader.ts`
> (`VITE_DATA_MODE`) : `loadLive()` (PostgREST) doit servir **exactement** la shape
> `Snapshot`/`RawCoin` ci-dessus pour que `initApi()` reste agnostique. Brancher
> `loadLive()` est le dernier pas du Chunk F (après confirmation de parité).

## 3. Schéma cible Supabase

Postgres illustratif (types à affiner). PK = `eurio_id` partout où 1:1.

### `coin` — identité + caractéristiques physiques (à plat, 1:1, figé)

Caractéristiques **en colonnes typées** (décision : à plat, pas de blob JSON —
1:1 figé, filtrable, snapshot/Room simples). Source = `coin_observations` aplati.

```sql
coin (
  eurio_id            text primary key,
  country             text not null,        -- ISO2 ('FR', 'eu' joint)
  country_name        text,
  year                int  not null,
  face_value_cents    int  not null,        -- 200 = 2 € (pas de float)
  is_commemorative    bool not null,
  collector_only      bool not null default false,
  theme               text,
  design_description  text,
  mintage             bigint,               -- mintage type-level (drill-down: coin_mint_release)
  -- caractéristiques physiques (coin_observations aplati) :
  diameter_mm         real,
  weight_g            real,
  thickness_mm        real,
  composition         text,                 -- "Bimetallic: ..." (texte libre Numista)
  shape               text,                 -- "Round"
  orientation         text,                 -- "medal" | "coin"
  edge_description    text,
  edge_lettering      text,
  obverse_lettering   text,
  reverse_lettering   text,
  demonetized         bool,
  demonetized_on      date,
  -- référentiel / variantes :
  design_group_id     text,                 -- → design_group
  variant_kind        text not null default 'classic',
  canonical_eurio_id  text,                 -- self-ref si variante
  series_id           text,
  -- images :
  shared_reverse_id   text not null,        -- → shared_reverse (côté commun, packagé APK)
  obverse_image_id    bigint,               -- → coin_image (avers unique, Storage)
  updated_at          timestamptz not null
)
```

### `shared_reverse` — catalogue du côté commun (packagé APK)

Le côté commun (carte / globe) est **partagé** : ~2 designs pour les 2 € (carte
1ʳᵉ version pré-2007, 2ᵉ version 2007+), **< ~15 visuels** toutes denominations.
Résolu par **règle déterministe** `(face_value, year ≥ 2007 ?)` à l'export.

```sql
shared_reverse (
  id          text primary key,    -- ex: '2eur-map-v2'
  label       text not null,       -- "Carte de l'Europe (2007+)"
  asset_name  text not null,       -- nom du fichier packagé dans l'APK
  map_version int,                 -- 1 | 2
  applies_to  text                 -- doc de la règle (denomination/période)
)
```

### `coin_image` — avers unique (Supabase Storage, on-demand)

```sql
coin_image (
  id         bigserial primary key,
  eurio_id   text not null,
  role       text not null default 'obverse',  -- on n'héberge que l'avers
  storage_path text not null,      -- chemin dans le bucket Storage
  source     text not null,        -- 'bce_official' | 'numista_api' | 'eurio_capture'
  license    text,                 -- traçabilité (on assume le risque côté Numista)
  width      int, height int
)
```

### `coin_price` — valeur (eBay) ET cote/achat (catalogue), par état

Un seul table, dimension `kind` :
- `kind='market'` → **valeur** de la pièce (marché eBay, par état) — affichage principal.
- `kind='catalogue'` → **cote/achat neuf** (LMDLP/MdP/Numista) — feature « compléter sa
  collection » (différée, `buy_url` souvent null pour l'instant).

```sql
coin_price (
  id          bigserial primary key,
  eurio_id    text not null,
  kind        text not null check (kind in ('market','catalogue')),
  grade       text check (grade in ('UNC','TTB','TB')),  -- null = 'overall'
  p_low       int,                 -- cents (p10 eBay)
  p_mid       int,                 -- cents (p50 / prix cote)
  p_high      int,                 -- cents (p90 eBay)
  currency    text not null default 'EUR',
  source      text not null,       -- 'ebay_browse' | 'lmdlp' | 'mdp' | 'numista_api'
  buy_url     text,                -- pour kind='catalogue' (achat neuf), nullable
  sampled_at  timestamptz not null
)
```

> eBay `coin_market_quotes` est déjà gradé (UNC/TTB/TB/unknown) avec p10/p50/p90 —
> le mapping `kind='market'` est direct. Le catalogue par grade vient de
> `mint_release_prices` (UNC/TTB/TB) et/ou `coin_market_quotes` source LMDLP.

### i18n, mint, crédits, variantes

```sql
coin_name_i18n        (eurio_id, lang, title, confidence)        -- app: confidence='canon'
coin_description_i18n (eurio_id, lang, title, description, confidence)
mint                  (id, country, mark, city, display_name)
coin_mint_release     (id, parent_type_id, mint_year, mint_id, issue_type, mintage)
coin_credit           (eurio_id, role, name, position)          -- designer/engraver
design_group          (id, designation, designation_i18n_json)
```

## 4. Qui sert quoi (APK / Supabase / Storage)

| Donnée | APK (snapshot/assets) | Supabase | Storage |
|---|---|---|---|
| identité + caractéristiques + titre langue système | ✅ core offline | refresh delta | — |
| description longue (24 langs) | langue système | autres langues on-demand | — |
| revers (côté commun) | ✅ assets packagés (~15 fichiers) | — | — |
| avers (unique) | URL dans snapshot | — | ✅ fetch on-demand + cache Coil |
| valeur eBay par état | dernière connue (offline) | refresh | — |
| cote/achat catalogue | — | on-demand | — |

**Free tier** : Storage ne porte que les avers (~2776 × ~80 KB webp ≈ **220 MB** < 1 GB) ;
egress proportionnel à l'usage réel (coffre + scans), pas au catalogue. Les revers ne
coûtent rien (APK). Pas de transform image (free tier) → on pré-génère le webp à l'export.

## 5. Contrat snapshot v2 (APK) + Room

Le snapshot actuel (`app-android/src/main/assets/catalog_snapshot.json`, 2776 coins,
champs morts `theme_code`/`obverse_meta`) est régénéré au schéma ci-dessus :
- on **retire** les champs fantômes ;
- on **ajoute** caractéristiques à plat, `shared_reverse_id`, `obverse_image_url`,
  titre + description (langue système), valeur eBay dernière connue par état.
- Room miroir (cf. `data-contracts.md`) mis à jour symétriquement.

## 6. Ce qu'on abandonne côté app

Tables pipeline (review_queue, discovery_*, training_*, source_runs, matching_*,
coin_confusion_map, model_classes) et colonnes admin de `coins` Supabase
(`needs_review`, `review_reason`, `review_action_hint`, `review_payload`,
`has_bce/has_wikipedia/has_lmdlp/has_ebay`, `cross_refs` jsonb, `sources_used`).
Ces données restent dans `eurio.db` (dev/admin) ; elles ne sont pas projetées.

## 7. Plan en chunks (à dérouler après validation)

1. **Migrations Supabase** — nouveau schéma (tables ci-dessus), drop des reliquats.
2. **Exporter** `eurio.db → Supabase` — réécriture de `sync_to_supabase.py`
   (aplatissement `coin_observations`, résolution `shared_reverse` par règle,
   split prix market/catalogue).
3. **Images Storage** — pré-génération webp avers + upload bucket public ;
   catalogue `shared_reverse` + assets packagés APK.
4. **Snapshot v2 + Room/app** — regénérer le snapshot, MAJ schéma Room + bootstrap,
   MAJ `data-contracts.md`.

## 8. Décisions verrouillées (2026-06-01) & points ouverts

Décisions actées (session 2026-06-01) :
- [x] **Supabase = surensemble** (cf. §2.1) : la donnée C3 vit aussi en tables propres.
- [x] **i18n offline** : **FR + EN complets** (titre + description) packagés dans l'APK.
      Les **autres langues = packs téléchargeables** servis par Supabase → prévoir un
      **storage optimisé pour packs de langues** (par-langue, pas N requêtes par pièce).
- [x] **Format core C3** : **SQLite pré-buildée** côté Android (Room) **+** `app_core.json`
      côté proto. Même projection, deux sérialisations.
- [x] **Prix offline** : **baseline figé** (dernière valeur eBay connue par état) packagé,
      refresh online ~mensuel.
- [x] **Proto online** : le proto fetch le **vrai Supabase** (clé anon read-only).
- [x] **Wipe autorisé** : Supabase actuel (2782 coins + bucket `coin-images` 6387 obj /
      178 MB) est intégralement rasable (dev, single-user). Rebuild propre depuis eurio.db.
- [x] **Périmètre 1er passage** : sous-ensemble **enrichi d'abord** (~689 coins avec
      caractéristiques complètes), pipeline de bout en bout sur un set propre, puis
      extension au reste du catalogue. **Confirmé** : les 689 d'eurio.db = exactement
      ce set ; le « 2782 » n'existe que dans le vieux Supabase (rasé).
- [x] **Source `theme`** : **observation Numista verbatim EN** (`coin_observations[theme]`),
      pas le `coins.theme` curé court (divergence 554/630). Titre long détaillé reste
      via `coin_descriptions_i18n`.
- [x] **Variantes** : modèle **coins first-class** (31 lignes `variant_kind` +
      `canonical_eurio_id` self-ref). La table enfant Numista `coin_variants` (10) **n'est
      PAS projetée** côté app (redondante avec le référentiel V2).
- [x] **Provenance** : schéma app **minimal** — on **droppe** `coin_credit.source_ref`,
      `coin_topics.source` et les colonnes `confidence` i18n. La provenance reste dans
      eurio.db (dev). Pas de badge « traduit auto » côté app pour l'instant.

Spec d'exporteur (résolutions, set 689) :
- Caractéristiques = aplatissement `coin_observations` (key/value `payload_json`).
  Mintage type-level via `coin_observations[mintage_official].value` (470/689).
- Mintage par release via JOIN `mint_release_observations[fact_type='mintage']`.
- Prix marché baseline = dernier quote par (eurio_id, grade), 672/689. Catalogue via
  `coin_mint_releases.parent_type_id`. **Fix lmdlp** : `UNC/BU FDC/BE Proof` → grade `UNC`
  à l'export (sinon 566 coins sans prix lmdlp).
- Images avers : 478/689 ont un webp local (`ml/canonical_images/<eurio_id>/`), 211 à
  télécharger depuis url Numista avant upload Storage. Revers tous url-only.
- `demonetized_on`, `series_id`, `coin_series`, `sets`, `set_members` = NULL/vides
  (tables créées, peuplées plus tard).
- `design_group.designation_i18n_json` vide (5 groupes) → à peupler (éditorial léger).

Points encore ouverts :
- [ ] Confirmer la **règle déterministe** côté-commun (denomination × année 2007) sur
      l'ensemble du catalogue (Andorre/Monaco/SM/Vatican, cas pré-2007 commémo).
- [ ] **buy_url** catalogue : non disponibles aujourd'hui (LMDLP/MdP) — feature achat
      différée, schéma prêt mais peuplement plus tard.
- [ ] eBay `unknown` grade : les rattacher à `grade=null` (overall) ou les exclure de
      l'affichage par état.
- [ ] **Schéma des packs de langues** : table/bucket + granularité (1 pack = 1 langue,
      tout le catalogue ; vs par pays). À trancher en P2.
