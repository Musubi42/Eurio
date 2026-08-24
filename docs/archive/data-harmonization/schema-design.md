# Chunk 1 — Schéma SQLite canonique `eurio.db` (FINALISÉ)

> Conception **auditée par un expert DB** et figée 2026-05-22. Cadre :
> `architecture.md`. Périmètre : tables du **référentiel canonique** + **cycle
> de vie** + **journal d'identité**. Hors périmètre : les blobs JSON des tables
> opérationnelles (`training_runs`, `benchmark_runs`, `experiment_iterations`).
>
> Ce doc est la **spec d'implémentation** du chunk suivant (schéma + migration).

## Contexte

`eurio.db` a 28 tables. La couche images/scrape/training est mature. Le maillon
faible : `coins` est un simple miroir de `eurio_referential.json` ;
`design_groups` n'existe pas dans `eurio.db` (seulement Supabase).

## Principes

1. `coins` devient **canonique** (généré depuis le catalogue source), plus un
   miroir.
2. Plus de blob `raw_payload_json` sur `coins` → tables filles ; le JSON brut
   amont vit dans `referential_catalog.raw_json`.
3. **Pas de duplication de colonnes** entre `referential_catalog` et `coins` :
   un re-scrape ne doit jamais pouvoir désynchroniser deux copies.
4. FK explicites là où on **possède le write-path** ; ailleurs, une **vue QA**
   observe les orphelins au lieu de les contraindre.
5. Nommage générique (« source référentielle », pas « Numista »).

---

## Tables — DDL cible

### `referential_catalog` — provenance brute du scrape référentiel

Thin table : provenance, pas de duplication des champs typés (re-dérivables
depuis `raw_json`). Aujourd'hui `source='numista'` (688 lignes).

```sql
CREATE TABLE referential_catalog (
  source              TEXT NOT NULL,           -- 'numista' (demain 'bce', …)
  source_native_id    TEXT NOT NULL,           -- ID natif, TEXT (pas d'arithmétique)
  country_name        TEXT,                    -- colonnes de QA pré-`coins`
  year                INTEGER,                 --   (diff/contrôle avant génération)
  face_value          REAL,
  type                TEXT,                    -- 'commemorative' | 'circulation'
  raw_json            TEXT NOT NULL,           -- payload API complet (vérité brute)
  scrape_snapshot_ref TEXT,                    -- fichier sources/ immuable
  scraped_at          TEXT NOT NULL,
  PRIMARY KEY (source, source_native_id)
);
```

### `design_groups` — porté de Supabase

```sql
CREATE TABLE design_groups (
  id                    TEXT PRIMARY KEY,      -- slug stable
  designation           TEXT NOT NULL,
  designation_i18n_json TEXT,
  description           TEXT,
  shared_obverse_url    TEXT,
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TRIGGER design_groups_touch_updated_at AFTER UPDATE ON design_groups
BEGIN UPDATE design_groups SET updated_at = datetime('now') WHERE id = NEW.id; END;
```

### `coins` — référentiel canonique (refonte)

```sql
CREATE TABLE coins (
  eurio_id              TEXT PRIMARY KEY,
  ref_source            TEXT NOT NULL,         -- 'numista'
  ref_native_id         TEXT NOT NULL,         -- → referential_catalog
  numista_id INTEGER GENERATED ALWAYS AS       -- compat, zéro dérive
    (CASE WHEN ref_source='numista' THEN CAST(ref_native_id AS INTEGER) END) VIRTUAL,
  country               TEXT NOT NULL,         -- ISO2 ('FR',…,'eu')
  country_name          TEXT,
  year                  INTEGER NOT NULL,
  face_value            REAL NOT NULL,
  currency              TEXT NOT NULL DEFAULT 'EUR',
  is_commemorative      INTEGER NOT NULL DEFAULT 0,
  collector_only        INTEGER NOT NULL DEFAULT 0,
  theme                 TEXT,
  design_description    TEXT,
  mintage               INTEGER,               -- promu (queryable : rareté, sets)
  mintage_source        TEXT,
  design_group_id       TEXT REFERENCES design_groups(id) ON DELETE SET NULL,
  status                TEXT NOT NULL DEFAULT 'referenced'
                          CHECK (status IN ('referenced','trained')),
  status_computed_at    TEXT,
  needs_review          INTEGER NOT NULL DEFAULT 0,
  review_reason         TEXT,
  last_seen_in_catalog_at TEXT,                -- détection « disparue d'un re-scrape »
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at            TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (ref_source, ref_native_id)
);
CREATE INDEX idx_coins_status        ON coins(status);
CREATE INDEX idx_coins_design_group  ON coins(design_group_id) WHERE design_group_id IS NOT NULL;
CREATE INDEX idx_coins_needs_review  ON coins(needs_review) WHERE needs_review = 1;
CREATE INDEX idx_coins_country_year  ON coins(country, year);
CREATE TRIGGER coins_touch_updated_at AFTER UPDATE ON coins
BEGIN UPDATE coins SET updated_at = datetime('now') WHERE eurio_id = NEW.eurio_id; END;
```

