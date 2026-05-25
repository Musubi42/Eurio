# ROADMAP-DB — Reset référentiel + validation vertical-slice

> **Statut** : Document opérationnel canonique du chantier `coin-richness`.
> Consolide les décisions prises en sessions 2026-05-25.
>
> **Lecteur cible** : nous-mêmes en session, et toute future session Claude
> reprenant ce chantier. Tous les chantiers (`chantier-A`, `chantier-C`,
> `chantier-D`, `kickoff`) sont des **deep-dives** ; ce fichier est le
> chef d'orchestre.

---

## 1. TL;DR

On reconstruit le référentiel Eurio depuis zéro, proprement :

1. **Schéma cible installé** (V2 SQLite : variants, mint_releases, observations multi-source, source_registry, credits, edge_variants)
2. **Backup vérifié** (pas d'action destructive sans check de restauration)
3. **Wipe** du référentiel actuel (coins + tables filles + observations + market_quotes — 13k+ lignes)
4. **Refetch Numista** ciblé sur une **cohorte de 19 coins** = `mix-zone-17` + 3 ajouts (DE Bremen 5-ateliers, FR Bleuet coloured, DE Treaty of Rome joint-issue)
5. **Branchement** des autres sources sur la cohorte : BCE, eBay, MdP/LMDLP
6. **Validation visuelle** par Raphaël page coin par page
7. **GO/NO-GO** : si OK, scale aux 21 pays + AD/MC/SM/VA + joint-issues. Si KO, on discute, **pas de rollback auto**.

**Cette roadmap couvre la prep (P.*) + la validation (V.*) jusqu'au GO/NO-GO.**
Le scale (F.*) est out-of-scope de cette session.

---

## 2. Doctrine actée

### 2.1 — `eurio.db` = LA source de vérité

(Cf. mémoire [[feedback-sqlite-only-doctrine]].)

- Admin Vue ne lit **plus** Supabase. Lectures via API Python ml/ → `eurio.db`.
- Toute nouvelle migration référentielle → `ml/state/schema.sql`. Plus jamais `supabase/migrations/`.
- Supabase reste cible app Android : sync **sortant explicite** SQLite → Supabase, déclenché manuellement quand besoin.

### 2.2 — Provenance first-class, pas de fallback silencieux

- Chaque fact en DB porte sa `source` (FK vers `source_registry`).
- Si deux sources divergent (BCE 29/01/2010 vs Numista 01/02/2010), on garde les **deux lignes**, l'admin tranche éditorialement.
- Pas d'enum `confidence` per-fact — la confiance se déduit de la source (registry.kind) + du nombre de sources concordantes (lecture).

### 2.3 — Vertical slice avant scale

On ne refait pas 524 coins d'un coup. **18 coins → validation visuelle → scale**.

---

## 3. Schéma cible — tables à avoir en `eurio.db`

### 3.1 — Nouvelles tables (à créer)

| Table | Rôle | Provenance |
|---|---|---|
| `source_registry` | Catalogue des sources de données (8 seed initiales, extensible) | nouveau |
| `mints` | **Ateliers monétaires normalisés** (A=Berlin, D=Munich, F=Stuttgart, G=Karlsruhe, J=Hamburg, plus FR Pessac, IT Roma, ES Madrid, AT Wien, etc.) avec id + country + city + name + founded_year. FK depuis `coin_mint_releases.mint_id` | nouveau (décidé 2026-05-25) |
| `coin_variants` | Niveau VARIANT : finition (classic / coloured / hologram / gilded / pattern / mule / misstrike / other) | rapatrié depuis Supabase V2 |
| `coin_mint_releases` | Niveau MINT_RELEASE : (parent_type, year, mark, issue_type) — l'unité du tableau A/D/F/G/J × BE/BU/CIRC de 2euros.org | rapatrié depuis Supabase V2 |
| `coin_source_refs` | Multi-source refs vers Numista / MdP / BCE / LMDLP (polymorphe : type/variant/release) | rapatrié depuis Supabase V2 |
| `mint_release_prices` | Prix par grade × source × mint_release (Numista 7 grades, MdP, etc.) | rapatrié depuis Supabase V2 |
| `mint_release_observations` | Facts attribués à des sources (mintage, released_on, notes) avec `source` obligatoire | nouveau (pattern provenance) |
| `coin_credits` | Graveur **avers** + graveur **revers** + (potentiellement sculpteur) avec `source` en PK (multi-source autorisé). Le rôle distingue avers/revers, pas designer/engraver (Numista n'a qu'un seul rôle `graveur` par face). | nouveau (Chantier D, révisé 2026-05-25) |
| `coin_edge_variants` | Tranche A / B (DE 2007-2008 uniquement) | nouveau (Chantier D) |

### 3.2 — Tables existantes à modifier

| Table | Modification | Raison |
|---|---|---|
| `coin_observations` | **Drop + recreate** avec `source_ref TEXT`, FK `source` → `source_registry(id) ON DELETE RESTRICT` | provenance traçable. SQLite n'a pas `ALTER ADD CONSTRAINT` → recreation propre, profite du wipe. |
| `coin_market_quotes` | **Drop + recreate** avec `source_ref TEXT`, FK `source` → `source_registry(id) ON DELETE RESTRICT` | idem |
| `referential_catalog` | **Drop + recreate** avec FK `source` → `source_registry(id) ON DELETE RESTRICT` | doctrine FK étendue à toutes les tables source-aware (cf. §3.4) |
| `coin_canonical_images` | **Drop + recreate** avec FK `source` → `source_registry(id) ON DELETE RESTRICT` | idem |
| `coin_aliases` | **Drop + recreate** avec FK `source` → `source_registry(id) ON DELETE RESTRICT` | idem |
| `coin_names_i18n` | **Drop + recreate** avec FK `source` → `source_registry(id) ON DELETE RESTRICT` | idem |
| `coins` | `raw_payload_json` → drop post-wipe (transitoire devenu obsolète) | doublon avec tables filles |
| `referential_catalog` (audit qualité) | normaliser `country_name` à l'ingestion (variants "Germany" / "Germany, Federal Republic of") | éviter duplicates lors du refetch |

### 3.3 — Tables existantes inchangées (V1 saine)

`design_groups`, `coin_national_variants`, `eurio_id_migrations`, plus toute l'infra `source_runs`, `source_images`, `image_assets`, `experiment_*`, `training_*`, `review_queue`, `discovery_*` — préservées.

### 3.4 — Doctrine FK source — portée

Toute table qui porte un fact attribué (image, alias, nom localisé, observation, prix, payload référentiel) **doit** avoir une FK `source` → `source_registry(id)` avec `ON DELETE RESTRICT`. Les tables d'infra (`source_runs`, `source_images`, `image_assets`, `discovery_*`) gardent leur colonne `source TEXT` libre car leur source est le **pipeline d'enrichissement** (eBay scraper, etc.), pas une source référentielle au sens registry.

**Conséquence opérationnelle** : aucune row ne peut être écrite avec un `source` qui n'est pas seedé en `source_registry`. Les producers (scrapers, refetch scripts) doivent utiliser le vocabulaire canonique du registry — cf. P.3b ci-dessous.

---

## 4. `source_registry`, `mints`, `coin_source_refs` — DDL canonique

### 4.1 — `source_registry`

```sql
CREATE TABLE IF NOT EXISTS source_registry (
  id           TEXT PRIMARY KEY,                  -- ex: 'numista_api', '2euros_org'
  display_name TEXT NOT NULL,
  kind         TEXT NOT NULL
               CHECK (kind IN ('official','reference','community','manual','derived')),
  base_url     TEXT,
  notes        TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 4.2 — `mints` (ateliers normalisés)

```sql
CREATE TABLE IF NOT EXISTS mints (
  id            TEXT PRIMARY KEY,                 -- slug : 'de-berlin-a', 'fr-pessac', 'it-roma-r'
  country       TEXT NOT NULL,                    -- ISO2
  mark          TEXT,                             -- lettre frappe ('A','D','F','G','J', NULL)
  city          TEXT NOT NULL,
  display_name  TEXT NOT NULL,                    -- 'Staatliche Münze Berlin'
  founded_year  INTEGER,
  notes         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mints_country ON mints(country);
```

### 4.3 — `coin_source_refs` (polymorphe Type/Variant/Release)

```sql
CREATE TABLE IF NOT EXISTS coin_source_refs (
  id             INTEGER PRIMARY KEY,
  target_kind    TEXT NOT NULL CHECK (target_kind IN ('coin','variant','mint_release')),
  target_id      TEXT NOT NULL,                   -- eurio_id | variant.id | mint_release.id
  source         TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
  source_native_id TEXT NOT NULL,                 -- numista_id, BCE URL, 2euros slug, ...
  source_url     TEXT,
  notes          TEXT,
  fetched_at     TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (target_kind, target_id, source)         -- une source = un native_id par target
);
CREATE INDEX IF NOT EXISTS idx_coin_source_refs_target
  ON coin_source_refs(target_kind, target_id);
CREATE INDEX IF NOT EXISTS idx_coin_source_refs_native
  ON coin_source_refs(source, source_native_id);
```

### 4.4 — Seed `source_registry`

```sql
INSERT INTO source_registry (id, display_name, kind, base_url, notes) VALUES
  ('numista_api',    'Numista API v3',           'reference', 'https://api.numista.com/api/v3',          'Source primaire référentiel'),
  ('bce_official',   'BCE — pages officielles',  'official',  'https://www.ecb.europa.eu/euro/coins/comm/', 'Date émission, mintage total, image officielle'),
  ('bundesbank',     'Deutsche Bundesbank',      'official',  NULL,                                       'Mintage DE par atelier (A/D/F/G/J)'),
  ('mdp',            'Monnaie de Paris',         'official',  'https://www.monnaiedeparis.fr',           'Prix BU/BE neufs, descriptions FR'),
  ('lmdlp',          'Le Monde des Pieces Euros','community', 'https://www.lmdlp.com',                   'Prix marché secondaire FR, variants'),
  ('wikipedia',      'Wikipedia',                'community', NULL,                                       'Mintage, variants, contexte historique'),
  ('ebay_browse',    'eBay Browse API',          'community', NULL,                                       'Annonces actives — prix marché courant'),
  ('2euros_org',     '2euros.org',               'reference', 'https://www.2euros.org',                  'Compilation référentielle FR — mintage par atelier × qualité, rareté'),
  ('eurio_derived',  'Eurio — calcul interne',   'derived',   NULL,                                       'Facts dérivés en lecture (agreement_count, indice rareté dérivé, ...)'),
  ('manual',         'Curation manuelle',        'manual',    NULL,                                       'Décisions éditoriales admin');
```

→ FK `source` sur **toutes** les tables source-aware (cf. §3.2 et §3.4) pointent vers `source_registry(id)` avec `ON DELETE RESTRICT`.

→ `kind ∈ {official, reference, community, manual, derived}` permet filtrage / priorisation en lecture.

---

## 5. Pure functions — checklist

Toutes vivent dans `ml/referential/` et doivent être :
- pures (même input → même output),
- couvertes par tests golden avec cas litigieux historiques,
- **seule source canonique** de leur logique (suppression des doublons éparpillés).

| Fonction | Fichier canonique | Doublons à supprimer | Golden cases |
|---|---|---|---|
| `eurio_id_from_numista_payload(payload) -> str` | `numista_eurio_id.py` | `audit_apply_common.eurio_id_from_catalog`, `apply_3f_standards.standard_slug` | LV-2018 (Zemgale vs Baltic), BE-2017 (Gand vs Liège), FR-2010 (Appel vs Speech), DE-2009 Saarland, NL-2015 EU Flag, FR-2018 Bleuet (2 colored) |
| `country_to_iso2(name) -> str \| None` | `eurio_referential.py:210` | aucune connue, mais à ré-vérifier | "Germany", "Germany, Federal Republic of", "Deutschland", "European Union", "Andorra", "Vatican City", "Monaco", "San Marino" |
| `design_group_id_from_payload(payload) -> str \| None` | `numista_eurio_id.py` (intégré à la fct principale) | — | Treaty of Rome 2007, EMU 2009, 10 Years Euro Cash 2012, EU Flag 2015, Erasmus 2022 |

---

## 6. Cohorte de validation — 19 coins

### 6.1 — `mix-zone-17` (16 NIDs, cohort_id = `bdc640b9f9c6`)

**Clé = NID Numista** (cf. P.1 finding 2026-05-25 : les slugs eurio_id sont
recomputés à chaque refetch, donc pas stables comme clé externe).

| NID | eurio_id actuel en DB (peut changer post-refetch) | Type | Pays | Notes |
|---|---|---|---|---|
| 68395 | ad-2014-2eur-standard | standard | AD | Andorre — petit pays |
| 64 | at-2002-2eur-standard | standard | AT | premier-millésime |
| 2193 | at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty | commemo | AT | 1 atelier (Vienne) |
| 6292 | be-2007-2eur-standard | standard | BE | |
| 19734 | be-2011-2eur-1st-centenary-of-the-international-womens-day | commemo | BE | |
| 2201 | de-2007-2eur-schwerin-castle-mecklenburg-vorpommern | commemo | DE | série Bundesländer |
| 226447 | de-2020-2eur-50-years-since-the-kniefall-von-warschau | commemo | DE | commémo récente |
| 88 | es-1999-2eur-standard | standard | ES | pré-circulation physique |
| 81058 | es-2016-2eur-old-city-of-segovia-and-its-aqueduct | commemo | ES | UNESCO |
| 93999 | fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright | commemo | FI | |
| 113429 | fi-2017-2eur-100-years-of-independence | commemo | FI | |
| 3561 | fr-2008-2eur-french-presidency-of-the-council-of-the-european-union | commemo | FR | |
| 91431 | fr-2016-2eur-100-years-since-the-birth-of-francois-mitterrand | commemo | FR | |
| 141382 | fr-2018-2eur-simone-veil | commemo | FR | |
| 84714 | it-2016-2eur-2200-years-since-the-death-of-plautus | commemo | IT | |
| 82330 | it-2016-2eur-550-years-since-the-death-of-donatello | commemo | IT | |

### 6.2 — Ajouts ciblés (3 NIDs)

| NID | Label | Motif d'ajout |
|---|---|---|
| **10069** | Bremen Bundesländer 2010 (slug actuel `de-2010-2eur-city-hall-and-roland-bremen` ; post-refetch sera probablement `de-2010-2eur-bundeslander-bremen`) | Cas-fil-rouge 2euros.org. Valide la grille **5 ateliers (A/D/F/G/J) × 3 issue_types (BE/BU/CIRC)** dans `coin_mint_releases`. Référence visuelle directe avec 2euros.org. |
| **134283** | Bleuet de France 2018 — Coloured | Valide la chaîne `coin_variants` : titre Numista actuel `2 Euros (Bleuet de France; Coloured)` → `is_variant=True, finish='coloured'`, parent slug `fr-2018-2eur-bleuet-de-france`. |
| **2162** | Treaty of Rome 2007 DE | Valide la chaîne `design_groups` (joint-issue 13 pays) **et** stresse mint-releases DE multi-ateliers sur un cas joint-issue. Choix DE plutôt que FR/IT pour cumuler les deux dimensions de test dans une seule slot. |

### 6.3 — Couverture matricielle

| Aspect testé | Couverture cohorte |
|---|---|
| 1 atelier, 1 issue_type | ✅ majorité |
| Multi-ateliers (DE 5×) | ✅ Bremen |
| Multi-issue_types (BE/BU/CIRC) | ✅ Bremen + à voir Schwerin |
| Variant coloured | ✅ Bleuet 2018 |
| Standards (circulation) | ✅ 5 coins |
| Pays multi-eurozone | ✅ 8 pays (AD, AT, BE, DE, ES, FI, FR, IT) |
| Joint-issue | ✅ Treaty of Rome 2007 (DE) — couvert |

**Budget Numista cohorte estimé** : ~150-200 calls (types + issues + prices). ~10 % quota mensuel.

---

## 7. Roadmap — phases & chunks

### Phase P — Préparation codebase

| # | Chunk | Effort | Sortie | Bloqué par |
|---|---|---|---|---|
| **P.1** | Audit `numista_eurio_id.py` + écriture golden tests (LV-2018, BE-2017, FR-2010, etc.) | ~2 h | `tests/referential/test_eurio_id.py` vert | — |
| **P.2** | Audit `country_to_iso2()` + golden tests | ~1 h | `tests/referential/test_country_iso2.py` vert | — |
| **P.3** | Migration `ml/state/schema.sql` : (a) ajout des 8 tables nouvelles ; (b) **drop + recreate** des 6 tables source-aware (cf. §3.2) pour porter la FK source → source_registry. SQLite ne supportant pas `ALTER ADD CONSTRAINT`, on profite du wipe imminent pour recréer proprement. Bootstrap via `store.py::_bootstrap`. | ~2.5 h | schema appliqué, bootstrap idempotent | — |
| **P.3b** | **Alignement vocabulaire producers** : auditer tous les scripts qui écrivent `source='ebay'/'numista'/'mdp_issue'/...` et les patcher vers le vocabulaire registry (`ebay_browse`, `numista_api`, `mdp`, ...). Sans ce chunk, premier insert post-P.3 = FK violation. Cibles connues : `ml/sources/ebay/`, `ml/sources/bce/`, `ml/scripts/bootstrap_*`, `ml/scripts/refetch_numista_*`. | ~2 h | code source-aware aligné | P.3 |
| **P.4** | Seed `source_registry` (10 sources : numista_api, bce_official, bundesbank, mdp, lmdlp, wikipedia, ebay_browse, 2euros_org, eurio_derived, manual). Script idempotent. | ~30 min | DB | P.3 |
| **P.5** | **Backup test** : créer `eurio.db.bak-precoinrichness`, **restaurer dans un fichier temporaire** et vérifier intégrité (counts, sample queries) | ~30 min | confiance backup | P.3, P.4 |
| **P.6** | Script `wipe_referential.py` avec : `--dry-run` (liste lignes), `--apply` (avec backup auto + check post-wipe). NE PAS L'EXÉCUTER, juste écrit. | ~1.5 h | script + go-task | P.3 |
| **P.7** | Refacto `refetch_numista_2eur.py` : passer de Supabase UPSERT à SQLite (lecture seule de `referential_catalog`, écriture vers les 7 tables cibles) | ~3 h | script | P.3, P.4, P.1, P.2 |
| **P.8** | Découplage admin Vue ← Supabase → API ml/ : endpoints + remplacement clients Supabase par fetch API | ~3-4 h | admin lit eurio.db | P.3 (les nouvelles tables doivent exister pour endpoints) |
| **P.9** | Archivage scripts legacy : `mv apply_3*.py` + `bootstrap_coins_from_referential.py` vers `ml/referential/_legacy/` avec README de désaffectation | ~30 min | ménage | P.7 |

**Total prep : ~16-17h** (P.3b ajouté +2h).

### Checkpoint avant phase V — backup + audit pre-wipe

- ✅ Tests pure functions verts
- ✅ Nouvelles tables existent et sont vides
- ✅ `source_registry` seedé
- ✅ Backup `eurio.db` créé ET **restauration testée** (P.5 condition non négociable)
- ✅ Admin Vue lit déjà eurio.db (P.8 fini)
- ✅ Wipe script écrit + dry-run vérifié

### — WIPE — (action destructive)

Une seule commande, sous garde-fou interactif :

```bash
go-task ml:wipe-referential -- --apply
```

Wipe la liste actée (cf. §8). NE PAS lancer avant que tous les ✅ du checkpoint soient verts.

### Phase V — Validation vertical-slice sur cohorte 19 coins

| # | Chunk | Effort | Sortie |
|---|---|---|---|
| **V.1** | Refetch Numista cohorte 19 NIDs (`refetch_numista_2eur.py --nids-file ml/state/cohort_validation_19.txt`). ~160-220 calls. Le script lit les NIDs, fait `/coins/{nid}` + `/coins/{nid}/issues` + prices, et **calcule l'eurio_id canonique** via `eurio_id_from_numista_payload`. | ~1 h tournage + 1 h debug | coins + variants + mint_releases + prices Numista + credits + JOUE + design_groups pour 19 coins (eurio_ids = sortie, pas entrée) |
| **V.2** | Branchement BCE sur la cohorte : `issuing_date` + image canonique → `coin_observations` + `coin_canonical_images` | ~1 h | observations BCE attachées |
| **V.3** | Branchement eBay : discovery + price_aggregate sur les 19 coins | ~2 h (durée scrape) | `coin_market_quotes` peuplée pour les 19 |
| **V.4** | **Tour admin par Raphaël** : ouvrir chaque page coin (19), vérifier rendu, divergences multi-source, absence de fallback Supabase, prix affichés, mintage par atelier (Bremen), variant (Bleuet), design_group (Treaty of Rome), JOUE link, designer. **Endpoint admin minimum à décider à ce moment** selon ce qu'il faut voir pour trancher (hypothèse de départ : page détail seule). | ~1 h (visuel) | go/no-go décision |

### — GO/NO-GO —

- **Si V.4 OK** : on passe à Phase F (scale 21 pays + ...) dans une future session.
- **Si V.4 KO** : **pas de rollback auto**. On debug ensemble. La cohorte est en DB, on inspecte, on corrige les scripts, on relance V.1-V.3 (idempotent par design).

### Phase F — Scale (out-of-scope cette session)

`refetch_numista_2eur.py --all-eurozone --apply` une fois validé. ~2000 calls Numista, plusieurs heures.

---

## 8. Wipe scope (liste actée)

### À wiper

```
coins                       (2782 lignes — toutes denoms)
referential_catalog         (688)
design_groups               (18)
coin_cross_refs             (3233)
coin_observations           (3192)
coin_canonical_images       (1022)
coin_aliases                (563)
coin_names_i18n             (3936)
coin_market_quotes          (42 lignes eBay 20-22 mai — historique court, accepté perdu)
coin_national_variants      (0)
```

### À préserver

```
source_runs, source_images, image_assets           (terrain eBay)
discovery_log, discovery_searches, discarded_listings
pending_quotes, listing_text_signals
review_queue, review_claude_verdicts
experiment_cohorts, cohort_members, experiment_iterations, iteration_aug_vs_real, iteration_live_tests
training_runs, training_run_*, training_staging, training_removal_staging
augmentation_recipes, augmentation_runs
benchmark_runs
image_asset_dino_predictions
eurio_id_migrations  (patrimoine — 3 lignes)
```

### Slugs orphelins post-wipe

Les `experiment_*`, `training_run_classes`, `cohort_members` référencent des `eurio_id` qui peuvent **disparaître** au refetch. Politique :

- **Au refetch**, si un eurio_id legacy n'est pas régénéré, on inscrit une ligne dans `eurio_id_migrations(kind='retire', old_eurio_id=<>, status='pending')`.
- Les FK existantes restent (DB ne les nettoie pas via CASCADE car les tables source sont préservées).
- **Lecture future** : un job d'audit (out-of-scope cette session) listera les FK orphelines et permettra arbitrage manuel.

---

## 9. Décisions actées — log

| Date | Décision | Détail |
|---|---|---|
| 2026-05-25 | Doctrine SQLite-only | `eurio.db` canonique, stop reads admin → Supabase. Cf. [[feedback-sqlite-only-doctrine]] |
| 2026-05-25 | Provenance first-class | Chaque fact a `source`, multi-source = multi-row, pas de fallback silencieux |
| 2026-05-25 | `source_registry` + drop `confidence` enum | Source dit qui, registry dit ce qu'est la source |
| 2026-05-25 | Refetch greenfield | Pas de migration de données, wipe + scrape from scratch |
| 2026-05-25 | Vertical slice validation | 19 coins cohorte avant scale 524 |
| 2026-05-25 | Joint-issue dans cohorte | `de-2007-2eur-treaty-of-rome` ajouté (cumule design_groups + multi-mint DE) |
| 2026-05-25 | Fixtures golden tests | Payloads Numista réels stockés en `tests/fixtures/numista/<nid>.json` |
| 2026-05-25 | Refetch input | `refetch_numista_2eur.py --eurio-ids-file <path>` (cohorte en `ml/state/cohort_validation_19.txt`) |
| 2026-05-25 | Endpoint admin V.4 | Décision différée au moment de V.4 selon clarté requise (hypothèse : page détail seule) |
| 2026-05-25 | Test restauration backup | Default : égalité stricte counts + 1 sample query métier. À durcir si anomalie. |
| 2026-05-25 | FK source étendue à 6 tables | Doctrine "FK obligatoire" appliquée à `coin_observations`, `coin_market_quotes`, `referential_catalog`, `coin_canonical_images`, `coin_aliases`, `coin_names_i18n`. Mécanique = drop+recreate (SQLite n'a pas `ALTER ADD CONSTRAINT`) — coût absorbé par le wipe. `ON DELETE RESTRICT` partout. |
| 2026-05-25 | Source registry — 10 sources seed | Ajout `2euros_org` (reference) + `eurio_derived` (derived). Kind élargi à 5 valeurs : `official, reference, community, manual, derived`. |
| 2026-05-25 | DDL `source_registry`, `mints`, `coin_source_refs` | Spécifiées in extenso en §4 (étaient en prose / "..."). |
| 2026-05-25 | Producer vocabulary alignment | Chunk P.3b dédié à patcher les scripts producers vers le vocabulaire registry avant que la FK ne plante. Cibles : `ml/sources/ebay/`, `ml/sources/bce/`, refetch Numista, bootstrap scripts. |
| 2026-05-25 | Source SDK différé post-cohorte | Cf. `docs/sources-refacto/sdk-kickoff.md`. Cohorte 19 sert de banc d'essai du contrat de données ; le SDK arrive quand on est sûr du contrat. Ordre de portage prévu : BCE → Numista → 2euros.org → Bundesbank → eBay. |
| 2026-05-25 | Cohorte clé NID, pas eurio_id | P.1 finding : `MANUAL_NID_SLUG_OVERRIDES` vide + Numista renomme régulièrement ses titres → les slugs eurio_id sont fragiles comme clé externe. La cohorte stocke des NIDs, les eurio_ids sont une **sortie** du refetch. Rename détecté en V.4 → trace via `eurio_id_migrations(kind='rename')`. |
| 2026-05-25 | V1 EMU bug NID 5054 | La pure function produit `de-2009-2eur-economic-and-monetary-union` (joint-issue détecté) sur le titre Numista actuel du Saarland Bundesland 2009. Bug couvert par un test golden qui assert le comportement courant. Fix prévu en P.7 (refetch hardening) via `MANUAL_NID_SLUG_OVERRIDES[5054]` ou acceptation du rename. |
| 2026-05-25 | Backup obligatoirement testé | Pas d'action destructive sans check de restauration |
| 2026-05-25 | Pas de rollback auto | Si validation échoue, on discute |
| 2026-05-25 | Chantier A cote weekly snapshot-only | Bloqué par discovery (cf. `chantier-A-cote.md`) |
| 2026-05-25 | Chantier D — `release_date` en observations (révisé) | Pas de colonne typée, observations BCE + Numista en parallèle |
| 2026-05-25 | Bench single-NID 10069 avant cohorte | API + HTML Numista + 2euros.org + BCE, synthèse en matrice champ × source |
| 2026-05-25 | Échelle rareté 1-10 | Conversion Numista 0-100 → 1-10 inversée. Noms gamification reportés (cosmétique) |
| 2026-05-25 | `mints` schéma slug-based | PK = slug (`de-berlin-a`, `fr-pessac`), FK depuis `coin_mint_releases.mint_id`. Plus de `mint_letter` en TEXT brut |
| 2026-05-25 | Luycx 524 fois OK | `coin_credits` stocke fidèlement Numista, pas de normalisation revers commun |
| 2026-05-25 | Cross-refs catalogues KM#/J#/Schön# | Dans `coin_cross_refs(ref_type='krause_mishler'\|'jaeger'\|'schon')`, pas dans `source_registry` |
| 2026-05-25 | Concept "série" en observations | `coin_observations(observation_type='series')`, promu en table dédiée si besoin d'usage navigation |
| 2026-05-25 | Multi-source same value = 2 lignes | Provenance first-class systématique, agreement_count dérivable read-side |
| 2026-05-25 | Inscriptions en observations | `coin_observations(observation_type='inscription', payload={face, text, lang, translation})` pour démarrer |
| 2026-05-25 | Frequency + Rarity Numista | 2 niveaux : `mint_release_observations(collection_frequency)` per variant + `coin_observations(rarity_index)` Type-level |
| 2026-05-25 | 2euros.org scrape — ordre | 1) Bremen seul (B.3 bench) pour comprendre format ; 2) cohorte 19 (V.*) ; 3) scrape généralisé après validation visuelle |
| 2026-05-25 | Idempotence refetch | `INSERT OR REPLACE` sur `(target, fact_type, source)`. Acceptable de perdre l'historique d'évolution d'une observation Numista entre 2 runs. Cohorte petite = facile à rerun. |
| 2026-05-25 | Sync Supabase = filtered subset | Note pour le futur : SQLite admin = **vue d'ensemble pour comprendre le domaine euro + entraîner le modèle**. Beaucoup de data (inscriptions, sales archive, frequency, séries, observations brutes multi-source) **ne seront pas nécessaires dans Supabase**. Un script de sync explicite sera écrit pour push uniquement ce dont Android a besoin. Pas de miroir 1:1. |

---

## 10. Bench single-NID 10069 (Bremen) — plan validé

Test ciblé **après prep**, **avant la cohorte 19**. Objectif : valider end-to-end la chaîne de sources sur 1 pièce, identifier ce que chaque source donne vraiment.

| # | Bench | Action | Sortie attendue |
|---|---|---|---|
| **B.1** | Numista API : 3 calls sur NID 10069 | `/v3/types/10069`, `/v3/types/10069/issues`, `/v3/types/10069/issues/{first}/prices?currency=EUR&lang=en` | JSON brut, voir si `/issues` retourne 15 lignes (atelier × issue_type) ou 5 (atelier seul) |
| **B.2** | Numista HTML scrape sur NID 10069 (Firecrawl) | `firecrawl scrape https://en.numista.com/catalogue/pieces10069.html` | Tout ce qu'on a vu côté Raphaël : grille 15 lignes + artist links + sets + rarity index + sales archive |
| **B.3** | 2euros.org scrape sur la page Bremen | adapter Python à écrire, capture grille atelier × qualité + indice rareté 1-10 + JOUE link + edge variant si présent | Cross-source confirmation Bundesbank ; capture du JOUE + rareté éditoriale |
| **B.4** | BCE scrape (infra déjà existante) | `python ml/sources/bce/cli.py --year 2010 --country DE` | `issuing_date` + image obverse officielle + texte feature |
| **B.5** | Synthèse | Matrice champ × source dans `docs/coin-richness/bench-single-NID-10069.md` | Identifie pour chaque champ : sources qui le donnent, divergences éventuelles, source recommandée |

### Décisions actées suite à la donnée HTML envoyée 2026-05-25

- **API vs HTML** : on bench **les deux**, on tranche après data. L'hypothèse forte (A — Numista a 15 issues) est posée par le HTML mais reste à confirmer côté API.
- **Sales archive Numista** : **pas essentiel** pour cette session. Capturable plus tard via la même URL scrape. Out-of-scope V.*.
- **Échelle rareté** : **1-10** (même échelle pour Numista, 2euros.org, eurio_derived). Conversion à l'écriture (Numista 0-100 → 1-10, inversé). Noms gamification ("commun / rare / épique") = cosmétique, **reportée**.
- **Mints normalisés** : table `mints` créée dans P.3, FK depuis `coin_mint_releases.mint_id`. Plus de `mint_letter` en TEXT brut.
- **Échanges Numista** : juste `coin_cross_refs(ref_type='numista_swap_url')`, pas de scrape de la liste swappers.
- **Composition** : champ libre dans `coins.composition`, pas typé. Tous les euros suivent le même pattern bimétallique.
- **Image strategy** : BCE → obverse uniquement. Numista → obverse + reverse. Pas de conflit, pas de duplication, pas de logique "source officielle vs fallback".

### Limitation connue

La doc API Numista `https://fr.numista.com/api/doc/index.php` est gatée par Cloudflare (403 sur les fetchers automatisés, WAF kick à ~7 req sur scrape standard). On ne pourra **pas auditer la doc avant le bench**. Conséquence : B.1 sera autant un test qu'une découverte. À documenter pendant l'exécution.

## 11. Questions tranchées (2026-05-25)

Cf. décisions log §9. Synthèse :

1. **Joint-issue** → ajouté (`de-2007-2eur-treaty-of-rome`). Cohorte = 19.
2. **Fixtures golden** → payloads Numista réels en `tests/fixtures/numista/<nid>.json`.
3. **Refetch input** → `--eurio-ids-file <path>`, cohorte en `ml/state/cohort_validation_19.txt`.
4. **Endpoint admin V.4** → décidé au moment de V.4. Hypothèse : page détail seule.
5. **Test restauration P.5** → égalité stricte counts (toutes tables wipées) + 1 sample query métier (ex : page coin Bremen renvoie ses observations + canonical_image). Escalade si anomalie.

---

## 12. Liens

- `docs/coin-richness/kickoff.md` — vision produit + mapping 2euros.org
- `docs/coin-richness/chantier-A-cote.md` — pipeline cote eBay (parallèle, bloqué cron par discovery)
- `docs/coin-richness/chantier-C-mintage.md` — analyse mintage + cohérence (intégré dans cette roadmap)
- `docs/coin-richness/chantier-D-metadata.md` — designer / JOUE / edge / release_date
- `docs/archive/numista-clean-refetch-kickoff.md` — base historique du refetch (à fusionner dans P.7)
- `docs/research/referential-v2.md` — schéma V2 conceptuel (référence)
- `docs/sources-refacto/sdk-kickoff.md` — **Source SDK** (différé post-cohorte, doc vivante à enrichir des findings cohort 19)
- `docs/sources-refacto/module-contract.md` — contrat image/listing-side existant (sera étendu par le SDK)
