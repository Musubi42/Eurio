# Chantier C — Mintage par atelier × qualité, et **cohérence DB**

> Objectif : reproduire (en mieux) la table mintage A/D/F/G/J × BE/BU/UNC de
> 2euros.org, en s'inscrivant proprement dans **referential-v2** sans créer
> de drift.

## ⚠️ Le vrai sujet de ce chantier : la cohérence

Avant même de parler de mintage, il faut résoudre un problème structurel
identifié en investiguant :

### Le schéma `coin_mint_releases` existe… mais ailleurs

| Élément | État |
|---|---|
| Schéma V2 (`coin_variants`, `coin_mint_releases`, `coin_source_refs`) | ✅ migré dans **Supabase** (`20260515_referential_v2.sql`) |
| `coin_variants` | 40 lignes dans Supabase |
| **`coin_mint_releases`** | **0 ligne dans Supabase, table inexistante dans `eurio.db`** |
| Schéma local `eurio.db` | ❌ V2 jamais miroité — seul `coin_national_variants` existe |
| `mint_release_prices` (Numista 7 grades) | ✅ migré Supabase, vide aussi |

### Le conflit de "source de vérité"

- Mémoire `feedback_architecture_eurio_db_vs_supabase` : **`eurio.db` =
  canonique dev local**, Supabase = cible Android future
- Mémoire `project_data_harmonization` : architecture tranchée, SQLite
  unique `eurio.db` canonique
- **Réalité 2026-05-25** : referential-v2 vit uniquement dans Supabase. Donc
  pour les Types/Variants V2, **Supabase est déjà devenu canonique de facto**
  pour ces tables.

→ **Décision à prendre dans ce chantier** : on miroite V2 dans `eurio.db`
ou on accepte officiellement que `eurio.db` ne contient que le sous-ensemble
V1 + tables d'enrichissement Python (sources, embeddings, runs), Supabase
porte le référentiel V2 ?

## État des lieux mintage

### Côté V1 (aujourd'hui)

```sql
coins.mintage         INTEGER   -- agrégat total
coins.mintage_source  TEXT      -- 'numista' | 'bce' | 'manual'
```

Une ligne `coins` = un Type. Le mintage stocké est le **total** toutes
ateliers/qualités confondues (ou ce que la source primaire a fourni).

État réel : `mintage` rempli partiellement (BCE expose le total pour ~493
pièces), pas de breakdown par atelier.

### Côté V2 (cible) — ⚠️ schéma historique, **OBSOLÈTE**

> ⚠️ **Cette DDL est l'ancienne version Supabase, conservée pour traçabilité.**
> Le schéma cible **est celui de la section "Pattern : identity + observations
> par source" ci-dessous** : identity-only (pas de `mintage`/`released_on` dans
> la table), FK `mint_id` vers `mints` (pas de `mint_mark TEXT` brut), sans
> colonne `confidence`. Ne pas implémenter cette version-ci.

```sql
-- HISTORIQUE — ne pas implémenter
CREATE TABLE coin_mint_releases (
  id              text PRIMARY KEY,                    -- '{parent_type_id}/{mint_year}/{mint_mark}/{issue_type}'
  parent_type_id  text NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  mint_year       int  NOT NULL,
  mint_mark       text,                                -- 'A','D','F','G','J' | NULL
  issue_type      text NOT NULL CHECK (issue_type IN (
    'CIRC', 'BU', 'BE', 'PROOF', 'COIN_CARD', 'OTHER'
  )),
  mintage         bigint,
  released_on     date,
  notes           text
);
```

**Mapping 1:1 propre avec 2euros.org**. La table Bremen → 15 lignes
(5 ateliers × 3 issue_types) avec `parent_type_id = 'de-2010-2eu-breme'`.

### ⚠️ Erreur de doc à corriger

Le commentaire de la migration dit :
> "A/D/F/G/J pour Allemagne (cents). NULL pour les pays sans marque (la plupart des 2€ commémos)."

C'est **faux** pour les 2€ commémos DE : la Bremen 2010 a bien des marques
A/D/F/G/J (cf. tableau 2euros.org). À corriger dans la migration suivante.

## Questions à trancher

### Q1 — Cohérence eurio.db ↔ Supabase pour V2

