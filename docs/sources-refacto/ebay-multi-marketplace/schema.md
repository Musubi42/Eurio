# Schema changes — migrations DB

> Migrations idempotentes nécessaires au multi-marketplace. Toutes
> rétro-compatibles : aucun row existant n'est cassé, mais les nouvelles
> colonnes deviennent obligatoires pour les rows écrites par le nouveau
> code.
>
> Conformément aux conventions du dépôt, les migrations sont des
> `ALTER TABLE` idempotents intégrés au schema bootstrap
> (`ml/state/schema.sql`). Pas de système de migration externe pour
> SQLite (le bootstrap recrée si besoin via `CREATE TABLE IF NOT EXISTS`
> + `ALTER ... ADD COLUMN` protégé par check de présence).

## 1. `source_images` — colonne `marketplace`

```sql
-- Marketplace qui a yieldé ce listing en premier (FIFO).
-- Pour les listings vus sur plusieurs marketplaces, voir
-- `discovery_searches.found_in_json` (1 row par mkt avec ses counters)
-- + `source_images.marketplace_found_json` (liste exhaustive).
ALTER TABLE source_images
  ADD COLUMN marketplace TEXT;  -- ex: 'EBAY_GB', 'EBAY_DE', NULL pour legacy

-- Liste de tous les marketplaces où ce listing a été vu pendant ce run.
-- JSON array de strings. Renseigné par discover step.
ALTER TABLE source_images
  ADD COLUMN marketplace_found_json TEXT;  -- ex: '["EBAY_GB","EBAY_DE"]'

CREATE INDEX IF NOT EXISTS idx_source_images_marketplace
  ON source_images(marketplace) WHERE marketplace IS NOT NULL;
```

Sémantique :
- `marketplace` : le premier marketplace dans l'ordre du double call qui
  a yieldé l'item_id. Convention : on appelle `primary` (mkt natif) puis
  `global_` (EBAY_GB), donc `marketplace` reflète où on l'a vu en premier.
- `marketplace_found_json` : la liste complète (dédup inclus). Permet
  d'analyser l'overlap GB ↔ natif.
- Rows legacy (avant ce chantier) restent `NULL` → l'admin sait qu'ils
  pré-datent la bascule.

### Stratégie d'écriture — merge en mémoire avant INSERT

Le `UNIQUE (source, source_ref)` rejette toute 2e INSERT du même item_id
au niveau SQLite. Conséquence : si `EBAY_DE` a yieldé l'item en premier
puis `EBAY_GB` retourne le même item_id, **une 2e INSERT ne mettra
jamais à jour `marketplace_found_json`**.

