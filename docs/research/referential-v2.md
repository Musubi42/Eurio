# Référentiel Eurio V2 — Type / Variant / MintRelease

> Statut : design draft 2026-05-15. Brainstorm validé, schéma à figer avant migration.
> Remplace progressivement le modèle V1 documenté dans `data-referential-architecture.md`.

---

## 1. Pourquoi V2

### 1.1 Le déclencheur

Pipeline actuel : `Numista catalog → eurio_referential → eBay scrape` itère sur les
`eurio_id`. Toute pièce 2€ qui existe sur Numista mais n'a pas de `eurio_id` est
invisible pour la collecte de prix/images. Objectif initial : combler ce gap.

### 1.2 Ce que l'audit a révélé (684 entrées 2€ du catalog Numista)

| Classification                | Action requise         | Count | %    |
| ----------------------------- | ---------------------- | ----: | ---: |
| IN_REF_OK (commémos OK)       | KEEP                   |   385 | 56 % |
| IN_REF_OK_STANDARD            | KEEP                   |    41 |  6 % |
| ORPHAN_NEW_TYPE               | CREATE_NEW_TYPE        |   151 | 22 % |
| IN_REF_WRONG (commémos)       | REMATCH                |    58 |  8 % |
| ORPHAN_VARIANT_OF_MATCHED     | ADD_AS_VARIANT         |    19 |  3 % |
| IN_REF_BUT_VARIANT            | MOVE_TO_VARIANT        |    15 |  2 % |
| IN_REF_UNCERTAIN              | REVIEW                 |     9 |  1 % |
| ORPHAN_VARIANT_NO_PARENT_YET  | ADD_AS_VARIANT (delay) |     6 |  1 % |

**Lectures clés** :

- Schéma V1 `identity = {country, year, face_value, theme}` n'a qu'un **slot
  unique** par tuple (pays, année, denom, commémo). Numista a en revanche
  jusqu'à 5+ commémos pour le même tuple (FR 2015, LU 2025 Schuman, NL 2015
  EU Flag, …) → 132 groupes Numista sous-représentés, 159 entrées 2€ "perdues".
- Le `batch_match_numista.py` accepte un match exact_key dès qu'il y a un seul
  slot ref candidat. Quand le catalog a N nids pour ce slot, il en pique un au
  hasard et le colle au slot → 58 matchings sémantiquement faux (ex : DE 2018
  "Helmut Schmidt" matché à "Bundesländer Berlin").
- **64 des 151 ORPHAN_NEW_TYPE sont des joint-issues** (Traité de Rome 2007,
  EMU 2009, 10 Ans Euro Cash 2012, EU Flag 2015, Erasmus 2022). Coordination
  multi-pays → même thème répété, scoring fuzzy s'embrouille.
- 34 variants (coloured / hologram / pattern / mule) sont aujourd'hui traités
  comme des types à plat. Coût technique faible si on a une vraie sous-table.

### 1.3 Le vrai besoin produit

Au-delà du scrape eBay, Raphaël vise :

1. **Échanges P2P** → prix précis dépendant de `(type, variant, mint_year, grade)`
2. **Multi-denomination** : 1€, cents, médailles 10€ MdP, sets BU/BE
3. **Pièces hors-Numista** : MdP éditions film, Catawiki collector, médailles
4. **Multi-référentiel additif** : pas de pivot unique, plusieurs sources peuvent
   déclarer un type, dédoublonnage en aval.

V1 ne peut pas porter ces besoins. V2 est conçu pour.

---

## 2. Architecture cible

### 2.1 Modèle conceptuel à 3 niveaux (+ 1 niveau utilisateur)

```
TYPE  (« quelle commémo / quel design ? »)
  │
  ├── 0..N  VARIANT      (« quel finish ? coloured / hologram / pattern / classic »)
  │
  ├── 0..N  MINT_RELEASE (« quel atelier × année × format ? — BU 2014 atelier X »)
  │
  └── 0..N  SPECIMEN     (« la pièce dans le coffre de Raphaël »)  ← Phase 5+
              ↳ grade (UNC / TTB / TB en MVP, échelle Sheldon plus tard)
```

