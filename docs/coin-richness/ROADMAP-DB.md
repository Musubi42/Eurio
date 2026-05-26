# ROADMAP-DB — Reset référentiel + validation vertical-slice

> **Statut** : Document opérationnel canonique du chantier `coin-richness`.
> Consolide les décisions prises en sessions 2026-05-25.
>
> **Lecteur cible** : nous-mêmes en session, et toute future session Claude
> reprenant ce chantier. Tous les chantiers (`chantier-A`, `chantier-C`,
> `chantier-D`, `kickoff`) sont des **deep-dives** ; ce fichier est le
> chef d'orchestre.

---

## 0. Progress log (2026-05-25)

- ✅ **Session 1 — cadrage** (matin) : doctrine SQLite-only + provenance, schéma cible, cohorte 19, audit cohérence docs/DB.
- ✅ **Session 2 — implémentation prep** (après-midi) : P.1, P.2, P.3a, P.3b, P.4 livrés. ~7h codées sur branche `coin-richness/p3-schema`. Backup `state/eurio.db.bak-pre-p3-2026-05-25` posé.
  - Finding majeur P.1 : **cohorte clé NID** (Numista renomme régulièrement → eurio_ids fragiles comme clé externe). Doc + fichier `cohort_validation_19.txt` réécrits NID-keyed.
  - Bug V1 EMU NID 5054 documenté + figé en test golden.
  - Décision P.3b : **split `source` / `method`** sur `coin_aliases` + `coin_names_i18n` (la colonne `source` mélangeait source et méthode).
  - Mécanique drop+recreate des 6 tables source-aware **déplacée de P.3 vers P.6** (impossible dans `_bootstrap` sans perte de données).
- ✅ **Session 3 — prep complète + acte destructif + V.1 + V.2** (2026-05-26) :
  Toute la Phase P + le wipe effectif + V.1 cohorte 19 + V.2 BCE livrés
  sur branche `coin-richness/p3-schema`. **15 commits** (`ee6d2ec` → `1e50877`).
  192/192 tests P-related verts. Validation MCP chrome admin OK.

  - **Prep P.5+P.6+P.7+P.9+P.8** : verify backup, wipe script, refetch
    SQLite-target (scaffold/fetch/transforms/writer/fixtures cohort),
    archive 12 fichiers legacy, schemas+endpoints+admin Vue refactor.
  - **WIPE exécuté** (commit `5bb1739`) : 15 476 rows supprimées, 6 tables
    FK source enforced, backup auto `eurio.db.bak-pre-wipe-2026-05-26T00-19-22Z`.
    cohort_members CASCADE-deleted (24 rows, accepté).
  - **V.1 refetch cohorte 19** : 149 calls live (38 cache hits) → 19/19 OK.
    coins=19, mint_releases=149, prices=391, market_quotes=55, images=38,
    credits=35, observations=153, design_groups=1 (eu-rome-2007),
    variants=1 (Bleuet coloured). Plusieurs renames eurio_id capturés
    (Bremen, Schwerin→Mecklenburg, etc.).
  - **V.2 BCE branchement** : 22 années scrapées, 12 images promues sur FS
    pour 12 coins de la cohorte (4 standards exclus, 3 commemos non matchés :
    Treaty of Rome, Donatello, Plautus — à debugger en P.10).
  - **Fixes pendant audit** :
    - P.8b.1 (`77b3569`) — CoinsPage refactoré (avait raté en P.8b initial),
      nouvel endpoint `GET /coins` paginated.
    - P.8b.2 (`1e50877`) — `_serve_canonical` avec fallback chain pour
      trouver thumbnails locales BCE/legacy quand `numista_api` n'a pas de
      binaire FS.
  - **Audit visuel validé** : 19 cards, images coexistent Numista+BCE,
    badge DG sur Treaty of Rome, variant Bleuet, renames cohérents.
