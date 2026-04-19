# Design groups — regroupement canonique des pièces partageant un design

> **Principe directeur** : un `design_group` regroupe les pièces qui partagent **le même design visuel**, indépendamment de l'année ou du pays qui l'émet. C'est la maille de classification visuelle d'Eurio — le label que ArcFace apprend, la clé qui déduplique la cartographie de collisions, l'entité que l'admin manipule pour décrire un design.
>
> La résolution fine vers une pièce précise (`eurio_id`) se fait ensuite en **deuxième passe** (OCR année et/ou OCR légende pays), pas dans ArcFace.
>
> Décidé le 2026-04-17.

---

## 1. Problème

Deux familles de pièces partagent un design à travers plusieurs `eurio_id` :

**Axe A — intra-pays, pluri-année.** Une pièce standard frappée à l'identique chaque année pendant N années (ex. Belgique 2€ Albert II 1<sup>re</sup> effigie 1999-2006, France 2€ Type 1999 de 2002 à 2021). Le design est identique, seule l'année (et parfois le mintmark) change. **Numista regroupe déjà ces re-frappes sous un unique `numista_id`**, et change d'ID dès qu'un élément du design évolue (effigie, carte, type).

**Axe B — cross-pays, même année.** Une commémorative commune émise par tous les pays de la zone la même année avec le même design, seule la légende nationale changeant (ex. Rome 2007, EMU 2009, Cash 2012, Flag 2015, Erasmus 2022). **Numista assigne N `numista_id` différents** pour les N variants pays, donc l'info de groupement cross-pays **n'existe nulle part dans le schéma actuel**.

Conséquences du manque de modélisation :

