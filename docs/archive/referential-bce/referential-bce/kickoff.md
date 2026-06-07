# Kickoff — Référentiel BCE complet (session dédiée)

> **Pour qui** : la prochaine session Claude (probablement fraîche) qui va
> attaquer le gros chunk **Source BCE** et l'architecture trust-model du
> référentiel coin.
>
> **À quoi sert ce doc** : prendre la session en 5 min — comprendre ce qui
> a déjà été livré, ce qui est attendu, les décisions actées, et les pièges
> à éviter.
>
> **Date du kickoff** : 2026-05-25

---

## TL;DR

Le **référentiel** (catalogue des pièces commémo 2 €) est à un palier solide
côté infra :

- Stockage local des images canoniques en place (`ml/canonical_images/`).
- Pipeline d'enrichissement Numista per-coin opérationnel + idempotent.
- Page admin `/referential` avec Coverage + Heal + Discover (Numista oracle) + Push (Supabase mirror).
- 600/614 commémo 2 € ont une image canonique locale + Supabase.

**Mais il manque la partie BCE proprement intégrée** : un scraper officiel
qui devient une *Source* dans `/sources`, qui crope intelligemment les images
(BCE met coin + texte dans la même page), et qui pousse ses observations
dans `coin_observations` pour alimenter le **trust model par provenance**
acté en mémoire.

C'est ce chunk-là qu'on attaque. Gros morceau, plusieurs surfaces touchées.

---

## Décisions déjà actées (à ne pas re-débattre)

Avant de coder, il faut intégrer ces décisions dans la tête. Toutes sont en
mémoire ou en docs.

### Architecture stockage

**eurio.db = source de vérité dev**, **Supabase = miroir Android future**,
**MinIO = enrichment eBay uniquement (VPS)**.

- Voir : memory `feedback_architecture_eurio_db_vs_supabase`
- Les images canoniques (Numista + BCE + futur) vivent **localement** sous
  `ml/canonical_images/{eurio_id}/{role}_{source_tag}.webp` (detail 400 px)
  et `..._thumb.webp` (120 px).
- Storage layout helpers : `ml/referential/canonical_image_local.py` (déjà
  livré). Le scraper BCE doit s'appuyer dessus.
- Source tags acceptés : `numista`, `bce` (court, depuis
  `coin_image_storage.source_file_tag`). La table DB utilise les noms longs :
  `numista`, `bce_comm`.

### Trust model

**Confiance par provenance tracée** : pas de "source totale" — chaque pièce
est observée par ≥1 source et carry un `confidence_level` dérivé.

- Voir : memory `project_trust_model_referential`
- Levels prévus : `confirmed` (BCE+Numista), `bce_only`, `numista_only`,
  `joue_only`, `manual`.
- Données brutes dans `coin_observations` (table existante en eurio.db
  + Supabase). Chaque scrape BCE doit y ajouter une ligne par coin matché.
- `confidence_level` à exposer côté UI `/coins/:id` (badge visuel).

### Discover stratégie

**Hybride** : Numista quotidien (réactif) + BCE refresh (mensuel, images
officielles) + JOUE backstop (à explorer plus tard, optionnel).

- Voir : memory `project_data_referential` + roadmap récente.
- Joint issues (Rome 2007, EMU 2009, Euro cash 2012, EU flag 2015, Erasmus 2022)
  sont déjà groupés via `design_group_id` (préfixe `eu-`). **Le scraper BCE
  doit détecter les entries BCE qui sont des joints et matcher l'ensemble du
  groupe, pas une seule entry**.

### Eurozone par année

La timeline de membership est hardcodée dans
`ml/api/referential_routes.py:eurozone_at(year)`. Réutiliser pour les
"pays attendus" sur un joint issue.

---

## Scope du chunk BCE (acté 2026-05-25)

4 axes complets à livrer dans la session dédiée. Ordre suggéré :

### 1. BCE comme Source dans `/sources` (orchestrator + runs)

Aujourd'hui BCE n'est qu'un script ponctuel
(`ml/referential/scrape_bce_images.py`). Il faut le promouvoir au rang de
**Source** comme eBay :

- Wire un adapter dans `ml/api/sources_routes.py:_load_adapter` (case `"bce"`).
- Adapter doit implémenter le contrat `Source._base.adapter.SourceAdapter`
  (déjà utilisé par eBay et le mock).
- Persistence : `source_runs` + `discovery_searches` + `source_images`
  comme pour eBay. Une "discovery_search" BCE = une URL `comm_{year}.en.html`.
- Idempotence : déjà l'idée du script existant (snapshots datés). Garder
  + skip si la page n'a pas changé (HTTP `If-Modified-Since` ou comparaison
  ETag/sha256 sur le HTML).
- Cadence : mensuelle. Surface dans `/sources` la cadence attendue
  (`overdue=True` si > 31 jours).
- Quota : aucun (BCE est public, sans rate-limit déclaré). Mettre en place
  un courtesy throttle (~1 req/s) pour ne pas hammer.