- ✅ **Session 5 — V.4 tour visuel + P10 partial** (2026-05-26 fin) :
  Tour admin des 19 coins cohorte (7 snapshotées + 11 vérifiées via
  API `/coins/{id}`). **Verdict GO scale 524** posé.
  - **Pattern UI validé** : H1 verbeux FR commémos, badges NUMISTA+BCE
    inline, 3 sections Localisation (titres/topics/aliases) avec
    compteurs cohérents audit §2.1, images Numista+BCE coexistent,
    prix eBay P25/P50/P75 avec count "N annonces analysées",
    Design Group affiché sur treaty-of-rome, aliases marché pertinents
    (kniefall/willy brandt, bleuet/armistice, rome treaty/1957).
  - **A1 (P10-I) fix** : filtre `/coins?fv=2` montrait "eBay 0" car
    `has_ebay` était dérivé de `coin_source_refs` (pas peuplé par
    pipeline eBay). Fix `sources/_base/steps/price_aggregate.py` :
    upsert `coin_source_refs` mirror du pattern BCE quand quote
    écrit. Backfill 15 coins existants. Endpoint
    `/coins/lookups/source-counts` retourne maintenant `ebay=15`.
  - **A2 (P10-J) fix** : H1 standards `ad-2014` = eurio_id brut,
    `at-2002` = "1st map" sans contexte. Fix
    `shared/utils/coin-display.ts` : seuil 12 chars sur `theme`,
    sinon synthèse `"<denom>€ standard (<variant>)"` extrait du slug
    `-standard-`. ad-2014 → `2€ standard (1st type)`.
  - **A3 noté** : enrichment fantôme `cb6139...` sur ad-2014 (run
    pré-V.3 `5a166018`). Eurio_id valide → cleanup conservative ne le
    purge pas. Hors-scope conservative ; relever pour cleanup
    aggressive futur (drop image_assets non-V.3).
  - **P10 cleanup orphans (conservative §2.3)** : DELETE 79
    `image_assets` + 3662 `source_images` dont
    `eurio_id NOT IN coins AND run_id != V.3`. Backup
    `eurio.db.bak-pre-p10-cleanup-2026-05-26T16-03-59Z` posé. Tous
    compteurs orphans = 0 post-cleanup (`coin_source_refs`,
    `coin_market_quotes`, `image_assets`, `source_images`).
  - **Findings non bloquants restants** :
    - P10-F : `/bench` consomme gold frozen, non paramétrable run_id
    - P10-G : DINO anchor bank pré-V.1 → thumbs review queue vides
    - P10-H : BCE adapter scrape uniquement `.en.html`
    - P10-C : 8 fichiers Vue résiduels Supabase
    - 3 commemos BCE non matchés (Treaty of Rome, Kniefall, Plautus)
    - Stretch cleanup : 1882 image_assets + 71 source_images
      pré-V.3 non-orphelins encore en DB (incl. A3)

- ✅ **Session 5d — P10 BCE manual overrides** (2026-05-26 suite) :
  BCE coverage cohorte 2€ commémo : 12/15 → **14/15** (+2 fixes).
  - `sources/bce/adapter.py` : nouveau `MANUAL_BCE_OVERRIDES` dict
    `(country, year, bce_slug) → eurio_id`, court-circuit du fuzzy
    `_match_entry` quand la translation BCE/Numista diverge trop. Avec
    garde-fou : on saute l'override si l'eurio_id targeté n'existe
    plus dans le référentiel courant (évite FK errors après rename).
  - 2 entries ajoutées :
    - DE 2020 : `the-50th-anniversary-of-willy-brandts-kniefall-von-warschau` → `de-2020-2eur-german-polish-reconciliation`
    - IT 2016 : `2200th-anniversary-of-the-death-of-tito-maccio-plauto` → `it-2016-2eur-2200th-anniversary-of-the-death-of-plautus`
  - **Hors portée** : `de-2007-2eur-50th-anniversary-of-the-treaty-of-rome`
    n'est pas listé sur `comm_2007.en.html` (joint-issue → page BCE
    séparée non scrapée). Coverage finale 14/15 attendue tant qu'on ne
    branche pas un scraper joint-issues dédié.
  - `tests/test_bce_adapter.py` (7 tests) : fuzzy single-candidate,
    no-candidate, score-floor, override kniefall, override plautus,
    bypass override si eurio_id absent, sanity keys.