- **ML training**. Entraîner ArcFace à distinguer les 14 re-frappes annuelles de la 2€ Albert II 1<sup>re</sup> effigie comme 14 classes gâche la capacité du modèle sur un différentiateur (l'année) qu'un OCR lit trivialement. Idem pour les 13 variants pays de Rome 2007 : 99% des pixels identiques, classification pixel-par-pixel non-informative.
- **Carto collisions**. La pipeline `ml/confusion_map.py` exclut déjà les paires partageant un `numista_id` (re-frappes annuelles intra-pays, axe A couvert). Mais les paires cross-pays d'une joint-issue (FR-Rome-2007 vs IT-Rome-2007) ont 99% de similarité cosine → elles sont faussement flaggées **zone rouge**, polluent la priorisation d'enrichissement.
- **Admin**. Pas de vue naturelle "liste des variants d'un même design". Chaque coin est un îlot.
- **Granularité scan**. L'objectif est de scanner une pièce et savoir **design + pays + année** précis. Sans concept de design_group, on ne sait pas quelle est la deuxième passe (OCR année ? OCR pays ? les deux ?).

## 2. Décision

**On introduit une table pivot `design_groups`** et un FK nullable `coins.design_group_id`. Un coin appartient à un design_group ssi son design est partagé par ≥2 coins. Les vrais one-offs (Mozart AT 2006, D-Day FR 2014) restent `design_group_id = NULL`.

Cette maille unifie les deux axes (A et B) sous un même concept. Le schéma ne distingue pas A de B — c'est dérivable de la composition des membres (tous même pays → A, tous même année → B, mélange → cas hybride futur).

**Alternatives écartées** :

- *Garder `issue_type='commemo-common'` + dériver tout à la volée* — fonctionne pour les sets (déjà le cas depuis 2026-04-15 PM) mais ne couvre ni l'axe A ni le besoin de label ArcFace stable. Insuffisant.
- *Design_group pour chaque coin (y compris size-1)* — uniformité apparente mais ~2900 rows dont l'écrasante majorité n'encode aucune information nouvelle. Augmente la surface sans bénéfice.
- *Ressusciter `theme_code` sur `coins`* — ne couvre que l'axe B et n'est plus qu'un identifiant plat sans table pivot. `theme_code` avait initialement été pensé comme un code BCE canonique ; la BCE n'assigne en réalité rien de tel. C'était une hallucination. Droppé correctement le 2026-04-15.

---

## 3. Schéma

### 3.1 Table `design_groups`

```sql
CREATE TABLE design_groups (
  id                 text PRIMARY KEY,            -- 'be-2euro-albert-ii-ef1', 'eu-rome-2007'
  designation        text NOT NULL,               -- libellé admin ('BE 2€ Albert II (1re effigie)')
  designation_i18n   jsonb,                       -- {fr:"…", en:"…", de:"…", it:"…"}
  description        text,                        -- contexte éditorial (optionnel)
  shared_obverse_url text,                        -- image de référence (cover training + admin)
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_design_groups_updated_at ON design_groups(updated_at DESC);
```

### 3.2 FK sur `coins`

```sql
ALTER TABLE coins
  ADD COLUMN design_group_id text
    REFERENCES design_groups(id) ON DELETE SET NULL;

CREATE INDEX idx_coins_design_group ON coins(design_group_id)
  WHERE design_group_id IS NOT NULL;
```

### 3.3 Namespace des IDs

Les IDs sont lisibles, stables, manuellement assignables. Conventions :

| Axe | Template | Exemples |
|---|---|---|
| A — circulation intra-pays | `{country}-{denom}-{series-short}[-{variant}]` | `be-2euro-albert-ii-ef1`, `fr-2euro-1999-std`, `be-2euro-philippe` |
| A — commémo nationale répétée (rare) | `{country}-{theme-slug}-{year-or-range}` | *aucun cas connu v1* |
| B — commémo commune | `eu-{theme-slug}-{year}` | `eu-rome-2007`, `eu-emu-2009`, `eu-cash-2012`, `eu-flag-2015`, `eu-erasmus-2022` |

Règle : `{denom}` en euro-spelled (`2euro`, `1euro`, `50cent`, `20cent`…). `{series-short}` dérivé de `coin_series.id` (ex. `fr-1999` → `1999`) quand la série existe. `{variant}` pour différencier des effigies d'un même roi (`-ef1`, `-ef2`).

### 3.4 RLS

Même pattern que le reste (`sets`, `coin_series`, `coin_confusion_map`) : lecture publique, écriture admin.

```sql
ALTER TABLE design_groups ENABLE ROW LEVEL SECURITY;

CREATE POLICY design_groups_public_read ON design_groups
  FOR SELECT USING (true);

CREATE POLICY design_groups_admin_all ON design_groups
  FOR ALL
  USING (auth.jwt() ->> 'role' = 'admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'admin');
```

### 3.5 Trigger `updated_at`

Reprendre le pattern `coin_series_touch_updated_at` (migration 2026-04-15).

---

## 4. Règles métier

### 4.1 Condition d'appartenance

Un coin reçoit un `design_group_id` non-NULL **ssi** son design est partagé par ≥2 coins (soit par re-frappe annuelle axe A, soit par variant cross-pays axe B).

Conséquences :

- Une commémorative nationale unique (FR D-Day 2014, AT Mozart 2006) → `NULL`. Elle **est** sa propre classe ArcFace.
- Une commémorative nationale qui serait re-frappée l'année suivante avec même design → le 2<sup>e</sup> coin déclenche la création d'un design_group, les deux coins pointent dessus. Re-bootstrap idempotent (cf. §5).
- Un coin dont `cross_refs->numista_id` est `NULL` (pas de match Numista) → `NULL` par défaut, éligible à attribution manuelle via admin plus tard.

### 4.2 Cohérence des membres

Après bootstrap, tous les membres d'un `design_group` **doivent** partager **soit le pays, soit l'année** (ou les deux dans le cas dégénéré d'un groupe size-1 hypothétique). Assertion de validation, pas contrainte SQL (trop rigide pour les cas hybrides futurs).

### 4.3 Dérivation de l'axe de disambiguation (runtime)

L'axe est dérivé à la volée, pas stocké :

```sql
SELECT
  COUNT(DISTINCT country) AS n_countries,
  COUNT(DISTINCT year)    AS n_years
FROM coins
WHERE design_group_id = $1;
```

| `n_countries` | `n_years` | Axe | Disambiguation scan |
|---|---|---|---|
| 1 | ≥2 | A | OCR année |
| ≥2 | 1 | B | OCR légende pays |
| ≥2 | ≥2 | hybride (pas de cas connu) | OCR année + OCR légende pays |

Si un `variant_axis` stocké devient nécessaire pour perf ou validation, on l'ajoute en v2.

### 4.4 `issue_type = 'commemo-common'` devient dérivable

Aujourd'hui `issue_type` peut valoir `commemo-common`. Avec design_groups, cette valeur devient **redondante avec** : `design_group_id IS NOT NULL AND (SELECT COUNT(DISTINCT country) FROM coins WHERE design_group_id = X) ≥ 2`.

**Phasage de la dépréciation** :

1. **v1 (cette décision)** : la valeur `commemo-common` reste dans l'enum et continue d'être populée par le bootstrap. Le DSL sets (`sets-architecture.md` §7.3) continue d'utiliser `(year, issue_type='commemo-common', distinct_by=country)` sans changement.
2. **v1.5** : script de réconciliation qui vérifie l'équivalence `issue_type='commemo-common' ⇔ design_group cross-pays` sur tous les coins, en mode assertion.
3. **v2** : si l'équivalence tient à 100%, on drope la valeur `commemo-common` de l'enum `issue_type` et on migre les 5 sets concernés vers un critère basé sur design_group (cf. §6.5).

## 5. Bootstrap

### 5.1 Données seed

Un fichier `ml/data/design_groups_seed.json` en repo, versionné. Format wrappé pour signaler l'état de l'axe B (cf. §5.4) :

```json
{
  "axis_b": {
    "status": "deferred",
    "deferred_reason": "Joint issues are currently modeled as single eu-country rows in `coins`. Per-country expansion required before these design_groups can be created.",
    "entries": [
      {
        "id": "eu-rome-2007",
        "designation": "50e anniversaire du Traité de Rome",
        "designation_i18n": { "fr": "…", "en": "…", "de": "…", "it": "…" },
        "members": {
          "criteria": { "year": 2007, "issue_type": "commemo-common" }
        },
        "expected_count": 13
      },
      { "id": "eu-emu-2009",      "...": "..." },
      { "id": "eu-cash-2012",     "...": "..." },
      { "id": "eu-flag-2015",     "...": "..." },
      { "id": "eu-erasmus-2022",  "...": "..." }
    ]
  }
}
```

Quand `status == "deferred"`, le bootstrap loggue les entrées en informatif et ne crée aucun design_group. Quand `status == "active"`, comportement nominal (cf. §5.2).

Les joint-issues futures (post-2026) s'ajoutent par PR sur ce fichier. Une fois l'admin web pour design_groups en place (v1.5+), édition à chaud.

### 5.2 Script `ml/bootstrap_design_groups.py`

Dry-run + apply, idempotent :

**Étape 1 — Axe A (automatique, depuis Numista)**

```python
SELECT cross_refs->>'numista_id' AS nid, COUNT(*) AS n, array_agg(eurio_id)
FROM coins
WHERE cross_refs->>'numista_id' IS NOT NULL
GROUP BY nid
HAVING COUNT(*) >= 2;
```

Pour chaque ligne retournée :
- Générer un `id` slug-style en s'appuyant sur les attributs partagés des membres (`country`, `face_value`, `series_id`).
- INSERT dans `design_groups` si absent (idempotent sur `id`).
- UPDATE `coins.design_group_id` pour les N membres.

**Étape 2 — Axe B (depuis seed JSON)**

Pour chaque entrée du seed :
- INSERT dans `design_groups` si absent.
- Résoudre les membres par la `criteria` (typiquement `year + issue_type='commemo-common'`).
- UPDATE `coins.design_group_id` sur les membres.
- Assert que le count des membres matche l'`expected_count` attendu (13 pour Rome 2007, 16 pour EMU 2009, etc.).

**Étape 3 — Assertions de cohérence**

- Chaque design_group a ≥2 membres.
- Les membres d'un design_group partagent soit `country`, soit `year`.
- Aucun coin avec `issue_type='commemo-common'` ne reste avec `design_group_id=NULL`.
- Aucun coin avec `design_group_id` non-NULL dont le design_group est size-1 (ne devrait jamais arriver si la logique est correcte).

**Étape 4 — Output dry-run**

Liste des design_groups à créer, liste des coins à rattacher, déltas par rapport à l'état actuel. Applique seulement avec `--apply`.

### 5.3 Ré-exécution

Le script est idempotent. Nouveau coin ajouté dans `coins` avec un `numista_id` existant → re-run crée ou met à jour son rattachement. Nouveau thème commun (2027+) → ajout au seed JSON, re-run.

### 5.4 Pending : per-country expansion (axe B)

État au 2026-04-19 : les 5 joint-issues connues (Rome 2007, EMU 2009, Cash 2012, Flag 2015, Erasmus 2022) existent dans `coins` sous forme **d'une seule ligne** par thème, avec `country='eu'` et `national_variants` JSONB listant les pays émetteurs. Il n'y a **pas** de ligne par variant pays. Constat fait au dry-run du bootstrap design_groups le 2026-04-19 : la base contient 5 rows `commemo-common`, pas 84 (= 13+16+17+19+19).

Conséquence : l'axe B est marqué `status: "deferred"` dans le seed JSON. Le bootstrap loggue les 5 entrées pour visibilité mais ne crée aucun design_group. L'exclusion confusion_map n'a rien à exclure côté axe B — pas de paire intra-thème puisqu'il n'y a qu'une row par thème.

**Per-country expansion** = chantier séparé. Ce qu'il faudra faire :
1. Pour chaque joint-issue, à partir du `national_variants` array, générer N nouvelles rows dans `coins` (une par pays émetteur), chacune avec son propre `eurio_id`, son `numista_id` (les variants pays ont des IDs Numista distincts), ses images.
2. Marquer la row `eu-…` originale comme dépréciée ou la supprimer (à trancher).
3. Flipper `axis_b.status` à `"active"` dans le seed JSON.
4. Re-run `go-task ml:bootstrap-design-groups` → les design_groups axe B se créent normalement.
5. Re-run `go-task ml:confusion-map` → l'exclusion intra-design devient effective sur les variants pays.

Cette session n'est pas planifiée v1 — à ouvrir quand le besoin produit (granularité scan-time "tu as la version FR de Rome 2007") devient prioritaire.

---

## 6. Impact sur le reste du système

### 6.1 ML training (`ml/prepare_dataset.py`, `ml/train_arcface.py`)

Label ArcFace utilisé = `COALESCE(design_group_id, eurio_id)`.

Conséquences :

- Les ~300-500 design_groups axe A absorbent la majorité des ~3000 coins actuels. Cible réaliste post-scale : ~500-800 classes ArcFace au lieu de ~3000.
- Le pipeline d'augmentation (hors-scope ici, cf. `docs/research/training-pipeline.md`) n'est pas affecté dans sa logique, juste dans le label assigné aux samples.
- Les images de training pour un design_group peuvent venir de **n'importe lequel** de ses membres. Avantage pratique : plus de samples par classe.

### 6.2 Scan / inférence (app Android, `ml/api/`)

Pipeline cible en deux passes :

1. **Passe visuelle** (ArcFace) : produit un `design_group_id` (ou un `eurio_id` direct si NULL).
2. **Passe textuelle** (OCR) : selon l'axe dérivé du design_group (§4.3), OCR l'année et/ou la légende pays.
3. **Résolution** : `(design_group_id, year, country)` → `eurio_id` final.

Ce qu'il faut dans la base pour supporter ça : rien de plus que le schéma ci-dessus. Le lookup de résolution est un simple `WHERE` composite.

Hors-scope de ce doc : l'implémentation OCR (document dédié à venir).

### 6.3 Confusion map (`ml/confusion_map.py`)

Changement minimal. La ligne 342 qui exclut les paires partageant `numista_id` devient une exclusion sur `design_group_id`. Avantage : couvre à la fois l'axe A (déjà couvert) et l'axe B (non couvert aujourd'hui).

Pseudocode avant :
```python
if eurio_to_numista[eid_b] == nid_a:
    continue  # same design, skip
```

Après :
```python
if eurio_to_design_group[eid_b] == dg_a and dg_a is not None:
    continue  # same design, skip
```

Les coins sans design_group (NULL) sont traités comme aujourd'hui : chacun est sa propre entité, collisions computed normalement.

### 6.4 Admin (`admin/packages/web`)

Nouvelle vue "Designs" (route à définir, hors-scope ici, à spécifier dans `docs/design/admin/README.md`) qui liste les `design_groups`, expose les N membres, montre l'`shared_obverse_url`. **Édition non nécessaire en v1** — bootstrap-only. Édition à chaud vient en v1.5+ une fois les règles métier stabilisées.

### 6.5 DSL sets (`sets-architecture.md`)

**Aucun changement au DSL en v1.**

- Les sets joint-issues existants (`common-rome-2007`, `common-emu-2009`, etc.) continuent de matcher par `(year, issue_type='commemo-common', distinct_by=country)`. Équivalence préservée tant que `issue_type` reste populé.
- Un set "toutes les Albert II 2€ 1<sup>re</sup> effigie" serait nouveau (pas dans la liste v1). S'il devient souhaitable, ajout d'une clé `design_group_id` au DSL v1.1 — tranché à ce moment-là.
- L'exemple stale en `sets-architecture.md` §10 qui référence `theme_code` doit être corrigé indépendamment (cleanup de doc, pas impacté par cette décision).

### 6.6 App mobile (Room schema, Kotlin)

Miroir `design_groups` côté Room :

```
design_group
├── id                 TEXT PRIMARY KEY
├── designation        TEXT NOT NULL
├── description        TEXT
├── shared_obverse_url TEXT
└── updated_at         INTEGER NOT NULL   -- epoch ms, delta fetch

coin
├── … (existant)
└── design_group_id    TEXT (FK design_group.id, NULL autorisé)
```

Sync : même canal que `coins` / `sets`, delta fetch sur `updated_at`. Bootstrap APK : snapshot JSON packagé (`assets/catalog_snapshot.json`) enrichi des design_groups.

Aucun impact UX direct en v1 (le coffre reste organisé par coin, pas par design_group). Les vues "X/13 variants collectés" sont déjà couvertes par les sets existants via `distinct_by=country`. Si plus tard on veut afficher "tu as 4 ans sur les 14 d'Albert II 2€ 1<sup>re</sup> effigie", c'est une vue à concevoir (hors-scope).

---

## 7. Migration depuis l'état actuel

### 7.1 État actuel (2026-04-17)

- Migration `20260415_sets_and_coins_enrichment.sql` appliquée (ajoute `issue_type`, `series`, etc.).
- Migration `20260415_cleanup_and_coin_series.sql` appliquée (drop `theme_code`, `ruler`, `series_rank` ; crée `coin_series` ; renomme `series → series_id`).
- Migration `20260417_coin_confusion_map.sql` appliquée (table `coin_confusion_map`, exclusion par `numista_id`).
- ~2938 coins en base, ~5 coins ML-trained (`numista_id` populé sur les 5).

### 7.2 Étapes

1. **Migration SQL** `20260418_design_groups.sql` — additive, crée `design_groups` + FK sur `coins` + indexes + RLS + trigger.
2. **Seed file** `ml/data/design_groups_seed.json` — les 5 thèmes axe B listés §5.1.
3. **Script bootstrap** `ml/bootstrap_design_groups.py` — dry-run d'abord, valider les assertions, apply.
4. **Régénération types** `supabase/types/database.ts` via `mcp__supabase__generate_typescript_types` ou `go-task types:regen` (selon task existant).
5. **Update `ml/confusion_map.py`** ligne 342 — remplacement `numista_id` → `design_group_id`. Re-run pour regénérer `coin_confusion_map` avec la nouvelle logique (les zones vont changer : moins de red, plus de green/orange sur les ex-faux-positifs).
6. **Update doc sets-architecture.md** §10 — corriger l'exemple Rome-2007 stale (nettoyage indépendant de cette décision, opportuniste).
7. **Bascule ML training vers `COALESCE(design_group_id, eurio_id)` appliquée le 2026-04-20**. Le pipeline utilise maintenant ce label. Table additive `model_classes` (migration `20260420_model_classes.sql`) stocke l'embedding par `class_id` avec un discriminateur `class_kind`. `coin_embeddings` continue d'être populée via dual-write pour l'app Android — sa migration vers `model_classes` est un chantier distinct. Helper central : `ml/class_resolver.py`. Scripts refactorés : `prepare_dataset.py`, `compute_embeddings.py`, `seed_supabase.py`, `api/training_runner.py`.

### 7.3 Rollback

La table `design_groups` et le FK `coins.design_group_id` sont purement additifs. Rollback = `DROP TABLE design_groups CASCADE` (le FK coins tombe en même temps). Aucune donnée source perdue (l'info reste dans `cross_refs->numista_id` + seed JSON).

---

## 8. Questions ouvertes / v2

- **Per-country expansion des joint-issues** (cf. §5.4) — chantier majeur à ouvrir quand le besoin de granularité scan-time devient prioritaire. Débloque l'axe B effectif.
- **`variant_axis` stocké** si le runtime en a besoin pour perf ou validation pré-inférence. Dérivation à la volée OK pour <500 design_groups.
- **Admin UI pour édition à chaud** : créer, renommer, re-parenter des coins. Gated sur v1.5, une fois les règles métier stabilisées et les premiers cas limites observés.
- **Drop effectif de `issue_type='commemo-common'`** dans l'enum. Conditionné à l'équivalence 100% validée (cf. §4.4 phasage) — qui elle-même requiert l'expansion §5.4.
- **Clé DSL `design_group_id`** pour les sets. Ajoutée ssi un set utilisateur en a besoin (ex. "Tous les Albert II 2€ 1<sup>re</sup> effigie"). Pas de besoin v1.
- **Cas hybride** (design partagé pluri-pays ET pluri-année) : aucun exemple connu dans l'histoire de l'euro. Le schéma le supporte trivialement via la dérivation §4.3. Pipeline OCR double (année + pays) à l'exécution.
- **Coins rétro-frappés** (ex. Bulgarie rejoint 2026, frapperait-elle une 2012 Cash rétroactivement ?) : jamais vu, mais le schéma l'autorise (ajout d'un membre à un design_group existant = simple UPDATE).
- **Validation visuelle automatique des design_groups** par clustering ArcFace post-training : vérifier que les membres d'un même design_group forment bien un cluster compact, et flagger les design_groups incohérents. Gated sur Phase 2B (ArcFace v2).

---

## 9. Voir aussi

- [`docs/design/_shared/sets-architecture.md`](./sets-architecture.md) — sets DSL, référence `issue_type` et dépendance future sur design_groups
- [`docs/research/data-referential-architecture.md`](../../research/data-referential-architecture.md) — architecture globale du référentiel
- [`docs/research/ml-scalability-phases/README.md`](../../research/ml-scalability-phases/README.md) — plan scalability ML, phase 1 cartographie qui consomme la nouvelle logique confusion_map
- [`supabase/migrations/20260415_cleanup_and_coin_series.sql`](../../../supabase/migrations/20260415_cleanup_and_coin_series.sql) — drop `theme_code` du 2026-04-15 PM
- [`supabase/migrations/20260417_coin_confusion_map.sql`](../../../supabase/migrations/20260417_coin_confusion_map.sql) — table confusion à patcher §6.3

---

## Historique

- **2026-04-17** — Décision initiale. Scope identifié comme "designs partagés à travers coins" sur **deux axes** (intra-pays pluri-année + cross-pays même année), pas juste joint-issues. Numista reconnu comme source de vérité pour l'axe A (un `numista_id` par design, change dès que effigie/carte/type évolue — confirmé sur l'exemple Albert II : N#80 1<sup>re</sup> effigie 1999-2006, N#6293 2<sup>e</sup> carte/effigie 2008, N#6311 2<sup>e</sup> carte 1<sup>re</sup> effigie 2009-2013). Table pivot `design_groups` avec FK nullable depuis `coins`. Règle : `design_group_id` non-NULL ssi design partagé par ≥2 coins. Bootstrap en deux étapes (automatique axe A via GROUP BY numista_id, manuel axe B via seed JSON). DSL sets inchangé v1. `issue_type='commemo-common'` marqué dépréciable, drop effectif phasé v2.
- **2026-04-19** — Migration appliquée. Dry-run du bootstrap révèle que les 5 joint-issues existent dans `coins` sous forme d'**une seule ligne par thème** (`country='eu'`, `national_variants` JSONB), pas en per-country. Axe B marqué `status: "deferred"` dans le seed JSON — entrées documentées mais non appliquées. Per-country expansion ajoutée comme chantier futur §5.4. Axe A appliqué seul.
- **2026-04-20** — Bascule label ML training appliquée (avance sur le plan initial §7.2 step 7). Nouvelle table additive `model_classes` (migration `20260420_model_classes.sql`, RLS publique-lecture/admin-écriture, trigger `updated_at`). `prepare_dataset.py` résout chaque `numista_id` source vers `COALESCE(design_group_id, eurio_id)` via `class_resolver.py` et fusionne les augmented/ des N membres d'un design_group dans un dossier de classe unique. Le manifeste `eurio-poc/class_manifest.json` propage le `class_kind` aux scripts aval. `compute_embeddings.py` produit un embedding par class_id (+ fanout numista_id dans le JSON Android pour back-compat). `seed_supabase.py` fait le dual-write `model_classes` + `coin_embeddings`. Sur les 324 classes vues par Supabase : 320 `eurio_id` (standalones) + 4 `design_group_id` (les 4 groupes axe A bootstrappés). Mobile inchangée tant que l'app ne consomme pas `model_classes`.