**Fichiers à créer / modifier** :
- `ml/sources/bce/__init__.py` + `adapter.py` (nouvelle source)
- `ml/api/sources_routes.py` (case load_adapter)
- `ml/api/sources_aggregator.py` (status section "bce")
- `admin/packages/web/src/features/sources/composables/useSourcesApi.ts`
  (ajouter `bce` au type `SourceId`)

### 2. Cropping intelligent des images BCE

Les pages BCE ont **coin + descriptif texte ensemble** dans la même image
parfois (ex : 540×540 avec une zone bordure descriptive). Il faut :

- Détecter et isoler le disque coin via **Hough circle** (déjà utilisé dans
  le pipeline scan Android — `ml/scan/normalize_snap.py` + listing detection
  `ml/listing_detection/*.py`).
- Bien dimensionner : 400 px detail + 120 px thumb (cohérent avec
  `canonical_image_local.write_variants`).
- Edge case : certaines pages BCE ont **2 coins** (obverse + reverse côté à
  côté). Détecter 2 cercles et split.
- Edge case : autres pages ont 1 seul coin et c'est l'obverse. Heuristique :
  si 1 seul cercle → obverse ; si 2 → gauche=obverse, droite=reverse.
- Sauvegarder via `canonical_image_local.write_variants(eurio_id, role, "bce_comm", bytes)`.

**Fichiers** :
- `ml/sources/bce/cropper.py` (nouveau, isole la logique de détection)
- Tests sur 5-10 pages BCE différentes pour valider les heuristiques.

### 3. Affichage multi-source dans `/coins/:id`

La page existe (`admin/packages/web/src/features/coins/pages/CoinDetailPage.vue`).
Elle gère déjà 3 shapes d'images (cf. ligne 130+). Il faut :

- Afficher **toutes les sources côte-à-côte** dans la galerie : Numista,
  BCE, eBay listings (déjà câblé via `useCoinAssets`).