- ✅ **Session 5c — P10-G DINO anchor bank rebuild** (2026-05-26 suite) :
  `go-task ml:dino-anchors:build -- --force` sur `kind=2eur_commemo`.
  Bank passe de 376 anchors pré-V.1 (cohorte legacy avec slugs renamed)
  → 15 anchors fresh cohorte V.3. Backup
  `foundation_anchors_2eur_commemo.npz.bak-pre-rebuild-...` posé.
  - Détour : `datasets/226447/obverse.jpg` manquait pour
    de-2020 (le dataset historique a `obverse.png` 1.4MB). Convert
    PIL PNG→JPG pour respecter la convention du script.
  - Numista CDN refuse les curl directs (anti-bot) — toujours
    convertir depuis le local plutôt que re-fetch.
  - Validation visuelle `/review/manual` : suggestions DINO avec
    thumbs ronds peuplés (avant : placeholders vides quand l'anchor
    pointait sur eurio_id pré-V.1 rename).

- ✅ **Session 5b — P10-F bench audit live** (2026-05-26 suite) :
  Refactor `bench_routes.py` pour accepter un `run_id` arbitraire.
  Nouvelle page `BenchRunAuditPage` qui mime la layout `/bench` studio
  (métriques top + tabs recherches + 3 colonnes pièces / entonnoir /
  listings grid). Pas de scoring (pas de gold humain), on rend
  visuellement les stages persistés du pipeline.
  - Backend : 2 endpoints `GET /bench/runs/{run_id}` (structure par
    discovery group + drops par route_decision×route_reason +
    contexte coin via `coin_canonical_images`) +
    `GET /bench/runs/{run_id}/listings` (drill paginé par groupe/nœud
    avec image eBay externe via `raw_payload_json.image_url`).
  - Frontend : layout studio (groups grid, entonnoir vertical Brut →
    Matcher unmatched → Matchés → Routing 4 drops → Quotes, listings
    panel grid 185px cards).
  - Entrée : bouton "Audit theme-match →" sur la page
    `/sources/ebay/runs/{run_id}` (eBay only).

- ⏳ **Session 6 — Phase F scale 524 + P10 finish** (à venir) :
  Scale eBay aux 524 commémos zone euro + cleanup résiduel.
  - P.5 : `ml/scripts/verify_backup_restore.py` + `go-task ml:verify-backup`. Vert sur backup `eurio.db.bak-pre-p3-2026-05-25` (counts égaux bak↔cur sur 10 tables, integrity_check ok, FK clean, sample query Bremen identique).
  - P.6 : `ml/scripts/wipe_referential.py` (`--dry-run` / `--apply`) + `go-task ml:wipe-referential`. Drop+recreate des 6 tables source-aware avec FK `source → source_registry(id) ON DELETE RESTRICT`. Garde-fou interactif `Type "WIPE"`. Backup auto pré-wipe. Smoke test FK enforcement (savepoint rollback) intégré.
  - Gotcha capturé : `sqlite3.executescript()` commit implicitement la transaction pendante → on split sur `;` et exécute statement par statement en autocommit mode pour préserver le BEGIN IMMEDIATE / COMMIT manuel.
  - Tests : `ml/tests/test_wipe_referential.py` (8 cas, copie DB → tmp_path, exerce apply complet + assertions FK + WITHOUT ROWID préservé + refus confirmation). 126/126 verts.
  - ❌ Wipe **non exécuté** en `--apply` sur la DB réelle — décision produit ouverte (cf. SESSION-KICKOFF-P5-P6.md §8).

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