- `numista_id` n'est plus une colonne écrite à la main : **colonne générée**
  depuis `ref_native_id` → impossible de désynchroniser.
- `mintage` promu en colonne (filtrable/triable — rareté, critères de sets).
- `last_seen_in_catalog_at` : la génération le rafraîchit ; une pièce absente
  du dernier scrape → `needs_review=1`, `review_reason='absent_from_catalog'`,
  **jamais supprimée** (la suppression cascade-orphelinerait images/cohortes).
- Anciens `first_seen`/`last_updated`/`imported_at` → fusionnés dans
  `created_at`/`updated_at` à la migration.

### `coin_national_variants` — pays participants d'une émission commune

Un joint-issue = **une** ligne `coins` avec `country='eu'`. Cette table liste
les pays participants.

```sql
CREATE TABLE coin_national_variants (
  eurio_id     TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  country_iso2 TEXT NOT NULL,
  PRIMARY KEY (eurio_id, country_iso2)
) WITHOUT ROWID;
```

### `coin_cross_refs` — références externes non-référentielles

```sql
CREATE TABLE coin_cross_refs (
  eurio_id  TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  ref_type  TEXT NOT NULL,            -- 'wikipedia_url', …
  ref_value TEXT NOT NULL,
  PRIMARY KEY (eurio_id, ref_type)
);
CREATE INDEX idx_coin_cross_refs_value ON coin_cross_refs(ref_type, ref_value);
```

### `coin_observations` — observations hétérogènes par source

```sql
CREATE TABLE coin_observations (
  id               INTEGER PRIMARY KEY,
  eurio_id         TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  source           TEXT NOT NULL,     -- 'wikipedia','bce','lmdlp','mdp','ebay'
  observation_type TEXT NOT NULL,     -- 'market_stats','variant',…
  payload_json     TEXT NOT NULL,
  recorded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (eurio_id, source, observation_type)   -- sémantique : dernier état par source
);
CREATE INDEX idx_coin_observations_eurio ON coin_observations(eurio_id);
```

`payload_json` reste un blob **volontairement** (observations de formes
variées). `mintage` n'y est plus — promu sur `coins`. La contrainte `UNIQUE`
impose une sémantique « dernier état par (pièce, source, type) », pas un
historique.

### `coin_canonical_images` — images de référence

Distinctes des images scrapées (`image_assets`).

```sql
CREATE TABLE coin_canonical_images (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  source     TEXT NOT NULL,           -- 'numista'
  role       TEXT NOT NULL CHECK (role IN ('obverse','reverse')),
  url        TEXT,
  local_path TEXT,                    -- clé sur eurio_id, PAS numista_id
  PRIMARY KEY (eurio_id, source, role)
) WITHOUT ROWID;
```

### `cohort_members` — remplace `experiment_cohorts.eurio_ids_json`

```sql
CREATE TABLE cohort_members (
  cohort_id TEXT NOT NULL REFERENCES experiment_cohorts(id) ON DELETE CASCADE,
  eurio_id  TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  PRIMARY KEY (cohort_id, eurio_id)
) WITHOUT ROWID;
```

Transition : backfill depuis `eurio_ids_json` (en tolérant les orphelins —
cohortes gelées pointant un `eurio_id` splitté/disparu → logués, pas insérés),
réécriture des méthodes `store.py`, puis suppression du blob quand tous les
lecteurs ont migré.

