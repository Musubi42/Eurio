# Data contracts — Room local ↔ Supabase

> ⚠️ **MAJ 2026-06-02 — archi 3 couches (V2).** La doctrine a changé : `eurio.db`
> (SQLite dev) est le **canon**, Supabase est une **projection read-only app-facing**,
> et l'app embarque un **core offline C3**. Spec autoritaire :
> [`docs/research/supabase-app-schema-v2.md`](../../research/supabase-app-schema-v2.md)
> (implémentée P1-P6). Les §1-§6 ci-dessous décrivent le **design v1 original
> (2026-04-13)** et sont conservés à titre historique — plusieurs tables (`user_collection`,
> `coin_price_observation`) n'ont jamais été implémentées telles quelles.

## 0. Réalité implémentée (V2, 2026-06-02)

**Flux** : `eurio.db` → exporteur `ml/export/app_export` → **Supabase** (14 tables
app-facing) → projection `ml/export/build_app_core.py` → **`app_core.db`** (SQLite
packagée APK) + **`app_core.json`** (proto).

**Côté Android** : `AppCoreBootstrapper` copie `app_core.db` (asset → cacheDir),
l'ouvre en read-only, et **`@Upsert`** le catalogue dans Room (table `coins` V2 :
`face_value_cents`, caractéristiques à plat, `shared_reverse_id`, `variant_kind`,
`name_fr/en`, `desc_fr/en` ; + tables `coin_prices`, `shared_reverse`). Version-gate
`APP_CORE_VERSION` dans `catalog_meta`. **Le coffre (`coin_in_vault`, `coin_captures`)
est local-first et n'est JAMAIS touché par le refresh catalogue** — c'est pour ça
que l'insert est `@Upsert` (pas `REPLACE`, qui cascaderait la FK `coin_in_vault →
coins ON DELETE CASCADE` et viderait le coffre).

**Images** : avers (côté national) = URL Storage dérivée de l'`eurio_id`
(`obverseStorageUrl()`), fetch on-demand (Coil → viewer 3D Filament). Revers (côté
commun) = asset carte packagé (`file:///android_asset/shared_reverse/<asset_name>`),
résolu via `shared_reverse_id`.

**i18n** : FR+EN dénormalisés sur `coins` (offline) ; autres langues = packs Supabase.
**Prix** : `coin_prices` = baseline marché (eBay) par état, refresh on-demand.

---

> _Ci-dessous : design v1 historique (2026-04-13). Voir la bannière en tête._

---

## 1. Sources de vérité

| Donnée | Source de vérité | Réplique |
|---|---|---|
| Identité canonique d'une pièce (`eurio_id`, country, year, face_value, theme...) | Supabase `coins` | Room `coin` |
| Images canoniques (BCE, Numista) | Supabase Storage | Cache disque local + Room (URLs + chemins locaux) |
| Observations de prix (eBay time series) | Supabase `source_observations` | Room `coin_price_observation` (dernière valeur seulement) |
| Collection user | Room `user_collection` (local-first) | Supabase `user_collections` (opt-in sync future) |
| Embeddings pour le scan | Supabase `coin_embeddings` + `assets/ml/coin_embeddings.npy` shippé | Chargé en mémoire par `EmbeddingMatcher` Android |
| Achievements user | Calculés localement depuis `user_collection` | N/A |

---

## 2. Schema Room proposé (v1)

> Sketch conceptuel. Les types exacts seront affinés à l'implémentation. Une migration Room par version du schema.

### Table `coin`
Miroir de Supabase `coins`. PK = `eurio_id`.

```
coin
├── eurio_id              TEXT PRIMARY KEY   -- "fr-2012-2eur-10ans-euro"
├── country_iso2          TEXT NOT NULL      -- "fr"
├── country_name          TEXT NOT NULL      -- "France"
├── year                  INTEGER NOT NULL
├── face_value_cents      INTEGER NOT NULL   -- 200 pour 2 EUR (évite les float)
├── is_commemorative      INTEGER NOT NULL   -- 0/1
├── theme                 TEXT               -- "10 ans de l'euro fiduciaire"
├── design_description    TEXT
├── national_variants     TEXT               -- JSON array ISO2 pour émissions communes
├── rarity_tier           TEXT               -- "common" | "uncommon" | "rare" | "very_rare" (dérivé)
├── mintage_total         INTEGER
├── image_obverse_path    TEXT               -- chemin local OU null
├── image_reverse_path    TEXT               -- chemin local OU null
├── image_source          TEXT               -- "bce" | "numista" | "lmdlp"
├── updated_at            INTEGER            -- epoch ms, pour le delta fetch
└── INDEX(country_iso2, year), INDEX(face_value_cents), INDEX(is_commemorative)
```

### Table `coin_price_observation`
Dernière snapshot de prix connue pour chaque pièce. Pas de time series complète en local (ça reste sur Supabase, fetchable à la demande).

```
coin_price_observation
├── eurio_id              TEXT PRIMARY KEY (FK coin.eurio_id)
├── p25_cents             INTEGER            -- prix en cents d'euro pour éviter float
├── p50_cents             INTEGER
├── p75_cents             INTEGER
├── samples_count         INTEGER
├── source                TEXT               -- "ebay_market" | "lmdlp_current" | "mdp_issue"
├── sampled_at            INTEGER            -- epoch ms
└── trend_3m              TEXT               -- "up" | "stable" | "down" | null
```

### Table `user_collection`
La collection locale de l'user. C'est LE coffre.