**Le sujet structurant du chantier.** Trois options :

**(a) Mirror V2 dans `eurio.db`** — copier les tables `coin_variants`,
`coin_mint_releases`, `coin_source_refs`, `mint_release_prices` dans le
schéma SQLite, et créer un mécanisme de sync bidirectionnel (ou one-way
Supabase→SQLite).
- ➕ `eurio.db` reste la source unique pour tout le code Python
- ➕ pas de dépendance réseau pour le dev local
- ➖ sync à maintenir (drift = bug silencieux)
- ➖ duplication d'effort sur chaque nouvelle migration V2

**(b) Acter le split** — `eurio.db` ne contient que V1 + tables
d'enrichissement (runs, sources, embeddings, training, review_queue).
Supabase porte le référentiel V2. Pour lire un mint_release côté Python,
on requête Supabase.
- ➕ pas de sync, une seule vérité par domaine
- ➖ casse la promesse "tout en local" (dev needs Supabase auth)
- ➖ contredit les mémoires `project_data_harmonization` et
  `feedback_architecture_eurio_db_vs_supabase`

**(c) Inverser la canonicité V2** — `eurio.db` devient canonique pour V2
aussi, on **migre les 40 variants de Supabase vers SQLite** et on fait un
push vers Supabase pour Android.
- ➕ aligne sur la doctrine déjà actée
- ➕ tout le tooling Python lit local
- ➖ refonte de la migration `20260515_referential_v2.sql` côté SQLite
- ➖ remettre en cohérence Supabase post-coup (40 variants + futures
  mint_releases)

**Reco** : **(c)**. C'est l'option qui respecte la doctrine déjà actée,
même si c'est le plus de travail. Sinon on accumule la dette de
"où vit quoi". Le chantier C devient l'occasion de **rattraper la
canonicité** sur le sujet.

### Q2 — Que devient `coins.mintage` une fois `coin_mint_releases` peuplée ?

Aujourd'hui : `coins.mintage` INTEGER, agrégat. Demain : N lignes
`coin_mint_releases.mintage` à sommer.

**(a) `coins.mintage` devient un cache** — colonne maintenue par trigger
(SUM des mint_releases du parent_type)
- ➕ pas de breaking change pour les lecteurs actuels
- ➖ trigger SQLite + Supabase à maintenir, source de bugs

**(b) `coins.mintage` devient `mintage_legacy`** — gardé pour les pièces
non-décomposées (pas de mint_releases peuplées), NULL sinon
- ➕ pas de duplication d'écriture
- ➖ logique de lecture : `COALESCE(SUM(mr.mintage), c.mintage_legacy)`
- ➖ ambiguïté : si mint_releases est partielle, on peut sous-estimer

**(c) `coins.mintage` désaffectée** — toutes les lectures passent par
mint_releases ; pour les pièces non-décomposées, on insère **1 ligne
unique** dans mint_releases (mint_mark NULL, issue_type CIRC) avec le
total.
- ➕ une seule vérité, plus de coexistence
- ➕ uniforme : toute pièce a au moins 1 mint_release
- ➖ migration : créer ~500 lignes mint_releases "fallback" pour les
  pièces dont on n'a que le total

**Reco** : **(c)**. C'est cohérent avec "le détail englobe l'agrégat", et
ça évite la gymnastique COALESCE / le risque de cache désynchro.

### Q3 — Granularité du bootstrap

Toutes les pièces n'ont pas de breakdown public. Réalité :

| Pays | Breakdown atelier × qualité disponible ? | Source |
|---|---|---|
| DE | ✅ 5 ateliers × 3 qualités | Bundesbank, repris par 2euros.org |
| AT | ✅ 1 atelier mais BU/BE distincts | Münze Österreich |
| FR | ⚠️ MdP publie BU/BE/proof, pas d'atelier (Pessac unique) | MdP |
| ES | ⚠️ 1 atelier (M), BU/BE distincts | FNMT |
| IT | ⚠️ 1 atelier (R), BU/BE distincts | IPZS |
| NL | ⚠️ 1 atelier (utrecht), BU/BE | KNM |
| Autres (PT, BE, GR, IE, LU, SK, SI, EE, CY, MT, LT, LV, FI, AD, MC, SM, VA, HR, BG) | ❌ ou très partiel | — |