### 2.2 Pourquoi 3 niveaux et pas 2

- Fusionner VARIANT et MINT_RELEASE casse le pricing. Une FR 2024 "JO Paris"
  existe en classic (circulation), classic BU, classic BE, **et** coloured.
  La coloured BU n'a pas le même prix que la classic BE. Avec 2 niveaux, on
  doit énumérer le produit cartésien (4 × 3 = 12 lignes) au lieu de 4 + 3.
- 3 niveaux laissent la porte ouverte aux pièces où seul l'atelier change
  (cents allemands : A/D/F/G/J × année) sans dupliquer les variants.

### 2.3 Schéma Supabase proposé

```sql
-- TYPE : la pièce canonique
CREATE TABLE coin_types (
  eurio_id         TEXT PRIMARY KEY,           -- ex: fr-2017-2eur-auguste-rodin
  issuer           TEXT NOT NULL,              -- ISO2 ou 'eu' pour joint-issues
  denomination_eur NUMERIC(6,2) NOT NULL,      -- 2.0, 0.5, 10.0…
  year_of_design   INT NOT NULL,               -- année du design (≠ mint year)
  series           TEXT,                       -- 'circulation' | 'national-commemorative'
                                               -- | 'joint-issue' | 'bundeslander' | 'mdp-collector' …
  theme            TEXT,                       -- string descriptif (libre)
  is_commemorative BOOLEAN NOT NULL DEFAULT FALSE,
  is_legal_tender  BOOLEAN NOT NULL DEFAULT TRUE,
  design_description TEXT,
  obverse_url      TEXT,                       -- image canonique (= variant 'classic')
  reverse_url      TEXT,
  design_group_id  TEXT REFERENCES design_groups(id),  -- réutilisé du V1
  created_at       TIMESTAMPTZ DEFAULT now(),
  updated_at       TIMESTAMPTZ DEFAULT now()
);

-- VARIANT : finition / déclinaison graphique d'un type
CREATE TABLE coin_variants (
  id               TEXT PRIMARY KEY,           -- ex: fr-2017-2eur-auguste-rodin/classic
  parent_type_id   TEXT NOT NULL REFERENCES coin_types(eurio_id) ON DELETE CASCADE,
  finish           TEXT NOT NULL,              -- 'classic' | 'coloured' | 'hologram'
                                               -- | 'gilded' | 'pattern' | 'mule' | …
  obverse_url      TEXT,                       -- spécifique au variant si différent
  reverse_url      TEXT,
  notes            TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);
-- Convention : tout type a au minimum 1 variant 'classic' (implicite ou matérialisé).

-- MINT_RELEASE : émission d'un type par atelier × année × format
CREATE TABLE coin_mint_releases (
  id               TEXT PRIMARY KEY,           -- ex: fr-2017-2eur-auguste-rodin/2017-bu
  parent_type_id   TEXT NOT NULL REFERENCES coin_types(eurio_id) ON DELETE CASCADE,
  mint_year        INT NOT NULL,
  mint_mark        TEXT,                       -- 'A'/'D'/'F'/'G'/'J' pour DE, null sinon
  issue_type       TEXT NOT NULL,              -- 'CIRC' | 'BU' | 'BE' | 'PROOF' | …
  mintage          INT,                        -- tirage si connu
  released_on      DATE,
  notes            TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

-- SOURCE_REFS : 1 type → N (source, native_id)
CREATE TABLE coin_source_refs (
  coin_type_id     TEXT NOT NULL REFERENCES coin_types(eurio_id) ON DELETE CASCADE,
  source           TEXT NOT NULL,              -- 'numista' | 'mdp' | 'lmdlp' | 'bce'
                                               -- | 'wikipedia' | 'catawiki' | 'wikidata' …
  native_id        TEXT NOT NULL,              -- ID natif côté source
  native_url       TEXT,
  fetched_at       TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (source, native_id)
);
-- Une source peut aussi pointer un variant (Numista distingue parfois), donc
-- variante envisageable : coin_variants_source_refs si besoin se confirme.

-- SPECIMEN (Phase 5+, pour le P2P trading)
CREATE TABLE coin_specimens (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL,              -- propriétaire
  variant_id       TEXT NOT NULL REFERENCES coin_variants(id),
  mint_release_id  TEXT REFERENCES coin_mint_releases(id),
  grade_simple     TEXT CHECK (grade_simple IN ('UNC','TTB','TB')),  -- MVP
  grade_sheldon    INT CHECK (grade_sheldon BETWEEN 1 AND 70),       -- futur, opt
  certified_by     TEXT,                       -- 'NGC' | 'PCGS' | null
  cert_number      TEXT,
  photos           JSONB,
  acquired_at      DATE,
  acquired_price   NUMERIC(10,2),
  notes            TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

-- PRICES : on garde la table existante coin_market_prices mais avec une cible
-- polymorphe : (target_kind, target_id) ∈ {('type', eurio_id), ('variant', variant_id), ('mint_release', release_id)}.
```