| Fonction | Fichier canonique | Doublons | Statut tests |
|---|---|---|---|
| `eurio_id_from_numista_payload(payload) -> NumistaSlugResult \| None` | `ml/referential/numista_eurio_id.py:323` | `audit_apply_common.eurio_id_from_catalog` (DEPRECATED header), `apply_3f_standards.standard_slug` (DEPRECATED header). Suppression effective en P.9. | ✅ 86/86 verts (50 legacy + 9 cohort19 regression + 27 autres). Module `ml/tests/test_numista_eurio_id.py`. |
| `country_to_iso2(name) -> str \| None` | `ml/referential/eurio_referential.py:210` | aucune | ✅ 23/23 verts. Module `ml/tests/test_country_iso2.py`. Fix : `"Germany, Federal Republic of": "DE"` ajouté au dict. |
| `design_group_id_from_payload(payload) -> str \| None` | `numista_eurio_id.py` (intégré à la fct principale) | — | ✅ couvert via cas joint-issues du test cohort19 (Treaty of Rome 2007 DE) + 15 cas legacy. |

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

| # | Chunk | Effort | Statut | Sortie |
|---|---|---|---|---|
| **P.1** | Audit `numista_eurio_id.py` + golden tests cohort 19 | ~2 h | ✅ **DONE** 2026-05-25 (branche `coin-richness/p3-schema`) | `ml/tests/test_numista_eurio_id.py` +9 cas (86/86 verts). Finding majeur : cohorte clé NID. V1 EMU bug NID 5054 figé en test. |
| **P.2** | Audit `country_to_iso2()` + golden tests | ~1 h | ✅ **DONE** | `ml/tests/test_country_iso2.py` (23/23 verts). Ajout `"Germany, Federal Republic of": "DE"` dans `COUNTRY_NAME_TO_ISO2` (Numista long-form, 688 catalog rows). |
| **P.3a** | `schema.sql` additif — 9 nouvelles tables. Bootstrap idempotent. | ~1 h | ✅ **DONE** | 9 tables vides : `source_registry`, `mints`, `coin_variants`, `coin_mint_releases`, `coin_source_refs`, `mint_release_prices`, `mint_release_observations`, `coin_credits`, `coin_edge_variants`. FK ON DELETE RESTRICT vers `source_registry` enforced (testé). |
| **P.3b** | Alignement vocabulaire producers + split source/method sur `coin_aliases` + `coin_names_i18n` | ~2 h | ✅ **DONE** | `ml/sources/_base/registry_map.py` (`to_registry_source()`, 23 mappings) + `method TEXT` ajouté aux 2 tables i18n/aliases via `_ensure_column`. 8 producers patchés. `migrate_canonical_schema.py` marqué DEPRECATED. |
| **P.4** | Seed `source_registry` (10 sources, script idempotent) | ~30 min | ✅ **DONE** | `ml/scripts/seed_source_registry.py` + `go-task ml:seed-source-registry`. 10 rows seedées (kind ∈ {official, reference, community, manual, derived}). |
| **P.5** | **Backup test** : restauration dans fichier temporaire + vérif intégrité (counts + sample query) | ~30 min | ✅ **DONE** 2026-05-26 | `ml/scripts/verify_backup_restore.py` + `go-task ml:verify-backup`. Backup pre-p3 vert. |
| **P.6** | Script `wipe_referential.py` (`--dry-run` / `--apply`) **incluant drop+recreate** des 6 tables source-aware avec FK source. Garde-fou interactif. NE PAS L'EXÉCUTER après écriture. | ~2 h | ✅ **DONE** 2026-05-26 | `ml/scripts/wipe_referential.py` + `go-task ml:wipe-referential` + 8 tests pytest (126/126 verts). Wipe **non exécuté** en `--apply`. |
| **P.7** | Refacto `refetch_numista_2eur.py` : Supabase → SQLite, `--nids-file`, écriture vers les 9 tables cibles via registry vocabulary | ~3 h | ✅ **DONE** 2026-05-26 | Script SQLite-target + 4 sous-chunks (a scaffold, b fetch+cache, c.1 mints + c.2 transforms + c.3 writer, d fixtures cohort). 175/175 tests P-related. 3 live fetchs (Bremen 17 + Bleuet 3 + Treaty of Rome 17 = 37 calls). Fixtures committées `ml/tests/fixtures/numista/{10069,134283,2162}/`. Findings dans `findings-numista-api.md`. |
| **P.8** | Découplage admin Vue ← Supabase → API ml/ FastAPI : endpoints + remplacement clients Supabase | ~3-4 h | ✅ **DONE** 2026-05-26 | 3 sous-chunks : (a) schemas sets/coin_series/coin_embeddings + 3 cols coins (personal_owned/lent_to_me/series_id) + 16 endpoints FastAPI + 17 tests. (b) refactor admin Vue (useCoinsApi/useSetsApi + useCoinLookups/CoinDetailPage/SetEditDrawer/SetsListPage). (c) bouclage : zéro `supabase.from()` data dans admin (auth Supabase intacte). Validation MCP chrome OK. |
| **P.9** | Archivage scripts legacy : `apply_3*.py`, `bootstrap_coins_from_referential.py`, `migrate_canonical_schema.py` → `ml/referential/_legacy/` + `ml/scripts/_legacy/` | ~30 min | ✅ **DONE** 2026-05-26 (partiel) | 12 fichiers archivés `ml/referential/_legacy/` (apply_3* cluster + audit_apply_common + migrate_to_v2 + wipe_2eur_for_refetch + clean_referential + bootstrap_design_groups_2eur). 4 résidus gardés (`refetch_numista_2eur` Supabase + `import_numista` + `migrate_canonical_schema` + `bootstrap_coins_from_referential`) car importers actifs (admin live + tests). Bouclage post-P.8 ou session P.10. README.md mapping legacy → moderne. 180/180 tests P-related verts. |