- Tag visuel par source (`SRC: NUMISTA`, `SRC: BCE`, etc.).
- Si une source manque, le slot reste vide avec placeholder (pas d'erreur).
- Endpoint pour récupérer toutes les images d'un coin :
  - Option A : étendre `useCoinAssets.ts` pour inclure les canoniques.
  - Option B : nouvel endpoint `GET /referential/coin-canonicals/{eurio_id}`
    qui retourne la liste de tous les `coin_canonical_images` rows pour
    ce coin, avec leurs URLs FastAPI.

**Fichiers** :
- `ml/api/referential_routes.py` (nouvel endpoint)
- `admin/packages/web/src/features/coins/pages/CoinDetailPage.vue`
- Possiblement `useCoinAssets.ts`

### 4. Workflow review divergences BCE↔Numista

Quand BCE et Numista désaccordent sur un coin (slug, theme, year, country
parfois), enqueue une ligne dans une **review queue éditoriale**. L'admin
tranche manuellement via UI.

**Cas concrets observés** (sample, à vérifier) :
- Joint issues 2015 : BCE écrit "European Union Flag", Numista écrit
  parfois "30 Years of European Union Flag". Cohérent mais slug différent.
- Variants `coloured`/`hologram` (NL, FR, LU…) : Numista les liste séparément,
  BCE non.
- AD/SM/VA/MC : BCE peut ne pas lister une année que Numista a déjà.

**Schéma proposé** :
- Table `editorial_review_queue` (à créer) ou réutiliser `review_queue`
  (existe pour les lots eBay → vérifier si on peut pollue/extend).
- Champs : `eurio_id`, `divergence_type` (slug|theme|year|country|missing),
  `bce_payload_json`, `numista_payload_json`, `status` (open|resolved|skipped),
  `resolved_at`, `resolved_by` (admin email).
- UI : nouvelle page `/referential/review` ou tab dans `/referential`.

Plus complexe que les 3 axes précédents — peut être un sous-chunk dans la
session BCE OU séparé en lot 2.

---

## Cible images concrète : les 14 zero-canon

Pour avoir un objectif **mesurable et borné** pendant la session BCE, viser
en priorité les **14 classes encore à 0 image** (Numista n'avait pas d'images
pour elles, BCE peut-être bien).

Liste actuelle (cf. dashboard `/referential` tab "Sans canonical") :
- `ee-2019-2eur-100-years-since-the-foundation-of-the-estonian-language`
- `fi-2014-2eur-100-years-since-the-birth-of-ilmari-tapiovaara`
- `fi-2014-2eur-100-years-since-the-birth-of-tove-jansson`
- `gr-2013-2eur-2400th-anniversary-of-the-founding-of-the-platonic-academy`
- `gr-2018-2eur-70th-anniversary-of-the-union-of-the-dodecanese-with-greece`
- `it-2009-2eur-louis-braille`
- `it-2013-2eur-700th-birthday-of-giovanni-boccaccio`
- `it-2014-2eur-450-years-since-the-birth-of-galileo-galilei`
- `it-2016-2eur-2200-years-since-the-death-of-plautus`
- `it-2016-2eur-550-years-since-the-death-of-donatello`
- `it-2018-2eur-ministry-of-health`
- `it-2022-2eur-falcone-borsellino`
- `lt-2018-2eur-song-and-dance-celebration`
- `lu-2012-2eur-100-years-since-the-death-of-william-iv-grand-duke-of`

Toutes ont une année entre 2009-2022, donc la BCE devrait normalement avoir
ces pages. Si le scraper récupère ces 14 → le bucket "0 images" passe à 0,
référentiel à 100 % images.

---

## État du code juste avant cette session

### Acquis (livré 2026-05-24 / 2026-05-25)

- **`ml/api/referential_routes.py`** — endpoints `/canonical/{eurio_id}/{role}[/thumb]`,
  `/canonical-index`, `/coverage`, `/heal`, `/discover`, `/joint-issues`, `/push`.
- **`ml/referential/canonical_image_local.py`** — helpers stockage local.
- **`ml/scripts/migrate_canonical_images_local.py`** — migration idempotente.
- **`ml/scripts/enrich_missing_payloads.py`** — Numista per-coin pour combler payloads.
- **`ml/scripts/discover_numista_recent.py`** — sweep 21 pays × année courante + suivante.
- **`ml/scripts/push_to_supabase.py`** — push complet idempotent (rewrite URLs + upload Storage + sync tables + cleanup zombies).
- **`admin/packages/web/src/features/referential/pages/ReferentialPage.vue`** — page admin avec 4 actions principales.
- **`admin/packages/web/src/features/operations/pages/OperationsPage.vue`** — dashboard pulse / readiness / diversity / cohorts.

### Données actuelles eurio.db

- 614 commémo 2 € en catalogue, 553 classes distinctes (joints exclus).
- 1185 lignes `coin_canonical_images`, 100 % avec `local_path`.
- 668 dossiers sous `ml/canonical_images/`.
- 0 payload vide.
- 14 classes à 0 canonical (cible BCE).

### Données actuelles Supabase

- 2782 coins (eurio.db == Supabase, plus aucun zombie).
- 3963 observations, 624 market_prices, 3936 i18n rows, 563 aliases.
- Bucket Storage `coin-images` à jour avec le layout canonique
  `{eurio_id}/{role}_{source_tag}.webp` + `_thumb.webp`.

---

## Pièges connus

1. **Numista CDN bloque `User-Agent: Mozilla/5.0`** — utiliser un UA custom
   (`Eurio/0.1 ...`) ou pas de UA du tout. Vu lors du Chunk A.

2. **Slug drift** entre passes de scrape — Numista nomme ses coins en français,
   notre `slugify` peut changer. Avant d'INSERT un nouveau coin, toujours
   chercher par `numista_id` (stable) pas par eurio_id.

3. **Joint issues** ont leur propre `design_group_id` `eu-*-{year}`. Le
   scraper BCE doit détecter les entries qui sont des joints (heuristique
   dans `_BCE_JOINT_TITLE_HINTS` au début de `referential_routes.py`) et
   matcher l'ensemble du design_group, pas chercher un eurio_id unique.

4. **BCE 2026+ n'existe pas encore** — la BCE lag d'environ un an. Pour 2026,
   se reposer sur Numista uniquement (déjà fait, 17 coins en eurio.db).

5. **`x-upsert: true` sur Supabase Storage** : permet l'idempotence sans
   pre-check HEAD (qui timeout en masse). Utiliser systématiquement.

6. **Chrome ORB bloque les `<img>` cross-origin** sans `Cross-Origin-Resource-Policy: cross-origin`. Déjà ajouté sur l'endpoint canonical FastAPI.

7. **Le grid `/coins` utilise un canonical index client-side** pour ne pas
   demander d'images zombies. Si on ajoute des images BCE pour des coins
   sans canonical actuel, l'index doit invalider (refresh page) pour les
   voir apparaître.

---

## Premier pas suggéré

Quand tu reprends :

1. Lire ce kickoff (déjà fait si tu lis ça).
2. Lire la memory `project_trust_model_referential`.
3. Lire la memory `feedback_architecture_eurio_db_vs_supabase`.
4. Lire le code existant : `ml/referential/scrape_bce_images.py` (script v1)
   + `ml/sources/_base/adapter.py` (contrat Source) + `ml/sources/ebay/adapter.py`
   (exemple complet).
5. Discuter avec le user : par quel axe attaquer en premier ?
   - **Recommandé** : axe 1 (BCE comme Source) → la moitié du chunk est
     l'infra orchestration, le reste devient enchaînement. Cibler les
     14 zero-canon comme test d'acceptation E2E.

---

## Liens

- Roadmap globale : `docs/roadmap.md`
- Memory trust : `~/.claude/projects/.../memory/project_trust_model_referential.md`
- Memory archi : `~/.claude/projects/.../memory/feedback_architecture_eurio_db_vs_supabase.md`
- Code Source eBay (référence) : `ml/sources/ebay/adapter.py`
- Code Source mock (template minimal) : `ml/sources/_mock.py`
- BCE script v1 : `ml/referential/scrape_bce_images.py`
- Helpers storage local : `ml/referential/canonical_image_local.py`
- Page admin actuelle : `admin/packages/web/src/features/referential/pages/ReferentialPage.vue`