### `eurio_id_migrations` — journal de migration d'identité

Reshapé après audit : un `rename` se rejoue tel quel, un `split` ne peut **pas**
être rejoué en aveugle (quelle branche suivre ?) → il marque l'ancien id comme
`needs_rematch`.

```sql
CREATE TABLE eurio_id_migrations (
  id           INTEGER PRIMARY KEY,
  batch_id     TEXT NOT NULL,         -- regroupe les N lignes d'un même événement
  kind         TEXT NOT NULL CHECK (kind IN ('rename','split','merge','retire')),
  old_eurio_id TEXT NOT NULL,
  new_eurio_id TEXT,                  -- NULL pour 'retire' / split ambigu
  resolution   TEXT NOT NULL CHECK (resolution IN ('deterministic','needs_rematch')),
  status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','applied')),
  reason       TEXT,
  decided_by   TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_eurio_id_migrations_old ON eurio_id_migrations(old_eurio_id);
CREATE INDEX idx_eurio_id_migrations_new ON eurio_id_migrations(new_eurio_id);
```

- **rename** (1→1) : 1 ligne, `deterministic` → les dérivés suivent.
- **merge** (2→1) : N lignes même `new_eurio_id`, `deterministic`.
- **split** (1→2) : 1 ligne `retire` (`new_eurio_id NULL`, `needs_rematch`) +
  N lignes `split` pour les nouveaux ids. Les dérivés `needs_rematch` sont
  **re-matchés**, pas re-pointés en aveugle.
- C'est **cette table** qu'on exporte en JSON versionné git (réponse à la
  question « versioning des décisions humaines » de `architecture.md`).

### `image_assets.origin` — ALTER additif

```sql
ALTER TABLE image_assets ADD COLUMN origin TEXT
  CHECK (origin IN ('canonical','collected','synthetic'));
```

`collected` = scrapé (défaut implicite actuel), `synthetic` = augmenté. Ajouté
via `_ensure_column` (pas dans le `CREATE` de `schema.sql`, pour les DB
existantes).

### `v_orphan_eurio_refs` — vue QA (nouvelle)

`LEFT JOIN` de chaque colonne legacy qui référence `eurio_id` sans FK
(`source_images.target_eurio_id`, `image_assets.eurio_id`,
`training_run_classes.class_id`, `coin_market_quotes.eurio_id`, …) contre
`coins` → **observe** les orphelins. On n'en fait **pas** des FK : `target_eurio_id`
est une *hypothèse* de match autorisée à être fausse/nulle. `PRAGMA
foreign_key_check` en CI couvre les nouvelles tables qu'on contraint.

---

## Migration — séquence sûre (one-shot guardé, hors `executescript`)

Le piège n°1 : `CREATE TABLE IF NOT EXISTS coins` dans `schema.sql` est un
no-op sur la table existante → les nouvelles contraintes ne s'appliqueraient
**jamais** en silence. La refonte de `coins` exige un **rebuild 12-étapes**,
dans un script one-shot guardé (détection de l'ancien schéma via
`PRAGMA table_info`).

1. `wal_checkpoint(TRUNCATE)` + **backup du fichier `eurio.db`** (le rebuild
   `coins` est destructif).
2. `PRAGMA foreign_keys=OFF` sur la connexion de migration.
3. `BEGIN`. Créer `referential_catalog`, `design_groups`, tables filles
   `coin_*`, `cohort_members`, `eurio_id_migrations`.
4. Détecter l'ancien schéma `coins` (`PRAGMA table_info`). Si ancien : rebuild
   — `RENAME TO coins_legacy` → `CREATE TABLE coins` (nouveau) → `INSERT … SELECT`
   (`imported_at→created_at`, `ref_source='numista'`, `ref_native_id=numista_id`,
   `status='referenced'`) → `DROP coins_legacy`.
5. Backfill `cohort_members` depuis `experiment_cohorts.eurio_ids_json` (filtrer
   les `eurio_id` absents de `coins`, les loguer).
6. `COMMIT`. `PRAGMA foreign_key_check` (zéro ligne attendu sur les nouvelles
   tables ; les orphelins legacy sont attendus → `v_orphan_eurio_refs`).