La règle pour ce chantier : **l'adapter merge les résultats des 2 mkts
en mémoire AVANT le yield**. Chaque `DiscoveredItem` part avec son
`marketplace` (premier mkt qui l'a vu, par ordre primary→global) et son
`marketplace_found_json` complet (liste dédupliquée). Le step
`persist` fait alors une seule INSERT par item_id, conflit-free.

Anti-pattern explicitement banni : `INSERT … ON CONFLICT DO UPDATE` pour
patcher `marketplace_found_json` post-hoc. Ça noie la traçabilité et
introduit une condition de course si 2 runs concurrent touchent le même
item_id. Le merge in-memory est la seule voie.

Détails d'implémentation en chunk B4.

## 2. `discovery_searches` — colonne `marketplace`

```sql
ALTER TABLE discovery_searches
  ADD COLUMN marketplace TEXT;  -- 'EBAY_GB', 'EBAY_FR', etc.

CREATE INDEX IF NOT EXISTS idx_discovery_searches_marketplace
  ON discovery_searches(marketplace) WHERE marketplace IS NOT NULL;
```

Convention : **1 row par (run_id × target_eurio_id × marketplace)**. Le
`endpoint` reste générique (`ebay.browse.search`) — il décrit l'API,
pas la cible. Le marketplace vit exclusivement dans la colonne dédiée
(cf. `marketplace-map.md` §"Convention endpoint vs colonne marketplace"
pour la rationale). Le `query_filters_json` continue à contenir
`aspect_filter`, `theme_tokens`, `ambiguous`, mais aussi maintenant :

```jsonc
{
  "marketplace": "EBAY_DE",
  "accept_language": "de-DE",
  "aspect_filter": "categoryId:32650",
  "theme_tokens_used_langs": ["de", "en"],
  "theme_tokens_used": ["paulskirche", "verfassung", "constitution"],
  "ambiguous": false,
  "search_limit": 50,
  "category_id": "32650",
  "browse_url": "https://api.ebay.com/buy/browse/v1/item_summary/search?..."  // reconstructible
}
```

Le `browse_url` reconstructible est ajouté en V1 pour faciliter le debug
front (1 clic → ouvre la même requête sur Postman / curl).

## 3. Table `coin_names_i18n`

Pour le bootstrap Numista multilingue (cf. `language-probe.md` §"Étape 1").

```sql
CREATE TABLE IF NOT EXISTS coin_names_i18n (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  lang       TEXT NOT NULL CHECK (lang IN ('fr','en','de','it','es','nl')),
  title      TEXT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'numista',  -- 'numista' | 'override'
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, lang)
);

CREATE INDEX IF NOT EXISTS idx_coin_names_i18n_lang
  ON coin_names_i18n(lang);
```

Décision contre l'option "JSON column sur `coins`" évoquée dans
`ebay-strategy-v2-kickoff.md` §2.A : table dédiée plus propre pour
indexer par langue, plus simple à étendre (lt/pl/grc plus tard) sans
toucher au schema principal.

## 4. `source_ref` — pas de changement

`source_ref = ebay_<itemId>_img<N>` reste tel quel. **Ne pas** préfixer
par marketplace (`ebay_de_<itemId>_img<N>` casserait la dédup
cross-mkt — un même item_id retournerait 2 source_refs distincts).

C'est la valeur de `marketplace` colonne qui porte l'info ; le `source_ref`
reste un identifiant logique de la *paire (item_id, image_index)*,
agnostique du canal de découverte.

## 5. `discarded_listings` — colonne `marketplace`

```sql
ALTER TABLE discarded_listings
  ADD COLUMN marketplace TEXT;  -- 'EBAY_GB', 'EBAY_FR', etc.

CREATE INDEX IF NOT EXISTS idx_discarded_listings_marketplace
  ON discarded_listings(marketplace) WHERE marketplace IS NOT NULL;
```

Inclus dans B1 (pas optionnel) : `front-ux.md §3.C` matérialise le badge
marketplace dans la liste des rejets — sans la colonne, il faudrait
parser le `raw_payload_json` à chaque rendu. Coût storage négligeable
(TEXT 8 char), pattern d'écriture aligné sur `source_images.marketplace`
(le step `discover` propage le mkt courant au `record_discarded`).

Rows pré-bascule : `marketplace IS NULL`, le front affiche `—`.

## Idempotence des migrations

SQLite ne supporte pas `ADD COLUMN IF NOT EXISTS`. Pattern à utiliser
dans le bootstrap :

```python
def _ensure_column(conn, table, column, ddl):
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
```

À placer dans `ml/state/store.py` (ou équivalent qui exécute
`schema.sql`), après le `executescript(schema_sql)` initial. Cela permet
de re-bootstrap une DB existante sans erreur "duplicate column".

## Compatibilité backward — runs antérieurs

- Rows `source_images` pré-migration : `marketplace IS NULL`. Le front
  affiche `(pre-bascule)` en lieu et place du badge marketplace.
- Rows `discovery_searches` pré-migration : idem. Le funnel s'affiche
  comme un single-mkt sans badge.
- Les commandes admin (`reflag_needs_review`, etc.) ne changent pas
  de signature.

## Volume estimé

- `coin_names_i18n` : ~3000 coins × 6 langues = ~18 k rows. ~3 MB.
- `source_images.marketplace` : storage négligeable (TEXT 8 char).
- `discovery_searches.marketplace` : déjà des dizaines de milliers de
  rows attendues à terme — storage 1 col × 8 char = négligeable.
- `discovery_searches` ×2 rows par eurio_id (1 par mkt) : double la
  taille de cette table à volume de runs constant. Reste largement sous
  les quotas SQLite (DB actuelle ~50 MB, projection avec multi-mkt à
  ~200 MB sur 1 an).
