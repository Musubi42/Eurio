# Sets — architecture, DSL et inférence

> **Principe directeur** : un set d'achievement est un **objet produit de premier plan**, pas une constante de code. Sa définition canonique vit dans Supabase. Sa grande majorité est **structurelle** (dérivable du référentiel enrichi), pas curée à la main. Sa complétion utilisateur reste 100% locale en v1 (cohérent avec auth différée).
>
> Décidé le 2026-04-15 après brainstorm (cf. §4 « Historique » en bas).

---

## 1. Qu'est-ce qu'un set

Un set d'achievement a exactement **4 attributs fondamentaux** :

| Attribut | Description | Exemple |
|---|---|---|
| **Critère d'appartenance** | Quelles pièces en font partie ? | « country=fr AND category=circulation » |
| **Condition de complétion** | Quand est-il complété ? | « 100% des membres possédés » (seul cas v1) |
| **Récompense** | Quoi quand il est complété ? | badge, XP, déblocage visuel, cue célébration |
| **Présentation** | Nom i18n, description, icône, ordre, catégorie | « Circulation France », display_order=10, category='country' |

Un set n'est **pas** : une liste de pièces hardcodée dans le code Kotlin, une constante JavaScript dupliquée entre `state.js` et `profile.js`, ou un concept réservé aux développeurs. C'est une donnée éditoriale synchronisable.

---

## 2. Taxonomie

Quatre natures, par ordre d'importance décroissante :

### 2.1 Structurel (la grande majorité)