7. `PRAGMA foreign_keys=ON`. Bootstrap normal `executescript`.
8. Générer `coins` depuis `referential_catalog` (Chunk 2 — marque les pièces
   absentes du catalogue).

Ordre des `CREATE` dans `schema.sql` : `referential_catalog`, `design_groups`,
`coins`, tables filles, `eurio_id_migrations`. Supprimer l'ancien bloc
`CREATE TABLE coins` (pas deux définitions dans le fichier).

## Ajustements d'implémentation — Chunk 1b (migration sûre)

L'audit prévoyait un **rebuild 12-étapes** de `coins` (RENAME → CREATE → COPY →
DROP) pour imposer `NOT NULL` + supprimer le blob. À l'implémentation, deux
faits ont fait choisir une migration **non destructive** (ALTER seulement) —
nettement plus sûre, conforme à la consigne « s'assurer que la migration se
passe bien » :

1. **2071 / 2628 pièces n'ont pas de `numista_id`** (référentiel actuel
   bootstrappé depuis Wikipédia ; seules ~688 sont matchées Numista). Donc
   `ref_source` / `ref_native_id` **doivent être NULLABLE** aujourd'hui — la
   contrainte `NOT NULL` est l'état cible *après* la génération Numista
   (Chunk 2), pas l'état transitoire. La contrainte d'unicité est posée via
   `CREATE UNIQUE INDEX` (les NULL sont distincts en SQLite) — ALTERable, pas
   besoin de rebuild.

2. **`raw_payload_json` et `imported_at` sont conservés transitoirement.** La
   migration **décompose** le blob dans les tables filles (`coin_cross_refs`,
   `coin_observations`, `coin_canonical_images`, `coin_national_variants`)
   mais **ne le supprime pas** : `api/bench_routes.py` et
   `bootstrap_coins_from_referential.py` le lisent encore. Le blob sera retiré
   dans un chunk ultérieur, une fois ces lecteurs rebranchés sur les tables
   filles. Décomposer-et-garder = migration étagée, pas de la dette.

3. **`numista_id` reste une colonne simple** (pas `GENERATED`) : une colonne
   générée casse tout `INSERT` qui la mentionne (tests, outillage). Pendant la
   transition, `numista_id` et `ref_native_id` sont posés ensemble par la
   migration puis par la génération Chunk 2 — un seul write-path, pas de
   dérive. Le passage en colonne générée est un durcissement pour Chunk 2+.

4. **`(ref_source, ref_native_id)` n'est PAS unique** — découvert en vérifiant
   avant de créer l'index. Une pièce de **circulation** réutilise un seul
   `numista_id` sur N millésimes (ex. nid 135 = 23 pièces, nid 87 = 16). Le
   « 1:1 sur numista_id » de l'architecture ne vaut que pour les
   **commémoratives** ; la circulation est `(numista_id, année) → eurio_id`.
   Donc index **non unique** ici ; l'unicité réelle est gérée par la logique
   de génération (Chunk 2).

Conséquence : **pas de rebuild de `coins`** — que des `ALTER TABLE ADD COLUMN`
(idempotents via `_ensure_column`) + `CREATE … IF NOT EXISTS` pour les tables
filles + un `CREATE UNIQUE INDEX`. Le piège n°1 de l'audit (le `CREATE TABLE
IF NOT EXISTS` no-op) **disparaît** : on ne redéfinit jamais `coins`. La
migration one-shot devient une pure **migration de données** (backfill des
nouvelles colonnes + remplissage des tables filles + backfill
`cohort_members`), idempotente et re-jouable, le schéma lui-même étant posé par
`Store._bootstrap`.

## Reste à spécifier (Chunk 2)

- La **règle de dérivation du slug `eurio_id`** depuis une entrée
  `referential_catalog` (pays + année + valeur + slug de thème) et sa
  stabilité face à un re-scrape — c'est le cœur de la génération.
- Durcissement : `ref_source` / `ref_native_id` en `NOT NULL`, `numista_id` en
  colonne générée — une fois toutes les pièces ancrées à une source
  référentielle (rebuild propre de `coins` à ce moment-là).