**(a)** Bootstrap **tous** les pays, mintage NULL quand inconnu →
mint_releases partielles, l'absence de ligne signifie "non-frappé", l'absence
de `mintage` signifie "inconnu".

**(b)** Bootstrap **seulement les pays avec données fiables** (DE complète,
AT/FR/ES/IT/NL partielle) → ~70 % du catalogue couvert proprement, le
reste reste en `coins.mintage` total.

**Reco** : **(a)**, conjugué à Q2(c). Toute pièce a au moins 1 mint_release.
Pour les pays sans détail, c'est 1 ligne `(mint_mark=NULL, issue_type='CIRC',
mintage=<total connu ou NULL>)`. Pour DE, c'est 15 lignes. Granularité
adaptative, mais structure homogène.

### Q4 — Sources de bootstrap

Pour DE (le seul qui justifie le détail) :

- **Bundesbank** publie des PDF annuels par Land — données officielles, peu
  scrappables (PDF tabulaires). Travail ~2 jours.
- **2euros.org** affiche déjà la table → scrape rapide possible mais
  data-of-data (qualité inconnue, pas de provenance)
- **Numista API** : champ `mintage` par `mint` dans `/coins/{id}` (à
  vérifier sur leur free tier — overlap avec budget Chantier D)
- **Wikipedia DE** : tableaux exhaustifs sur la plupart des commémos DE

**Reco** : **Numista API** en priorité (mutualisable avec D : 1 call par
pièce sert et à designer/JOUE et au mintage breakdown). Fallback
Wikipedia DE pour les pièces où Numista n'a pas l'info.

### Q5 — `release_date` (Chantier D) : sur quel niveau ?

Dans Chantier D on a tranché : `coins.release_date` ISO partial. Mais avec
mint_releases, chaque émission a sa **propre** `released_on date`.

Trois articulations possibles :

**(a)** `coins.release_date` = première date de release (min des
`mint_releases.released_on`), maintenue par trigger
**(b)** `coins.release_date` désaffecté, lecture via
`MIN(mint_releases.released_on)` ad-hoc
**(c)** `coins.release_date` = date "officielle" (souvent la BCE) qui peut
différer de la première frappe atelier

**Reco** : **(c)**. La date officielle BCE (`issuing_date` déjà scrapé) est
la date que le grand public connaît (1er février 2010 pour Bremen). Les
dates atelier sont du détail numismatique qui peut diverger sans que ça
casse le récit public. Stocker les deux : `coins.release_date` (officielle,
ce qu'on affiche par défaut) + `mint_releases.released_on` (atelier, pour
drill-down).

### Q6 — Alignement `coin_market_quotes` avec V2

Aujourd'hui : `coin_market_quotes.eurio_id` → niveau Type. Source eBay agrège
au niveau Type (les annonces eBay ne précisent que rarement l'atelier).

Demain avec V2 : on a deux granularités de prix légitimes :

1. **eBay (`coin_market_quotes`)** — agrège au niveau Type × condition,
   continue tel quel (eBay ne sait pas l'atelier)
2. **Numista (`mint_release_prices`)** — par mint_release × grade
   (7 grades Numista), pour les pièces où Numista expose des prix

Pas de conflit : ce sont deux sources qui répondent à deux questions
différentes ("combien sur le marché secondaire ?" vs "combien le catalogue
estime un BE atelier J ?").

**Reco** : **garder les deux tables**, exposer côté API admin un endpoint
unifié qui agrège les sources disponibles pour une pièce donnée.

## Schéma — synthèse migration locale `eurio.db` (option Q1c)

> ⚠️ **DDL OBSOLÈTE — voir la version "Pattern : identity + observations par
> source" plus bas.** Cette section ci-dessous est conservée pour montrer la
> bascule. Les différences :
>
> - Pas de `mintage`/`released_on` dans `coin_mint_releases` (déplacés vers
>   `mint_release_observations`)
> - Pas de `mint_mark TEXT` brut → FK `mint_id` vers `mints` (slug normalisé)
> - Pas de colonne `confidence` (la doctrine s'en passe)
>
> **Le schéma cible est celui de la §"Pattern" ci-dessous, à jour avec la
> doctrine de provenance.**

```sql
-- HISTORIQUE — ne pas implémenter tel quel.
-- 1. coin_variants (OK tel quel)
CREATE TABLE IF NOT EXISTS coin_variants (
  id              TEXT PRIMARY KEY,
  parent_type_id  TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  finish          TEXT NOT NULL CHECK (finish IN ('classic','coloured','hologram','gilded','pattern','mule','misstrike','other')),
  obverse_url     TEXT,
  reverse_url     TEXT,
  notes           TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. coin_mint_releases — version OBSOLÈTE (mintage/mint_mark in-line)
-- → voir version révisée plus bas

-- 3. coin_source_refs — voir DDL canonique dans ROADMAP-DB.md §4.3

-- 4. mint_release_prices (OK, FK source à ajouter au moment de l'implémentation)
CREATE TABLE IF NOT EXISTS mint_release_prices (
  id               INTEGER PRIMARY KEY,
  mint_release_id  TEXT NOT NULL REFERENCES coin_mint_releases(id) ON DELETE CASCADE,
  source           TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  source_ref       TEXT,
  grade_raw        TEXT NOT NULL CHECK (grade_raw IN ('g','vg','f','vf','xf','au','unc')),
  grade_eurio      TEXT CHECK (grade_eurio IN ('UNC','TTB','TB')),
  price            REAL NOT NULL,
  currency         TEXT NOT NULL DEFAULT 'EUR',
  fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (mint_release_id, source, grade_raw, fetched_at)
);

-- 5. Désaffectation coins.mintage (Q2c) : voir ROADMAP-DB.md §7 (P.* + C.3)
```

Et **sync inverse vers Supabase** : un script one-shot qui rapatrie les 40
variants existants depuis Supabase vers `eurio.db` (pour ne pas les perdre)
puis push les mint_releases bootstrappés vers Supabase.

## Livrables — découpage

| # | Chunk | Effort | Bloqué par |
|---|---|---|---|
| C.0 | Trancher Q1 (cohérence V2 eurio.db ↔ Supabase) | discussion | rien |
| C.1 | Migration SQLite : `coin_variants` + `coin_mint_releases` + `coin_source_refs` + `mint_release_prices` (additif) | ~1 h | C.0 |
| C.2 | Rapatriement Supabase→SQLite des 40 variants existants + audit | ~1 h | C.1 |
| C.3 | Bootstrap **fallback** : 1 mint_release par coin avec `mintage` existant (Q2c) | ~1 h | C.1 |
| C.4 | Bootstrap **DE détaillé** : 5×3 mint_releases pour les commémos DE via Numista API (mutualisable avec D.3) | ~2 h | C.1, D.3 |
| C.5 | Bootstrap **autres pays partiels** : BU/BE quand connu, fallback CIRC sinon | ~2 h | C.1 |
| C.6 | Push SQLite→Supabase (sync sortante) | ~1 h | C.3-C.5 |
| C.7 | Désaffectation `coins.mintage` : retirer des écritures, garder lecture COALESCE temporairement | ~1 h | C.3 |
| C.8 | API admin : endpoint `/api/coins/{id}/mint_releases` + UI table A×qualité | ~3 h | C.6 |

## Décisions tranchées (2026-05-25)

### Décision structurante (nouvelle doctrine)

**`eurio.db` est LA source de vérité, point.** On arrête la doctrine "front
front lit Supabase pour être universellement accessible". Trop de couplage,
trop de double-stockage. Cf. mémoire
[[feedback-sqlite-only-doctrine]].

Conséquences immédiates :
- Admin Vue (dev local) → API Python ml/ → `eurio.db`. Plus de SDK
  Supabase pour lire le référentiel.
- Toute nouvelle table de schéma référentiel va dans `ml/state/schema.sql`,
  PAS dans `supabase/migrations/`.
- referential-v2 (40 variants + schéma `coin_mint_releases` vide) doit être
  **rapatrié dans eurio.db**.
- Supabase reste pour l'app Android future (cible) ; quand on aura besoin
  d'y pousser, ce sera un **sync sortant explicite**.

### Principe — provenance first-class, pas de fallback silencieux

**Chaque fact en DB porte sa source.** Si deux sources divergent (BCE vs
Numista sur la date d'émission, par ex.), on garde les **deux lignes**, on
n'écrit pas un consensus qui efface l'origine. Admin verra les divergences
et tranchera éditorialement (déjà le pattern `coin_observations`, à
généraliser).

### Réponses aux Q

| # | Question | Décision |
|---|---|---|
| Q1 | Cohérence V2 | **(c) Rapatriement eurio.db**, Supabase plus canonique pour le référentiel |
| Q2 | `coins.mintage` | **Désaffecté** : 1 mint_release fallback par pièce, identity portée par `coin_mint_releases` |
| Q3 | Bootstrap | **Tous les pays**, mais **provenance loggée** (table observations), pas de fallback silencieux |
| Q4 | Source primaire | **Numista en priorité**, autres sources viennent **enrichir** (pas fallback), chacune trace son origine |
| Q5 | `release_date` | **Deux sources distinctes BCE + atelier** affichées séparément, pas une "officielle" qui masque l'autre |
| Q6 | Prix multi-source | **Schéma multi-source explicite** : eBay + Numista + MdP + autres, tous en parallèle, chacun visible |

## Reformulation du schéma avec provenance first-class

### Pattern : identity + observations par source

Au lieu d'avoir des colonnes "fact + fact_source" sur l'identity (ex
`mintage` + `mintage_source` sur `coin_mint_releases`), on sépare :

```sql
-- IDENTITY : ce qui définit *l'objet* (pas de fait observable, juste l'identité)
CREATE TABLE coin_mint_releases (
  id              TEXT PRIMARY KEY,                        -- '{parent}/{year}/{mint_id|noMint}/{type}'
  parent_type_id  TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  mint_year       INTEGER NOT NULL,
  mint_id         TEXT REFERENCES mints(id) ON DELETE RESTRICT,    -- NULL = atelier inconnu/non-décomposé
  issue_type      TEXT NOT NULL CHECK (issue_type IN ('CIRC','BU','BE','PROOF','COIN_CARD','OTHER')),
  notes           TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (parent_type_id, mint_year, mint_id, issue_type)
);

-- OBSERVATIONS : facts attribués à des sources (une ligne par source qui a observé)
-- Pas de colonne `confidence` : la doctrine la juge flottante. La confiance se
-- déduit en lecture (registry.kind + COUNT(DISTINCT source) GROUP BY fact).
-- Pas de CHECK strict sur fact_type : laisser libre pour absorber les facts
-- découverts pendant la cohorte (mintage, released_on, frequency, notes, ...).
CREATE TABLE mint_release_observations (
  id              INTEGER PRIMARY KEY,
  mint_release_id TEXT NOT NULL REFERENCES coin_mint_releases(id) ON DELETE CASCADE,
  fact_type       TEXT NOT NULL,                          -- 'mintage'|'released_on'|'frequency'|'notes'|...
  value_json      TEXT NOT NULL,                          -- {"value": 5805250} ou {"date": "2010-01-29", "precision": "day"}
  source          TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  source_ref      TEXT,                                   -- URL/ID dans la source
  observed_at     TEXT NOT NULL DEFAULT (datetime('now')),
  notes           TEXT,
  UNIQUE (mint_release_id, fact_type, source)
);
CREATE INDEX idx_mro_release ON mint_release_observations(mint_release_id);
CREATE INDEX idx_mro_fact    ON mint_release_observations(fact_type);
CREATE INDEX idx_mro_source  ON mint_release_observations(source);
```

→ Pour afficher 2euros.org-style "Bremen atelier A : 5 805 250 UNC" on lit
les **observations** où `fact_type='mintage'`. S'il y a une seule source
(Numista) on affiche la valeur. S'il y a divergence (Numista 5 800 000 vs
Bundesbank 5 805 250) on affiche les deux + un badge "à arbitrer".

### Idem pour `coins` — release_date, designer, JOUE

⚠️ **Cela change ce qu'on avait tranché dans Chantier D** (où on avait dit
`coins.release_date` typé). Avec la doctrine "provenance first-class", on
re-route vers observations :

```sql
-- coin_observations est drop+recreate dans P.3 (SQLite n'a pas ALTER ADD CONSTRAINT,
-- on profite du wipe pour porter la FK source). Pas de colonne `confidence` :
-- la doctrine la juge flottante (cf. ROADMAP-DB.md §2.2).
-- Forme post-P.3 :
CREATE TABLE coin_observations (
  id               INTEGER PRIMARY KEY,
  eurio_id         TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  source           TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  source_ref       TEXT,
  observation_type TEXT NOT NULL,
  payload_json     TEXT NOT NULL,
  recorded_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (eurio_id, source, observation_type)
);

-- Usage :
-- INSERT INTO coin_observations(eurio_id, source, observation_type, payload_json, source_ref)
--   VALUES ('de-2010-2eur-bremen-presidency', 'bce_official',
--           'release_date', '{"date":"2010-01-29"}', 'https://www.ecb.europa.eu/...');
-- INSERT INTO coin_observations(eurio_id, source, observation_type, payload_json, source_ref)
--   VALUES ('de-2010-2eur-bremen-presidency', 'numista_api',
--           'release_date', '{"date":"2010-02-01"}', 'https://numista.com/...');
```

→ Page admin affiche `release_date BCE: 29/01/2010` et
`release_date Numista: 01/02/2010` côte à côte.

Pour `coin_credits` (designer) : on garde la table dédiée mais `source` est
**obligatoire** et **PK partielle** ; deux sources peuvent attribuer le
même rôle à des personnes différentes — on garde les deux lignes.

```sql
-- (mise à jour chantier-D, FK source ajoutée)
CREATE TABLE coin_credits (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('designer','engraver','sculptor')),
  name       TEXT NOT NULL,
  source     TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  source_ref TEXT,
  position   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (eurio_id, role, name, source)              -- source en PK : 2 sources peuvent attribuer différemment
);
```

### Prix multi-source — élargir le pattern

Aujourd'hui on a `coin_market_quotes` (eBay) et `mint_release_prices`
(Numista). Avec multi-source explicite, on peut accueillir MdP, La Monnaie
de Paris, autres sites :

Choix : **garder les deux tables séparées** (granularité Type vs
mint_release) ou **fusionner** ?

**Reco** : garder séparées **mais aligner le pattern** :

```sql
-- coin_market_quotes : prix Type-level (sources qui ne décomposent pas par atelier — eBay, parfois LMDLP)
-- mint_release_prices : prix mint_release-level (sources qui décomposent — Numista, MdP catalogue)
-- Les deux sont drop+recreate en P.3 (FK source → source_registry, ON DELETE RESTRICT)
-- et portent `source_ref TEXT`. Pas de colonne `confidence` (doctrine).
```

Lecture unifiée côté API : un endpoint `/api/coins/{eurio_id}/prices`
remonte les deux tables, grouped by source, sans masquer aucune source.

## Sources de bootstrap envisagées (extensible)

| Source | Couverture | Niveau de détail | Statut |
|---|---|---|---|
| **Numista** API | ~688 commémos | Type + variant + mint × mark + grades | source primaire (autorisé 500 calls) |
| **BCE** | ~493 pièces | Type + issuing_date + mintage total | déjà scrapé, à brancher |
| **Bundesbank** | DE uniquement | mint × mark × année × format | scrape PDF, ~2j travail |
| **La Monnaie de Paris** (MdP) | FR + collector | prix BU/BE neufs, descriptions | déjà scrapé partiel |
| **LMDLP** (lemondedespiecesdeuros) | FR commémos | prix marché secondaire, variants | déjà scrapé 278 pièces |
| **Wikipedia DE** | DE commémos | tirages détaillés | scrape gratuit, fallback |
| **Münze Österreich, FNMT, IPZS, KNM** | AT/ES/IT/NL | mintage officiel par pays | scrape par pays |
| **eBay Browse** | ouvert | prix marché secondaire | déjà en place |

→ Schéma prévoit toutes ces sources sans changement. Chaque source est juste
une chaîne dans `observations.source` / `prices.source`.

## Livrables — découpage révisé

| # | Chunk | Effort | Notes |
|---|---|---|---|
| **C.0** | ✅ Décision doctrine SQLite-only actée | — | mémoire écrite |
| C.1 | Migration SQLite : `coin_variants` + `coin_mint_releases` + `mint_release_observations` + `mint_release_prices` + extensions `coin_observations` (confidence, source_ref) + extensions `coin_market_quotes` (source_ref) | ~2 h | un seul commit, additif |
| C.2 | Rapatriement Supabase → SQLite des 40 variants + 4274 source_refs existants | ~1 h | one-shot, audit |
| C.3 | Bootstrap **fallback** : pour chaque coin avec `coins.mintage NOT NULL`, créer 1 `coin_mint_release` (mark=NULL, type=CIRC) + 1 `mint_release_observation(mintage, source=coins.mintage_source)` | ~1 h | préserve la donnée, source tracée |
| C.4 | Bootstrap **Numista détaillé** : 500 calls `/coins/{id}` → designer + JOUE + mint × mark × format × mintage + release_dates | ~3 h | mutualisé avec D.3 |
| C.5 | Bootstrap **BCE** : `issuing_date` → `coin_observations(release_date, source='bce')` (~493 pièces) | ~30 min | déjà scrapé |
| C.6 | Découplage admin Vue ↔ Supabase : tous les reads référentiels passent par API ml/ | ~3 h | gros chantier UI |
| C.7 | API admin : endpoints `/coins/{id}/mint_releases`, `/coins/{id}/observations`, `/coins/{id}/prices` (groupés par source) | ~2 h | dépend C.1-C.5 |
| C.8 | UI admin : page coin enrichie — table A×qualité + bloc observations multi-source avec affichage divergences | ~4 h | dépend C.7 |
| C.9 | **Sync sortant SQLite → Supabase** (one-way) pour préparer Android | ~2 h | à n'allumer que quand Android en a besoin |

## Impact sur les autres chantiers

- **Chantier D** doit être révisé : `coins.release_date` typé **annulé**,
  remplacé par `coin_observations(release_date, source=...)`. Les autres
  décisions D tiennent. `coin_credits` voit `source` passer en PK.
- **Chantier A** (cote eBay) : pas d'impact direct, `coin_market_quotes`
  déjà source-aware. Ajout cosmétique de `source_ref` et `confidence`.
- **Chantier B** (rareté dérivée) : devra agréger les prix multi-source —
  formule à affiner quand on aura plusieurs sources de prix actives.
- **Chantier E** (admin UI) : devient plus ambitieux — il faut un design qui
  rend lisibles les divergences entre sources (pas juste afficher des
  valeurs).

## Questions encore ouvertes

1. **Confidence enum** : `'confirmed' | 'reported' | 'estimated' | 'disputed'` →
   les 4 niveaux suffisent ? Ou on calque sur trust model existant
   (`confirmed | bce_only | numista_only | ... | manual`) ?
2. **Sync Supabase sortant** : à quel rythme ? trigger manuel ? cron ?
   Quand on attaquera Android, on tranchera. Pour l'instant, C.9 reste à
   *préparer* mais pas à activer.
3. **`coin_observations` actuel vs nouveau pattern** : aujourd'hui contient
   2628 lignes `legacy_import` avec sources `wikipedia`, `lmdlp_variants`,
   etc. À auditer : sont-elles bien typées pour le nouveau pattern ou
   faut-il les migrer ?
4. **Rapatriement Supabase coins (2736 lignes)** : aujourd'hui Supabase a
   2736 coins, eurio.db a un sous-ensemble. À auditer le delta avant la
   migration. Pas trivial.

## Risques

- **Refonte canonicité V2 (Q1c)** : c'est le plus gros chantier de cohérence
  jamais fait dans le repo. Risque de drift pendant la transition (Supabase
  et SQLite divergent). Mitigation : tout en une session, freeze des écritures
  V2 côté Supabase pendant la migration.
- **Numista API trous** : tous les coins n'ont pas le breakdown atelier. On
  acceptera des `mintage = NULL` sur certaines mint_releases.
- **Erreur du commentaire migration** : à corriger lors de la migration
  SQLite (et ré-aligner Supabase via un fix-up commentaire).
- **Audit Supabase** : si quelqu'un a déjà inséré des mint_releases en prod
  (peu probable vu le 0 row, mais à vérifier), bien rapatrier.