### 2.4 Backward compatibility avec V1

La table V1 actuelle `coins` migre vers `coin_types` en preservant tous les
`eurio_id` qui sont déjà des "TYPE" canoniques. Les champs `cross_refs` JSONB
existants se déversent dans `coin_source_refs`. Aucun `eurio_id` n'est cassé
côté snapshot Android (le snapshot continue de pointer un Type, pas un variant).

---

## 3. Multi-référentiel additif

### 3.1 Principe

Chaque source d'ingestion (Numista, MdP, BCE, Catawiki, …) émet des
**Type Candidates** — pas directement des `coin_types`. Un service de
dédoublonnage centralisé :

1. Cherche un Type existant via les `coin_source_refs` (match exact sur
   `(source, native_id)`).
2. Si pas trouvé, cherche un Type existant via signature `(issuer, year,
   denom, design_signature_normalisée)`.
3. Si proche mais pas certain → push dans une **Type Review Queue**
   admin-side (UI à proto'er).
4. Sinon → crée un Type neuf avec `eurio_id` généré.

### 3.2 Signature de design pour le dedup

```python
design_signature(name: str, theme_local: str | None) -> str:
    # 1. Extract parenthesized theme if present
    # 2. anyascii → lowercase → strip stopwords (the, of, a, in…)
    # 3. Sort tokens (anti-ordre)
    # 4. Hash to stable 8-char digest
```

Ainsi "30 Years of European Union Flag" et "EU Flag - 30 ans" produisent la
même signature → dedup automatique.

### 3.3 Cas frontière → Review Queue

- Signature partielle (≥ 0.6 overlap mais ≥ une candidate ambigüe) → review
- Conflit pays (Numista dit FR, MdP dit `eu`) → review
- Type existant a déjà un `numista_id` ≠ celui proposé → review

### 3.4 Pourquoi additif et pas pivot Numista

- Numista couvre 95% du 2€ mais 0% des collector MdP français (10€ films,
  séries Astérix, …). Sans politique additive, on ne pourra pas les ingérer.
- Permet à BCE / Wikipedia de servir de "fact-checker" (si BCE dit qu'une
  commémo n'existe pas, on flag le Type Numista correspondant).
- Coût : un service de dedup robuste + une UI de review. Bénéfice : neutralité.

---

## 4. Migration depuis V1

### 4.1 Étapes (ordre suggéré, chunks)

| Chunk | Livrable                                                              | Effort | API |
| ----- | --------------------------------------------------------------------- | ------ | --- |
| **0** | Ce doc + revue                                                        | fait   | 0   |
| **1** | Audit JSON exhaustif (684 entrées classifiées)                        | fait   | 0   |
| **2** | Migration Supabase (tables `coin_types`/`coin_variants`/`coin_mint_releases`/`coin_source_refs`) + script de repopulation depuis `coins` existant | ~2h   | 0   |
| **3** | Apply audit decisions : `MOVE_TO_VARIANT` × 15, `ADD_AS_VARIANT` × 19, `CREATE_NEW_TYPE` × 151, `REMATCH` × 58 (avec review queue pour les 9 UNCERTAIN) | ~3h   | 0   |
| **4** | Refetch Numista pour les 2025/2026 sortis depuis avril                | ~30min | ~50–100 calls |
| **5** | Refactor scrapers MdP/LMDLP/BCE → Type Candidates + dedup service     | à découper | 0 |
| **6** | UI review queue admin + apply automatique                             | ~3h   | 0   |

### 4.2 Contraintes invariantes pendant la migration

- Aucun `eurio_id` existant n'est cassé (sauf cas IN_REF_WRONG, mais alors on
  garde l'id et on re-mappe le numista_id sous-jacent).
- L'app Android continue de fonctionner avec le snapshot actuel pendant
  toute la migration (snapshot agrège Type + variant 'classic').
- Le scrape eBay continue à tourner sur les 508 `eurio_id` existants —
  juste élargi au fur et à mesure que les 151 nouveaux types sont créés.

### 4.3 Heuristiques pour la classification variant vs type

Côté nom Numista, ces patterns signalent un VARIANT (à mettre dans
`coin_variants` sous un Type parent) :

```
'coloured' | 'color(ed|ee)' | 'hologram' | 'hologramme' | 'holo'
'gilded' | 'pattern' | 'mule'
'- hologram version' | '- classic version'
'- blue flag' | '- multicoloured' | '- blue and yellow coloured'
```

Sinon, suffix unique sur un design distinct → nouveau Type.

Le matcher V2 (`referential/match_numista_v2.py`) appliquera :
1. Détection variant via regex (above)
2. Si VARIANT → cherche le sibling "classic" dans le même
   `(iso, year, commemo)` group → attache à son Type parent.
3. Si pas de sibling et catalog group multi-nids → cluster par signature
   de design (top-N similar names) → 1 cluster = 1 Type, autres nids =
   variants.
4. Si singleton → Type indépendant.

---

## 5. Décisions arrêtées

### 5.1 BU / BE / PROOF → `mint_release.issue_type`, pas `variant.finish`

`coloured`, `hologram`, `gilded`, `pattern`, `mule` modifient l'apparence
visuelle du design → vivent dans `coin_variants.finish`.

`CIRC`, `BU`, `BE`, `PROOF` ne changent pas le design, juste la qualité de
frappe / le conditionnement → vivent dans `coin_mint_releases.issue_type`.

Conséquence : pour FR 2024 "JO Paris", on a **1 Type** + **2 variants**
(classic, coloured) + **3 mint_releases** (CIRC, BU, BE) côté classic, soit
6 combinaisons possibles sans avoir à matérialiser le produit cartésien.

### 5.2 Joint-issues = N Types liés par `design_group_id`

Erasmus 2022 → **22 Types distincts** (1 par pays), pas 1 Type avec 22
variants. Chaque pays a un revers national légèrement différent, et le
prix marché diffère par pays.

Ces 22 Types pointent vers un même `design_groups.id =
"erasmus-2022-joint-issue"` (table existante depuis V1, schéma intact).

L'app peut donc :
- afficher "Erasmus 2022" comme groupe partagé sur le revers commun
- mais lister les 22 Types nationaux pour les revers nationaux

### 5.3 Variant ID = slug `{parent_eurio_id}/{finish}-{seq}` (seq auto si collision)

Exemple : `fr-2018-2eur-bleuet-de-france/coloured-1`,
`fr-2018-2eur-bleuet-de-france/coloured-2` (Bleuet a 2 variants colored
distincts dans Numista).

Le seq démarre à 1 et n'est ajouté que s'il y a collision. Le slug seul
(`/coloured`) reste valide pour les cas uniques. Avantage : lisibilité +
stabilité, opaque pour les rares cas multi-variants.

### 5.4 Migration de TOUTES les denoms en même temps (Chunk 2)

`coin_types` va recevoir les 2628 entries actuelles du référentiel
(toutes denoms confondues). `coin_variants` + `coin_mint_releases` ne
seront peuplés que pour les 2€ en cible immédiate, puis étendus aux
autres denoms en suivant.

Raison : refactor double (migrer 2€, puis re-migrer tout le reste) =
dette technique évitable. Le schéma `coin_types` est identique pour
toutes les denoms.

### 5.5 `coin_market_prices.target_kind` polymorphe

```sql
target_kind ENUM('type','variant','mint_release','specimen') NOT NULL,
target_id   TEXT NOT NULL  -- foreign key dynamique selon target_kind
```

- eBay scrape (mix de variants dans les annonces) → `target_kind='type'`
- LMDLP / MdP officielle (distingue classic vs BU) → `target_kind='variant'`
- NGC slab certifié → `target_kind='specimen'`

Pas de FK SQL formelle (target_id polymorphe), validation applicative.

---

## 6. Lien avec le reste de la stack

- **App Android** : le snapshot `catalog_snapshot.json` agrège Type +
  variant 'classic' (par défaut). Pas d'impact court terme. Nouvelle vue
  "Détails de la pièce" pourra afficher les variants quand on a la table.
- **eBay scrape** : continue d'itérer sur les 508 → 508+151+34 = ~693
  `eurio_id` après migration. Le scrape génère une query par Type. Variants
  sont vus comme des prix subordonnés.
- **Admin sources page** : ajouter une carte "Référentiel Health" qui
  affiche le compteur d'ORPHAN, WRONG, UNCERTAIN. Devient le pilote du
  matching qualité.
- **ML / ArcFace** : utilise déjà `design_group` comme label de
  classification — non impacté par V2 (le design_group survit, on l'attache
  juste sur `coin_types`).

---

## 7. Décisions actées 2026-05-15

| # | Décision | Source |
|---|---|---|
| D1 | Schéma 3 niveaux Type / Variant / MintRelease | §2.1, §2.3 |
| D2 | Multi-référentiel additif (Numista non pivot) | §3 |
| D3 | Grading MVP P2P : UNC / TTB / TB (Sheldon plus tard) | §2.3 (Specimen) |
| D4 | BU/BE/PROOF → `mint_release.issue_type` ; coloured/hologram/pattern/mule → `variant.finish` | §5.1 |
| D5 | Joint-issues = N Types nationaux liés par `design_groups.id` | §5.2 |
| D6 | Variant ID = slug `{parent_eurio_id}/{finish}[-{seq}]` | §5.3 |
| D7 | Migration de toutes les denoms simultanément (Chunk 2 migre les 2628 entries) | §5.4 |
| D8 | `coin_market_prices.target_kind` polymorphe (type/variant/release/specimen) | §5.5 |

## 8. Suite immédiate (Chunk 2)

Découpage proposé du Chunk 2 (migration Supabase) en sous-livrables auditables :

- **2a** — Inspection du schéma Supabase actuel (table `coins`, `cross_refs`,
  `design_groups`) pour aligner la migration avec l'existant.
- **2b** — Migration SQL `supabase/migrations/NNNN_referential_v2.sql` :
  création des 4 nouvelles tables (`coin_types`, `coin_variants`,
  `coin_mint_releases`, `coin_source_refs`) + index + contraintes.
- **2c** — Script Python `ml/referential/migrate_to_v2.py` qui repeuple
  `coin_types` depuis `coins`, déverse `cross_refs` JSON vers
  `coin_source_refs`, mode `--dry-run` obligatoire pour audit visuel.
- **2d** — Apply migration + script en mode réel (Raphaël valide chiffres
  avant) + verify counts.

Le **Chunk 3** (apply audit decisions = MOVE_TO_VARIANT × 15, etc.)
arrivera ensuite, séparément.