**Total prep réalisé** : ~20 h (P.1 → P.9 inclus). **Reste** : 0 (toute la phase P est livrée) — sauf bouclage P.9 (4 résidus legacy avec importers actifs) qui peuvent attendre P.10.

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
| **V.1** | Refetch Numista cohorte 19 NIDs (`refetch_numista_2eur.py --nids-file ml/state/cohort_validation_19.txt`). ~160-220 calls. Le script lit les NIDs, fait `/coins/{nid}` + `/coins/{nid}/issues` + prices, et **calcule l'eurio_id canonique** via `eurio_id_from_numista_payload`. | ~1 h tournage + 1 h debug | ✅ **DONE** 2026-05-26 (commit `5bb1739`). 149 calls live + 38 cache. 19/19 OK. 391 prices, 149 mint_releases. 1 design_group, 1 variant. Renames eurio_id observés. |
| **V.2** | Branchement BCE sur la cohorte : `issuing_date` + image canonique → `coin_observations` + `coin_canonical_images` | ~1 h | ✅ **DONE partiel** 2026-05-26 (run BCE all-years dans la foulée V.1). 12 images sur FS (4 standards exclus = OK). 3 commemos non matchés (Treaty of Rome, Donatello, Plautus) — fuzzy match BCE à debug en P.10. **Pipeline BCE n'écrit pas en DB** (FS-only) — finding `coin_source_refs.bce_official=0`, à reprendre P.10. |
| **V.3** | Branchement eBay : discovery + price_aggregate sur les 19 coins | ~2 h (durée scrape) | ⏳ next session |
| **V.4** | **Tour admin par Raphaël** : ouvrir chaque page coin (19), vérifier rendu, divergences multi-source, absence de fallback Supabase, prix affichés, mintage par atelier (Bremen), variant (Bleuet), design_group (Treaty of Rome), JOUE link, designer. **Endpoint admin minimum à décider à ce moment** selon ce qu'il faut voir pour trancher (hypothèse de départ : page détail seule). | ~1 h (visuel) | 🟡 **partiel 2026-05-26** : audit visuel V.1+V.2 sur Bremen / Treaty of Rome (DG OK) / Bleuet (variant OK) / liste 19 coins / source counts. Tour final post-V.3 (prix eBay). |

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
| 2026-05-25 | P.3 split P.3a / P.6.recreate | Le drop+recreate des 6 tables source-aware ne peut pas vivre dans `store.py::_bootstrap` (tournerait à chaque démarrage = perte de données). Déplacé dans le script wipe P.6, sous garde-fou interactif, atomique avec le wipe des données. P.3a reste purement additif (9 nouvelles tables, idempotent). |
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