100% dérivable du référentiel `coins` par filtrage. Aucune liste à maintenir. Ajoute automatiquement les nouvelles pièces du référentiel (ex: Bulgarie 2026 apparaît dans « circulation-bg » dès que le bootstrap l'insère).

Exemples :
- « Circulation France » = `country=fr AND issue_type=circulation`
- « €2 commémos Allemagne » = `country=de AND issue_type=commemo-national`
- « 50e anniversaire Traité de Rome » = `theme_code='eu-rome-2007'` (cf. §5 pour l'inférence)
- « Vatican — Jean-Paul II » = `country=va AND series='va-jp2'`
- « Les 4 micro-États » = `country IN ('mc','sm','va','ad') AND issue_type=circulation AND denomination=2`
- « Tour de la zone euro » = une pièce par `country` distinct (cf. `distinct_by` §3.3)

### 2.2 Curé

Liste humaine explicite d'`eurio_id`. À réserver aux sets **non-exprimables** par le DSL structurel, ou qui nécessitent un jugement éditorial subjectif.

Usage v1 strictement limité à :
- **Grande Chasse** — ~15-20 pièces rares et emblématiques (Monaco 2007 Grace Kelly 20k ex., Saint-Marin basses tirages, erreurs de frappe reconnues). Curation éditoriale.
- Sets thématiques éditoriaux ponctuels si nécessaire (« JO Paris 2024 » par exemple, si le theme_code ne suffit pas).

### 2.3 Paramétré (user-bound)

Set structurel avec un paramètre fourni par l'utilisateur. Seul cas v1 :
- **Millésime de naissance** — `year = user.birthYear`. L'année est demandée **au moment d'ouvrir la carte du set**, pas à l'onboarding (friction minimale, cohérent avec le no-account). L'utilisateur peut modifier/effacer son année à tout moment (stocké localement dans Room).

### 2.4 Dynamique

Sets time-bound, auto-générés à partir de conditions temporelles (« Nouveautés 2026 »). **Reporté v2**, pas dans le scope du bootstrap initial.

---

## 3. DSL structurel — figé v1

Les critères structurels sont exprimés en JSONB (`sets.criteria`). Le DSL est **figé** : ajouter une clé de critère nécessite une mise à jour app coordonnée (client embarque l'évaluateur). C'est un trade-off assumé — le DSL doit couvrir 95% des sets sans nouvelle clé.

### 3.1 Clés supportées

| Clé | Type | Description | Exemple |
|---|---|---|---|
| `country` | `iso2` \| `iso2[]` | Un ou plusieurs pays ISO2 | `"fr"` ou `["mc","sm","va","ad"]` |
| `issue_type` | enum \| enum[] | Type d'émission | `"circulation"`, `"commemo-national"`, `"commemo-common"`, `"starter-kit"`, `"bu-set"`, `"proof"` |
| `year` | `int` \| `"current"` | Année unique ou année courante | `2007` ou `"current"` |
| `denomination` | `float[]` | Valeurs faciales en euros | `[0.01,0.02,0.05,0.10,0.20,0.50,1.00,2.00]` |
| `series_id` | `string` | FK vers `coin_series(id)` — sélectionne toutes les pièces d'une série (circulation uniquement) | `"be-philippe"`, `"va-jp2"`, `"fr-2022"` |
| `is_withdrawn` | `bool` | Filtre sur le statut de retrait | `true` (pièces retirées) / `false` (en circulation) |
| `distinct_by` | `"country"` | Dédoublonnage : une seule pièce par valeur distincte | voir §3.3 |
| `min_mintage` / `max_mintage` | `int` | Bornes sur le tirage | `max_mintage: 100000` (sets raretés, gated sur la colonne `mintage`) |

Toute combinaison AND implicite entre les clés. Pas de OR explicite dans le DSL v1 (si besoin, split en deux sets).

**Clés volontairement absentes** et pourquoi :
- `year: [min, max]` (range) — remplacé par `series_id` qui porte la sémantique des plages temporelles au niveau métier (dates de frappe). Si un besoin légitime de plage d'années non-série apparaît (ex: « décennie 2010-2019 »), on l'ajoutera explicitement au DSL v2.
- `theme_code` — redondant avec `(year, issue_type='commemo-common')` puisqu'il n'y a jamais eu qu'une seule émission commune par an dans l'histoire de l'euro. La sémantique thématique vit dans `sets.name_i18n` et l'id du set, pas dans une colonne de `coins`. Si deux communes sortent la même année un jour, fallback curé pour ce cas.
- `ruler` — redondant avec `coin_series.designation`.
- `series_rank` — pas de cas d'usage v1.

### 3.2 Structure `criteria` JSONB

```json
{
  "country": "fr",
  "issue_type": "commemo-national",
  "year": [2008, 2026]
}
```

```json
{
  "country": ["mc", "sm", "va", "ad"],
  "issue_type": "circulation",
  "denomination": [2.00]
}
```

### 3.3 `distinct_by` — « un exemplaire par X »

Pour les sets du type « une pièce par pays de la zone » ou « un exemplaire par année ». Le moteur d'évaluation fait un dédoublonnage : si l'utilisateur possède 3 pièces françaises, une seule compte pour le set « Tour de la zone euro ».

```json
{
  "issue_type": "circulation",
  "denomination": [2.00],
  "distinct_by": "country"
}
```

→ 21 slots (un par pays eurozone), complété à `owned_countries / 21`.

---

## 4. Schéma Supabase

### 4.1 Table `sets`

```sql
CREATE TABLE sets (
  id              text PRIMARY KEY,            -- 'circulation-fr', 'common-rome-2007'
  kind            text NOT NULL CHECK (kind IN ('structural','curated','parametric')),
  name_i18n       jsonb NOT NULL,              -- {fr:"…", en:"…", de:"…", it:"…"}
  description_i18n jsonb,
  criteria        jsonb,                       -- structural/parametric uniquement
  param_key       text,                        -- parametric uniquement ('birth_year')
  reward          jsonb,                       -- {badge:'gold', xp:500, level_bump:false}
  display_order   int NOT NULL DEFAULT 1000,
  category        text NOT NULL,               -- 'country'|'theme'|'tier'|'personal'|'hunt'
  icon            text,                        -- ref à asset icon
  expected_count  int,                         -- validation bootstrap (optionnel)
  active          bool NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_sets_active_order ON sets(active, display_order);
CREATE INDEX idx_sets_category ON sets(category);
```

### 4.2 Table `set_members` (sets curés uniquement)

```sql
CREATE TABLE set_members (
  set_id     text NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
  eurio_id   text NOT NULL REFERENCES coins(eurio_id),
  position   int,                              -- ordre d'affichage dans le set (nullable)
  PRIMARY KEY (set_id, eurio_id)
);

CREATE INDEX idx_set_members_coin ON set_members(eurio_id);
```

Contrainte logique : `set_members.set_id` doit référencer un set `kind='curated'`. À valider côté admin (ou via trigger).

### 4.3 Table `sets_audit` (append-only)

```sql
CREATE TABLE sets_audit (
  id         bigserial PRIMARY KEY,
  set_id     text NOT NULL,
  action     text NOT NULL CHECK (action IN ('create','update','delete','activate','deactivate','publish')),
  before     jsonb,
  after      jsonb,
  actor      text NOT NULL,                    -- email admin ou 'bootstrap-script'
  at         timestamptz NOT NULL DEFAULT now()
);
```

Alimentée par l'admin (cf. [`docs/design/admin/README.md`](../admin/README.md)) et par le bootstrap script Python.

### 4.4 RLS

```sql
ALTER TABLE sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE set_members ENABLE ROW LEVEL SECURITY;

-- lecture publique (app cliente)
CREATE POLICY sets_read ON sets FOR SELECT USING (active = true);
CREATE POLICY set_members_read ON set_members FOR SELECT USING (true);

-- écriture réservée au rôle admin
CREATE POLICY sets_admin_write ON sets FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');
CREATE POLICY set_members_admin_write ON set_members FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');
```

---

## 5. Miroir Room (client Android)

Tables plates, miroir simplifié. JSONB Supabase → colonnes typées ou TEXT/JSON selon complexité.

```
sets
├── id                TEXT PRIMARY KEY
├── kind              TEXT NOT NULL           -- 'structural'|'curated'|'parametric'
├── name              TEXT NOT NULL           -- résolu selon locale courante
├── description       TEXT
├── criteria_json     TEXT                    -- JSON brut pour l'évaluateur
├── param_key         TEXT
├── reward_json       TEXT
├── display_order     INTEGER NOT NULL
├── category          TEXT NOT NULL
├── icon              TEXT
├── expected_count    INTEGER
├── active            INTEGER NOT NULL        -- 0/1
├── updated_at        INTEGER NOT NULL        -- epoch ms, delta fetch
└── INDEX(active, display_order), INDEX(category)

set_members
├── set_id            TEXT NOT NULL (FK)
├── eurio_id          TEXT NOT NULL (FK coins)
├── position          INTEGER
└── PRIMARY KEY (set_id, eurio_id)

user_set_progress                              -- LOCAL UNIQUEMENT v1, jamais synced
├── set_id            TEXT PRIMARY KEY (FK)
├── completion_ratio  REAL NOT NULL            -- 0.0..1.0 (calculé, cache)
├── owned_count       INTEGER NOT NULL
├── target_count      INTEGER NOT NULL
├── completed_at      INTEGER                  -- epoch ms, null tant que non complet
├── celebrated_at     INTEGER                  -- epoch ms, null tant que l'unlock celebration n'a pas joué
├── param_value       TEXT                     -- pour parametric sets (ex: '1990' birth_year)
└── updated_at        INTEGER NOT NULL
```

---

## 6. Enrichissements sur `coins` et nouvelle table `coin_series`

Le DSL a besoin de metadata qui n'existait pas dans le schéma initial de `coins`. Deux migrations ont été appliquées le 2026-04-15 :

### 6.1 `coins` — colonnes ajoutées

| Colonne | Type | Rôle |
|---|---|---|
| `issue_type` | text check (enum) | Type d'émission. Populé par l'enrichment script depuis `is_commemorative` + `national_variants` : `circulation` / `commemo-national` / `commemo-common`. `starter-kit` / `bu-set` / `proof` réservés futur. |
| `series_id` | text FK → `coin_series(id)` | Série de circulation à laquelle appartient la pièce. NULL pour toutes les commémoratives (commemos = standalone, pas de série). |
| `mintage` | bigint nullable | Tirage total. Reporté v2, laissé NULL v1. |
| `is_withdrawn` | bool default false | La pièce a-t-elle été officiellement retirée de la circulation ? Aucun cas historique connu pour l'euro, mais modélisé. |
| `withdrawn_at` | date nullable | Date de la décision de retrait. |
| `withdrawal_reason` | text nullable | Raison : `design_issue`, `political`, `defect`, `other`. |

Champs legacy conservés pour compat : `is_commemorative` (bool), `theme` (text libre), `national_variants` (jsonb).

### 6.2 `coin_series` — nouvelle table first-class

Une **série** est un type de design circulant pour un pays donné, avec un cycle de vie (début-fin de frappe) et une chaîne de succession.

```sql
CREATE TABLE coin_series (
  id                       text PRIMARY KEY,           -- 'be-philippe', 'fr-1999', 'va-jp2'
  country                  text NOT NULL,
  designation              text NOT NULL,              -- 'Philippe', 'Type 1999', 'Jean-Paul II'
  designation_i18n         jsonb,                      -- {fr:"…", en:"…"}
  description              text,
  minting_started_at       date NOT NULL,              -- date de première frappe officielle
  minting_ended_at         date,                       -- NULL = encore en production
  minting_end_reason       text,                       -- 'ruler_change','redesign','policy','sede_vacante_end','other'
  supersedes_series_id     text REFERENCES coin_series(id),
  superseded_by_series_id  text REFERENCES coin_series(id),
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now()
);
```

**Distinction sémantique critique** :
- `coin_series.minting_ended_at` = la Monnaie nationale a **arrêté de frapper** cette série. Les pièces existantes **restent en circulation** et conservent leur cours légal. C'est le cas standard à chaque rupture de série (Belgique 2013, France 2021, Vatican à chaque pape, etc.).
- `coins.is_withdrawn` = la pièce a été **retirée de la circulation** par décision officielle. Les banques la refusent, son cours légal est supprimé. **Aucun cas historique connu pour l'euro** (la BCE et les BC nationales n'ont jamais procédé à un recall post-émission depuis 2002), mais le data model le supporte parce que quand ça arrive, la valeur de collection explose — signal premier pour un numismate.

**Source de vérité des séries** : aucune base machine-readable unique. Compilé à la main dans `ml/data/coin_series_seed.json` (~32 entrées au total pour toute la zone euro historique) en croisant BCE + Numista + communiqués des monnaies nationales. Le taggage est one-shot, maintenu éditorialement via l'admin quand un nouveau pays entre ou qu'une rupture se produit.

**Matching coins → series** : pour chaque coin de circulation, trouver la série telle que `country` matche et `coin.year` ∈ `[minting_started_at.year, coalesce(minting_ended_at.year, ∞)]`. Toutes les frontières sont des années civiles pleines (aucune année de transition ambiguë dans l'histoire de l'euro). Les commémoratives ont `series_id = NULL`.

---

## 7. Inférence — runtime et bootstrap

### 7.1 Runtime client — évaluateur DSL

Exécuté dans l'app à chaque changement de `user_collection` :

```kotlin
fun evaluateSet(set: Set, ownedCoins: List<Coin>): SetProgress {
    val members = when (set.kind) {
        "curated"    -> loadSetMembers(set.id)
        "structural" -> coinsDao.filterByCriteria(set.criteria)
        "parametric" -> {
            val paramValue = userSetProgressDao.paramValue(set.id) ?: return SetProgress.NotStarted
            coinsDao.filterByCriteria(set.criteria.withParam(set.paramKey, paramValue))
        }
    }
    val targetCount = members.applyDistinctBy(set.criteria.distinctBy).size
    val ownedCount = ownedCoins.intersect(members).applyDistinctBy(...).size
    return SetProgress(ownedCount, targetCount)
}
```

Coût : O(N coins) par set, ~3000 coins × 80 sets = ~240k évaluations, < 50 ms sur téléphone moderne avec indexes Room. Re-calcul déclenché uniquement à l'ajout/suppression d'une pièce.

### 7.2 Bootstrap `coin_series` et enrichissement

Script `ml/enrich_coins_metadata.py` (dry-run + apply) :

1. **Seed `coin_series`** depuis `ml/data/coin_series_seed.json` (~32 entrées compilées à la main depuis BCE + Numista + communiqués monnaies nationales).
2. **Populate `issue_type`** sur les 2938 coins (dérivation auto) :
   ```
   is_commemorative=false              → 'circulation'
   is_commemorative=true, nat_var NULL → 'commemo-national'
   is_commemorative=true, nat_var !=   → 'commemo-common'
   ```
3. **Populate `coins.series_id`** pour les coins de circulation uniquement : matching `(country, year)` contre `[minting_started_at.year, minting_ended_at.year || ∞]`. Commémoratives laissées `NULL`.
4. **Assertions** :
   - `issue_type NOT NULL` sur 100% des coins
   - `series_id NOT NULL` sur 100% des coins où `issue_type='circulation'`
   - `series_id IS NULL` sur 100% des coins commémoratifs
   - Compte par série cohérent avec les bornes temporelles

### 7.3 Émissions communes — sans theme_code

Les commémoratives communes (Rome 2007, EMU 2009, Cash 2012, Flag 2015, Erasmus 2022, futures) sont **matchées par `(year, issue_type='commemo-common')`** dans le DSL, pas par un `theme_code` dédié. Possible parce qu'il n'y a jamais eu qu'**une seule commune par année** dans l'histoire de l'euro (2002-2026).

Exemple Rome 2007 :
```json
{
  "id": "common-rome-2007",
  "kind": "structural",
  "criteria": {
    "year": 2007,
    "issue_type": "commemo-common",
    "distinct_by": "country"
  },
  "expected_count": 13
}
```

Le libellé « 50e anniversaire du Traité de Rome » vit dans `sets.name_i18n` et l'`id` du set (`common-rome-2007` comme convention éditoriale lisible), pas dans une colonne de `coins`. La table `coins` reste **neutre descriptive**, la sémantique thématique vit dans les sets.

**Failsafe pour un scénario 2-communes-la-même-année** : détectable au seed (`expected_count != actual`) → fallback curé pour ce cas, pas de casse du système.

### 7.4 Validation par clustering visuel (failsafe futur, post Phase 2B)

Une émission commune a par définition une signature visuelle : N pays, même année, design identique sauf le champ national. Avec les embeddings ArcFace disponibles post-Phase 2B, on peut détecter automatiquement des communes non-taggées ou des erreurs de taggage :

```python
for year in range(2002, current_year + 1):
    candidates = coins.filter(year=year, denomination=2, issue_type='commemo')
    clusters = arcface_cluster(candidates, similarity_threshold=0.92)
    for cluster in clusters:
        if len(cluster) >= 3 and distinct_countries(cluster) == len(cluster):
            if not all_share_common_issue_type(cluster):
                flag_review_queue(cluster, "potential common issue miscategorized")
```

Contrôle de cohérence. Gated sur Phase 2B.

---

## 8. Sync

Trois canaux distincts, comme le reste du référentiel :

| Canal | Contenu | Déclencheur | État |
|---|---|---|---|
| **Bootstrap APK** | `sets` + `set_members` seed JSON dans assets | First install | 100% offline, zéro réseau |
| **Delta fetch Supabase** | `sets` + `set_members` où `updated_at > last_sync_at` | Cron background OU pull manuel | Nouveau set → toast « Nouveau set disponible » sur profil |
| **User progress** | `user_set_progress` (complétion locale) | Calculé après chaque `addCoin` / `removeCoin` | **100% local Room v1**, jamais synced. Sync cloud gated sur lien de compte (v2) |

Ordre de sync : `coins` **avant** `sets` (les sets référencent des coins, un set ne peut exister sans ses coins). Le bootstrap script enforce l'ordre.

---

## 9. Exemples de sets v1

Liste cible pour le premier référentiel (approximative, à affiner au bootstrap) :

| id | kind | criteria / membres | expected_count | category |
|---|---|---|---|---|
| `circulation-fr-1999` | structural | `series_id=fr-1999` | 8 × nb millésimes FR 1999-2021 | country |
| `circulation-fr-2022` | structural | `series_id=fr-2022` | 8 × nb millésimes FR 2022+ | country |
| `circulation-de` | structural | `series_id=de-circ` | 8 × nb millésimes DE | country |
| … (une par série, 32 au total) | | | | |
| `commemo-national-fr` | structural | `country=fr, issue_type=commemo-national` | dynamique | country |
| `common-rome-2007` | structural | `year=2007, issue_type=commemo-common, distinct_by=country` | 13 | theme |
| `common-emu-2009` | structural | `year=2009, issue_type=commemo-common, distinct_by=country` | 16 | theme |
| `common-cash-2012` | structural | `year=2012, issue_type=commemo-common, distinct_by=country` | 17 | theme |
| `common-flag-2015` | structural | `year=2015, issue_type=commemo-common, distinct_by=country` | 19 | theme |
| `common-erasmus-2022` | structural | `year=2022, issue_type=commemo-common, distinct_by=country` | 19 | theme |
| `micro-states` | structural | `country IN (mc,sm,va,ad), issue_type=circulation, denomination=[2.00]` | 4 | hunt |
| `eurozone-tour` | structural | `issue_type=circulation, denomination=[2.00], distinct_by=country` | 21 | hunt |
| `vatican-jp2` | structural | `series_id=va-jp2` | variable | theme |
| `vatican-benedict` | structural | `series_id=va-benedict-xvi` | variable | theme |
| `withdrawn-collector` | structural | `is_withdrawn=true` | 0 à ce jour (modélisation) | hunt |
| `birth-year` | parametric | `year=<param>`, `param_key='birth_year'` | variable | personal |
| `grande-chasse` | curated | 3-4 pièces symboliques v1 (à compléter plus tard) | ~4 | hunt |
| `coffre-dor` | curated | tier éditorial (à définir) | TBD | tier |

Total estimé v1 : ~50 sets structurels auto-générés + ~2-3 sets curés symboliques. Cible v2 (après admin) : ~80-100 sets.

---

## 10. Validation du cas de référence — Rome 2007

Le set « 50e anniversaire du Traité de Rome » est **le** cas de test critique pour valider l'approche. Challenge fait le 2026-04-15 contre la page Wikipédia correspondante : théorie validée, 13 pays attendus (BE, DE, IE, ES, FR, IT, LU, NL, AT, PT, SI, FI, GR), récupérables via `theme_code='eu-rome-2007'` + `distinct_by='country'`.

Définition canonique :
```json
{
  "id": "common-rome-2007",
  "kind": "structural",
  "name_i18n": {
    "fr": "50e anniversaire du Traité de Rome",
    "en": "50th anniversary of the Treaty of Rome",
    "de": "50. Jahrestag der Römischen Verträge",
    "it": "50° anniversario dei Trattati di Roma"
  },
  "criteria": {
    "theme_code": "eu-rome-2007",
    "distinct_by": "country"
  },
  "expected_count": 13,
  "category": "theme",
  "display_order": 100,
  "reward": { "badge": "gold", "xp": 500 }
}
```

Condition d'existence : le bootstrap BCE doit avoir posé `theme_code='eu-rome-2007'` sur exactement 13 entrées `coins` correspondant aux 13 pays. Assert dans le script, abort sur mismatch.

---

## 11. Questions ouvertes

- **Condition de complétion ≠ 100%** : v1 ne supporte que « 100% des membres possédés ». Faut-il des tiers bronze/argent/or par pourcentage (33% / 66% / 100%) ? Discussion à avoir si l'engagement user le demande. Impact faible sur le schéma (ajouter `tiers jsonb` à `sets`).
- **Sets imbriqués / méta-sets** : « Coffre d'or = 10 sets d'or complétés ». Pas supporté v1, nécessiterait une récursion d'évaluation. À rediscuter v2.
- **Versionnement des critères** : si un `theme_code` change de valeur (re-catégorisation), les user_set_progress sont invalidés. Pour l'instant, on recalcule intégralement à chaque sync. Suffisant v1.
- **Sets privés / partagés par l'utilisateur** : wishlist, liste d'échange. Hors scope sets d'achievement, à traiter comme feature distincte v2.

---

## 12. Voir aussi

- [`docs/design/admin/README.md`](../admin/README.md) — outil admin futur pour gérer ces sets
- [`docs/design/_shared/data-contracts.md`](./data-contracts.md) — contrats data Room ↔ Supabase
- [`docs/design/_shared/offline-first.md`](./offline-first.md) — stratégie offline
- [`docs/research/data-referential-architecture.md`](../../research/data-referential-architecture.md) — architecture référentiel `coins`
- [`docs/design/profile/achievements-engine.md`](../profile/achievements-engine.md) — moteur d'achievements côté profil
- [`docs/DECISIONS.md`](../../DECISIONS.md) — index des décisions

---

## Historique

- **2026-04-15 (matin)** — Création du doc, brainstorm initial. Premier plan : enrichir `coins` avec `issue_type`, `series`, `ruler`, `theme_code`, `mintage`, `series_rank`. DSL avec `year: [min,max]` et `theme_code` comme clés.
- **2026-04-15 (après-midi)** — Révision après pushback produit :
  - **`theme_code` supprimé** : redondant avec `(year, issue_type='commemo-common')` vu qu'il n'y a jamais eu qu'une commune par an. La sémantique thématique vit dans `sets.name_i18n`, pas dans `coins`. Table `coins` reste neutre descriptive.
  - **`year: [min, max]` supprimé du DSL** : identifié comme dette métier. Les plages temporelles passent par `coin_series` qui modélise proprement le cycle de vie des séries (dates de frappe + chaîne supersedes).
  - **Nouvelle table `coin_series`** first-class avec `minting_started_at`, `minting_ended_at`, `minting_end_reason`, `supersedes`/`superseded_by` chaînage. 32 entrées compilées dans `ml/data/coin_series_seed.json`.
  - **`coins.series` → `coins.series_id`** FK vers `coin_series`. Colonnes `ruler` et `series_rank` supprimées (redondantes / non utilisées).
  - **Distinction frappe arrêtée vs retrait** : `coin_series.minting_ended_at` = Monnaie stoppe la frappe, pièces restent en circulation (cas standard à chaque rupture). `coins.is_withdrawn` / `withdrawn_at` / `withdrawal_reason` = décision de retrait officiel, aucun cas historique connu pour l'euro mais modélisé pour signaler l'explosion de valeur de collection quand ça arrive.
  - Paramétré v1 confirmé : millésime de naissance, prompt au moment d'ouvrir la carte du set.
  - Schéma Supabase `sets` / `set_members` / `sets_audit` inchangé.
  - Admin tooling séparé planifié (cf. `docs/design/admin/README.md`).