```
user_collection
├── id                    INTEGER PRIMARY KEY AUTOINCREMENT
├── eurio_id              TEXT NOT NULL (FK coin.eurio_id)
├── owner_user_id         TEXT NOT NULL      -- UUID local ou Supabase user_id après upgrade
├── added_at              INTEGER NOT NULL   -- epoch ms
├── value_at_add_cents    INTEGER            -- P50 au moment de l'ajout, pour calculer le delta
├── user_photo_path       TEXT               -- chemin local de la photo scannée par l'user
├── condition             TEXT               -- "UNC" | "SUP" | "TTB" | "TB" | "B" | null
├── note                  TEXT               -- note perso optionnelle
└── INDEX(eurio_id), INDEX(owner_user_id)
```

Une pièce peut apparaître plusieurs fois dans la collection (un user peut avoir 3 exemplaires de la même pièce). Pas de unique constraint sur `(owner_user_id, eurio_id)`.

### Table `achievement_state`
État de progression des achievements. Recalculable depuis `user_collection` mais cache pour perf.

```
achievement_state
├── achievement_id        TEXT PRIMARY KEY   -- "serie-complete-fr" | "eurozone-founding" | ...
├── owner_user_id         TEXT NOT NULL
├── progress_current      INTEGER NOT NULL   -- 7
├── progress_target       INTEGER NOT NULL   -- 8
├── unlocked_at           INTEGER            -- epoch ms ou null
└── INDEX(owner_user_id)
```

### Table `sync_state`
Un KV simple pour tracker les timestamps de sync.

```
sync_state
├── key                   TEXT PRIMARY KEY   -- "referential_last_sync" | "prices_last_sync"
├── value                 TEXT               -- epoch ms stringifié ou JSON
```

---

## 3. Mapping avec le schema Supabase canonique

Le schema Supabase stocke tout en JSON (`identity`, `observations`, `images`, `cross_refs`, `provenance`). Room aplatit ça en colonnes typées parce que SQLite recherche/filtre infiniment mieux sur des colonnes que sur du JSON. Conversion au moment du sync.

| Supabase `coins` | Room `coin` |
|---|---|
| `eurio_id` | `eurio_id` |
| `identity.country` | `country_iso2` |
| `identity.year` | `year` |
| `identity.face_value` × 100 | `face_value_cents` |
| `identity.is_commemorative` | `is_commemorative` |
| `identity.theme` | `theme` |
| `identity.design_description` | `design_description` |
| `identity.national_variants` | `national_variants` (JSON string) |
| `observations.mintage.total` | `mintage_total` |
| `images[0 where role=obverse].url` | `image_obverse_path` (après download) |
| `provenance.last_updated` | `updated_at` |

Les champs qui ne servent pas à l'app en v1 (provenance, sources_used, matching decisions, full observations history) restent côté Supabase. Pas de réplication.

---

## 4. Points de synchronisation

### Sync #1 — Bootstrap au premier lancement
- **Trigger** : première ouverture de l'app après install.
- **Source** : `assets/seed/eurio_referential.json` shippé dans l'APK + `assets/seed/images/`.
- **Action** : import batch dans Room via migration initiale. Aucune requête réseau.
- **Durée** : < 3 secondes pour 3000 pièces.

### Sync #2 — Delta fetch du référentiel (opt-in, background)
- **Trigger** : WorkManager périodique (hebdo, Wi-Fi uniquement par défaut).
- **Source** : Supabase `GET /rest/v1/coins?updated_at=gt.{last_sync}`.
- **Action** : upsert dans Room. Si nouvelle pièce, fetch aussi image canonique depuis Supabase Storage.
- **Fallback** : si échec, on retry la semaine suivante. L'app continue à tourner avec le référentiel existant.

### Sync #3 — Prix eBay (opt-in, à la demande)
- **Trigger** : ouverture d'une fiche pièce, si `coin_price_observation.sampled_at > 7 jours` ou null.
- **Source** : Supabase `GET /rest/v1/source_observations?eurio_id=eq.{id}&source=eq.ebay_market`.
- **Action** : upsert dans `coin_price_observation`. Affichage avec indicateur de fraîcheur.

### Sync #4 — User collection cloud (opt-in, v2)
- **Trigger** : l'user active la sync cloud (nécessite auth Supabase — voir [`auth-strategy.md`](./auth-strategy.md)).
- **Source & cible** : `public.user_collections` Supabase.
- **Pattern** : Room est source of truth, Supabase est miroir. Conflict resolution : last-write-wins par timestamp. À raffiner en v2.

---

## 5. Migrations Room

Chaque changement de schema = nouvelle version Room + migration explicite.

Versions prévisibles :
- **v1** : schema initial (ci-dessus).
- **v2** : ajout colonnes pour la marketplace (`listing_price_cents`, `listing_status`, ...) — probablement quand on entamera la Phase Marketplace.
- **v3+** : TBD.

**Jamais** de `fallbackToDestructiveMigration`. Les coffres users sont sacrés.

---

## 6. Questions ouvertes

- [ ] Faut-il stocker les photos `user_photo_path` dans l'app FS privé ou laisser Android gérer via `MediaStore` ? Impact sur l'export PDF et sur la confidentialité.
- [ ] Comment gérer les pièces "supprimées" du référentiel Supabase (cas rare mais possible si bug de bootstrap) ? Soft delete avec flag `is_active` ou hard delete qui casse les `user_collection` ?
- [ ] Format de stockage des embeddings canoniques côté Android : `.npy` via JNI ? Ou conversion en format Kotlin-friendly (ex : `FloatArray` sérialisé) au build time ? Impact sur `EmbeddingMatcher`.
- [ ] Taille max acceptable du seed JSON dans l'APK (actuellement estimé ~16 MB avec images BCE). Si on veut ajouter les photos Numista, ça peut doubler. Mesurer à l'impl.
