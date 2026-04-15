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
| `year` | `int` \| `[min,max]` \| `"current"` | Année ou plage | `2007` ou `[2007,2012]` ou `"current"` |
| `denomination` | `float[]` | Valeurs faciales en euros | `[0.01,0.02,0.05,0.10,0.20,0.50,1.00,2.00]` |
| `series` | `string` | Identifiant de série/type | `"fr-2022"`, `"be-albert-ii"` |
| `ruler` | `string` | Identifiant dirigeant (redondant avec series pour monarchies) | `"jp2"`, `"benedict-xvi"` |
| `theme_code` | `string` | Thème officiel BCE | `"eu-rome-2007"`, `"eu-emu-2009"` |
| `distinct_by` | `"country"` | Dédoublonnage : une seule pièce par valeur distincte | voir §3.3 |
| `min_mintage` / `max_mintage` | `int` | Bornes sur le tirage | `max_mintage: 100000` (sets raretés) |

Toute combinaison AND implicite entre les clés. Pas de OR explicite dans le DSL v1 (si besoin, split en deux sets).

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

## 6. Enrichissements requis sur `coins`

Les colonnes nécessaires pour faire vivre le DSL. À ajouter en migration Supabase + Room :

```sql
ALTER TABLE coins ADD COLUMN issue_type text
  CHECK (issue_type IN ('circulation','commemo-national','commemo-common','starter-kit','bu-set','proof'));
ALTER TABLE coins ADD COLUMN series text;      -- 'fr-2022', 'be-albert-ii'
ALTER TABLE coins ADD COLUMN ruler text;       -- 'jp2','benedict-xvi' (nullable)
ALTER TABLE coins ADD COLUMN theme_code text;  -- 'eu-rome-2007' (nullable)
ALTER TABLE coins ADD COLUMN mintage bigint;   -- tirage Numista si déjà pas présent
ALTER TABLE coins ADD COLUMN series_rank int;

CREATE INDEX idx_coins_country_series ON coins(country, series);
CREATE INDEX idx_coins_theme_code ON coins(theme_code);
CREATE INDEX idx_coins_issue_type_year ON coins(issue_type, year);
```

Note : `coins` a déjà un champ `theme` (free text) et `is_commemorative` (bool). Ces champs restent pour compat. `theme_code` est une clé canonique distincte (« eu-rome-2007 »), `theme` reste descriptif (« 50e anniversaire du Traité de Rome »).

---

## 7. Inférence — algorithme officiel

Trois chemins complémentaires. Le chemin A est le runtime. B et C sont des outils de bootstrap / validation.

### 7.1 Chemin A — Metadata canonique (runtime client)

C'est l'évaluateur exécuté dans l'app à chaque changement de `user_collection` :

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

Coût : O(N coins) par set, ~3000 coins × 80 sets max = 240k évaluations, acceptable en mémoire Room indexé (< 50 ms sur téléphone moderne). Re-calcul déclenché uniquement à l'ajout/suppression d'une pièce.

### 7.2 Chemin B — Bootstrap depuis sources officielles

Pour **poser** les valeurs `theme_code`, `series`, `ruler` dans le référentiel. Exécuté côté `ml/`, pas côté app.

**Source BCE** (pour `theme_code` des communes) :
1. Scraper la page [BCE Joint commemorative issues](https://www.ecb.europa.eu/euro/coins/comm/html/index.en.html) → liste `[(theme_code, year, theme_name, countries[])]`
2. Pour chaque `(theme_code, country)`, retrouver l'`eurio_id` via `(country, year, denomination=2, issue_type='commemo-common')`
3. `UPDATE coins SET theme_code = ? WHERE eurio_id = ?`
4. `ASSERT COUNT(*) == expected` (13 pour Rome 2007, 16 pour EMU 2009, etc.). Abort sur mismatch.

**Source Numista + catalog catalogs** (pour `series`, `ruler`) :
Les ruptures de série (Belgique Albert II → Philippe, France 1999 → 2022, Vatican par pape, Monaco par prince, Espagne Juan Carlos → Felipe) sont **une vingtaine au total** sur toute la zone euro. Elles se taguent à la main dans un fichier `ml/data/series_overrides.json` et sont appliquées par le bootstrap.

**Source BCE pour les nouveautés** : cron mensuel (`ml/bootstrap_common_commemo.py`), idempotent, détecte nouvelles émissions communes et les ajoute au référentiel.

### 7.3 Chemin C — Validation par clustering visuel (failsafe, post Phase 2B)

Une émission commune a par définition une signature visuelle : N pays, même année, design identique sauf le champ national. Avec les embeddings ArcFace (disponibles après Phase 2B), on peut **détecter automatiquement** les communes non-taggées :

```python
for year in range(2002, current_year + 1):
    candidates = coins.filter(year=year, denomination=2, issue_type='commemo')
    clusters = arcface_cluster(candidates, similarity_threshold=0.92)
    for cluster in clusters:
        if len(cluster) >= 3 and distinct_countries(cluster) == len(cluster):
            if not all_have_same_theme_code(cluster):
                flag_review_queue(cluster, "potential common issue, check BCE")
```

Usage : contrôle de cohérence, pas source primaire. Utile si la BCE publie tardivement ou si Numista loupe un tag. Gated sur Phase 2B (dépend de l'existence d'embeddings entraînés).

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
| `circulation-fr` | structural | `country=fr, issue_type=circulation` | 8 × nb séries FR | country |
| `circulation-de` | structural | `country=de, issue_type=circulation` | 8 | country |
| … (21 pays) | | | | |
| `commemo-national-fr` | structural | `country=fr, issue_type=commemo-national` | dynamique | country |
| `common-rome-2007` | structural | `theme_code='eu-rome-2007'`, `distinct_by='country'` | 13 | theme |
| `common-emu-2009` | structural | `theme_code='eu-emu-2009'`, `distinct_by='country'` | 16 | theme |
| `common-euro-cash-2012` | structural | `theme_code='eu-cash-2012'`, `distinct_by='country'` | 17 | theme |
| `common-flag-2015` | structural | `theme_code='eu-flag-2015'`, `distinct_by='country'` | 19 | theme |
| `common-erasmus-2022` | structural | `theme_code='eu-erasmus-2022'`, `distinct_by='country'` | 19 | theme |
| `micro-states` | structural | `country IN (mc,sm,va,ad), issue_type=circulation, denomination=2.00` | 4 | hunt |
| `eurozone-tour` | structural | `issue_type=circulation, denomination=2.00, distinct_by=country` | 21 | hunt |
| `vatican-jp2` | structural | `country=va, series=va-jp2` | variable | theme |
| `vatican-benedict` | structural | `country=va, series=va-benedict-xvi` | variable | theme |
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

- **2026-04-15** — Création du doc, brainstorm avec Raphaël. Décisions clés :
  - Enrichissement metadata `coins` (issue_type, series, ruler, theme_code)
  - DSL structurel figé v1
  - Sets curés strictement limités à Grande Chasse v1
  - Paramétré v1 : millésime de naissance, prompt au moment d'ouvrir la carte du set
  - Schéma Supabase `sets` / `set_members` / `sets_audit`
  - Complétion utilisateur 100% locale v1
  - Chemins d'inférence A (runtime) + B (bootstrap BCE) + C (ArcFace failsafe, gated Phase 2B)
  - Validation par le cas Rome 2007 : théorie validée contre Wikipédia, 13 pays attendus
  - Un admin tooling séparé est planifié (cf. `docs/design/admin/README.md`)
