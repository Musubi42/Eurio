# Kickoff — Refetch Numista propre + génération eurio_id déterministe

> Document destiné à une **nouvelle session Claude Code**. Lis ce fichier en
> intégralité, puis les fichiers cités en §4 avant tout changement de code.
> Date de rédaction : 2026-05-16. Auteur : session 3e/3f.

---

## 1. TL;DR

L'objectif de cette mission est de **reconstruire la pipeline Numista → eurio_id**
pour les pièces 2€ avec trois garanties :

1. **Déterminisme** — un même payload Numista produit toujours le même eurio_id.
2. **Propreté** — pas de doublons, pas de slugs inconsistants, pas de cross_refs
   sales hérités des scripts V1.
3. **Complétude** — toutes les pièces 2€ existant côté Numista (eurozone 21 +
   Andorre/Monaco/San Marino/Vatican + joint-issues UE) sont importées avec
   metadata, images obverse/reverse, et prix par grade.

Le déclencheur : la session précédente (chunk 3e) a abouti à 32 coins flaggés
`needs_review = true`. En les inspectant on a vu que la plupart des cas sont
issus d'un **script V1 bancal** de génération d'eurio_id (matching par fuzzy
naming, joint-issues mal détectés, variants confondus avec des types).
**Résoudre 32 cas un par un dans l'UI = sparadrap sur un problème de source.**
On préfère repartir d'un référentiel Numista propre.

---

## 2. Pourquoi maintenant

### Ce qu'on a constaté pendant le chunk 3e

- **21 cas `rebind`** (du chunk 3b) : V1 référentiel avait des eurio_ids dont
  le nid Numista bound était sémantiquement faux (audit theme overlap < 0.20).
  La rematch automatique n'a trouvé aucun candidat satisfaisant → nid null
  + flag. Cause racine : le script de matching V1 était trop permissif.
- **4 cas `verify_parent`** (du chunk 3d B2/B3) : 3 NL "Willem-Alexander"
  coloured-only et 1 LU "Guillaume II" classic+hologram qui n'ont pas de
  parent classic Numista évident. On a créé un parent abstrait, en sachant
  que ça mérite vérif humaine. À voir si un refetch propre les couvre
  directement (peut-être Numista a un nid classic qu'on avait raté).
- **7 cas `confirm_or_rematch_uncertain`** (du chunk 3c) : theme overlap
  borderline (0.20 ≤ score < 0.40). 5/7 sont probablement des slots V1
  correctement bound qui pointent vers la même pièce mais sous deux libellés
  différents (ex: FR 2010 "Appeal of 18 June" vs Numista "Speech of June 18th
  1940"). Les autres sont des vrais mismatchs (ex: DE 2009 Saarland mappé à
  l'EMU joint-issue).

### Lecture stratégique

Tous ces cas existent parce que le **slug eurio_id n'est pas une fonction pure
du payload Numista**. Le slug a été construit à des époques différentes par des
scripts différents (`batch_match_numista.py`, manual editing, `bootstrap_*.py`),
qui ne produisaient pas la même chose pour le même input. D'où les dérives.

La doc §5.5 de `referential-v2.md` (rédigée pendant 3f) a posé le **contrat de
re-fetch à deux étages**. Cette nouvelle session doit **enforcer ce contrat
sur tout le corpus 2€**, pas juste sur les 15 standards traités en 3f.

---

## 3. Découvertes faites pendant la session 3e (à ne pas re-faire)

### 3.1 — Numista API expose les prix (contrairement à l'ancienne mémoire)

L'ancienne mémoire `reference_numista_no_price.md` disait « API v3 n'expose
aucun prix ». **C'est faux**. La structure correcte :

```
GET /v3/types/{type_id}                            → metadata du Type
GET /v3/types/{type_id}/issues                     → liste des émissions (mintage, mint_letter, year, comments)
GET /v3/types/{type_id}/issues/{issue_id}/prices?currency=EUR&lang=en  → prix par grade
```

Le 3e endpoint retourne :
```json
{
  "currency": "EUR",
  "prices": [
    {"grade": "g",   "price": 2},
    {"grade": "vg",  "price": 2},
    {"grade": "f",   "price": 2},
    {"grade": "vf",  "price": 2},
    {"grade": "xf",  "price": 2},
    {"grade": "au",  "price": 2},
    {"grade": "unc", "price": 3.4}
  ]
}
```

Numista expose **7 grades** : G, VG, F, VF, XF, AU, UNC. Eurio en a **3** :
UNC, TTB, TB (cf `project_referential_v2_design.md` D3 dans la mémoire).

**Mapping proposé Numista → Eurio** (à valider dans Phase 1 de la nouvelle session) :

| Eurio grade | Numista grades | Stratégie d'agrégation |
|---|---|---|
| `UNC` | `unc` | direct |
| `TTB` | `au`, `xf` | moyenne ou max (XF est en dessous de AU) |
| `TB` | `vf`, `f`, `vg` | moyenne ou max (VF est le seuil "lisible") |

Les grades Numista `g` (Good) sont trop bas pour le marché Eurio — on les ignore.

⚠️ **Implication** : chaque Type Numista a N issues (mint_letter × year × format),
chaque issue a son propre tableau de prix. Pour un Type Eurio (= V2 `coins`
row), il faut décider de l'agrégation :
- Option A — prix au niveau Type (min/median/max sur toutes les issues)
- Option B — prix au niveau Issue (peuple `coin_mint_releases` ET
  `coin_market_prices` avec `target_kind='mint_release'`)

Option B est plus juste mais plus volumineuse. À discuter avec l'utilisateur
dès Phase 1.

### 3.2 — KeyManager multi-clés existe déjà

`ml/referential/numista_keys.py:KeyManager` gère déjà :
- Scan des clés via env `NUMISTA_API_KEY_MUSUBI00`, `MUSUBI01`, …
- Sélection de la clé avec le moins d'appels du mois en cours
- Rotation auto sur HTTP 429 (`call()` wrapper)
- Status via `go-task ml:quota:status -- --source=numista`
- Limite hardcodée : **1800 calls/mois/clé** (free plan Numista)

➡️ **À RÉUTILISER**, pas re-écrire. Le seul changement à envisager : exposer
la liste des clés (status) côté admin Vue dans la page Sources (déjà câblée à
`api_quota`).

### 3.3 — Schéma V2 déjà en place (post-3a/3b/3c/3d/3f)

| Table | Rows | Note |
|---|---:|---|
| `coins` | 2736 | Niveau **TYPE** du modèle V2 (2€ + autres denoms confondues) |
| `coin_variants` | 40 | Variants (coloured / hologram / pattern / mule) |
| `coin_mint_releases` | 0 | **Vide aujourd'hui**, à peupler avec /issues |
| `coin_source_refs` | 4274 | (Type, source, native_id) — `numista` y est présent |
| `design_groups` | 5+ | Joint-issues bootstrappés |

Schéma source de vérité : `supabase/types/database.ts` (généré).

### 3.4 — Tables ajoutées en chunk 3e (à garder)

- `coins.review_action_hint TEXT` — hint UI pour la review queue
- `coins.review_payload JSONB` — contexte review (lost nid, member variants…)
- Index `idx_coins_needs_review` (partiel sur `needs_review=true`)
- Index `idx_coins_review_action_hint`

Migration : `supabase/migrations/20260516_coins_review_context.sql`.
Ces colonnes resteront utiles pour la **future review queue** après refetch
propre — elles seront vides post-cleanup mais l'infra reste en place.

### 3.5 — UI admin Vue de revue est livrée

`/coins/needs-review` dans `admin/packages/web/src/features/coins/`. Composable
`useCoinsReview.ts` consomme l'API `/coins-review/*`. La page restera l'outil
de résolution des cas ambigus que le pipeline propre laissera encore remonter
(beaucoup moins que 32). Cf §7.5.

---

## 4. Fichiers à lire AVANT toute modification

Ordre suggéré (lire les ★ obligatoirement, ⚪ selon besoin) :

### Référentiel & migration
- ★ `docs/research/referential-v2.md` — design canonique V2, décisions D1–D8
- ★ `docs/research/referential-v2.md §5.5` — **Re-fetch contract à 2 étages** (Tier 1 BINDING + Tier 2 SLUG GENERATION + MANUAL_NID_SLUG_OVERRIDES)
- ★ `docs/research/referential-v2-progress.md` — état des 6 chunks 3a→3f
- ★ `docs/research/numista-clean-refetch-kickoff.md` — **ce document**
- ⚪ `docs/research/data-referential-architecture.md` — design V1 (historique)

### Code Numista existant
- ★ `ml/referential/import_numista.py` — script actuel de fetch 2€ → `coin_catalog.json`. **À refactorer pour écrire dans Supabase au lieu de JSON.**
- ★ `ml/referential/numista_keys.py` — KeyManager multi-clés
- ★ `ml/referential/audit_apply_common.py` — `eurio_id_from_catalog()` + `detect_joint_issue()` + JOINT_ISSUES list. **C'est ici que vit la Tier 2 SLUG GENERATION pour les commémos.**
- ⚪ `ml/referential/apply_3f_standards.py` — exemple de Tier 2 pour les standards (`standard_slug()`) + `MANUAL_NID_SLUG_OVERRIDES` stub
- ⚪ `ml/referential/apply_3a_new_types.py` — pattern actuel d'insertion (UPSERT coins + coin_source_refs + design_groups)
- ⚪ `ml/api_quota.py` — moteur sous KeyManager
- ⚪ `ml/api/sources_aggregator.py` — UI Sources (admin Vue) consomme `api_quota`

### Schéma DB
- ★ `supabase/types/database.ts` — types TypeScript générés depuis Postgres
- ★ `supabase/migrations/20260515_referential_v2.sql` — création coin_variants / coin_mint_releases / coin_source_refs
- ★ `supabase/migrations/20260516_coins_review_context.sql` — review_action_hint + review_payload

### UI admin
- ⚪ `admin/packages/web/src/features/coins/pages/CoinsNeedsReviewPage.vue` — page review (post-refetch propre)
- ⚪ `admin/packages/web/src/features/sources/pages/SourcesPage.vue` — vue quotas (où afficher le status des 2 clés Numista)

### Storage & images
- ⚪ `ml/referential/batch_fetch_images.py` — upload Numista images vers Supabase Storage
- ⚪ `ml/referential/coin_image_storage.py` — primitives storage (bucket layout)
- ⚪ `ml/bootstrap/migrate_storage_layout.py` — convention de paths actuels

### Mémoire utilisateur (à mettre à jour)
- ★ `~/.claude/projects/.../memory/reference_numista_no_price.md` — **OBSOLÈTE**. La nouvelle session doit la **remplacer** par un fichier `reference_numista_prices.md` qui documente le bon endpoint, le mapping de grades, et les caveats.
- ★ `~/.claude/projects/.../memory/MEMORY.md` — index, mettre à jour la ligne correspondante
- ⚪ `~/.claude/projects/.../memory/project_data_referential.md` — architecture eurio_id, contient peut-être des claims obsolètes
- ⚪ `~/.claude/projects/.../memory/project_referential_v2_design.md` — décisions D1–D8 V2

---

## 5. Contrat eurio_id durci (à enforcer partout)

### 5.1 — Tier 1 : BINDING (autoritaire)

```python
def fetch_or_create_type(numista_payload: dict, sb: SupabaseClient) -> str:
    """Return the eurio_id for this Numista payload, creating if needed.

    Step 1 — query coin_source_refs by (source='numista', native_id=nid).
    Step 2 — if found, return that coin_type_id. Update metadata in coins,
             NEVER touch eurio_id slug.
    Step 3 — if not found, fall through to Tier 2.
    """
```

**Conséquence** : un eurio_id est **gelé à la création**. Si Numista renomme le
`catalog_name` plus tard, on update les métadonnées mais l'eurio_id reste
celui d'origine. Le binding survit aux renames.

### 5.2 — Tier 2 : SLUG GENERATION (fonction pure)

Pour un nid Numista inconnu :

```python
def eurio_id_from_numista(payload: dict) -> str:
    """Pure function — same payload → same eurio_id, always.

    Path :
      1. Extract country ISO2 (lowercase), year, face_value from payload
      2. If face_value != 2.0 → out of scope, return None (Phase 1 = 2€ only)
      3. Detect joint-issue → return joint-issue slug `{iso}-{year}-2eur-{theme-slug}-{country-suffix}`
      4. Detect variant suffix in catalog_name (coloured/hologram/…) → slug WITHOUT finish (parent), variant separately
      5. Detect commemo (object_type = 'Circulating commemorative coins') → use parenthesized theme as slug
      6. Detect standard (object_type = 'Standard circulation coins') → use standard_slug() heuristic from apply_3f_standards.py
      7. Slugify, append face_value tag, prefix with country/year
    """
```

⚠️ **Pas de domain knowledge externe**. Pas de « je sais que VA 2017 c'est la
2nd map ». Le slug doit être 100% dérivable du payload Numista. Si Numista
n'expose pas l'info, **le slug ne la contient pas** (l'année désambigue souvent).

### 5.3 — Manual overrides (escape hatch)

Quand un override est légitime (BCE/Wikipedia disent que 2 nids Numista
identiques en nom sont en réalité 2 designs différents), on l'inscrit dans :

```python
MANUAL_NID_SLUG_OVERRIDES: dict[int, str] = {
    # nid: full eurio_id slug, keyed by Numista native_id pour déterminisme au refetch
    # 12345: "fr-2017-2eur-rodin-second-map",  # source: Wikipedia https://...
}
```

**Toujours citer la source** dans un commentaire. Le keying par nid garantit
qu'au re-fetch, le même nid produit le même slug overridé.

### 5.4 — Tiebreaker pour collisions inter-batch

Si deux nids Numista produisent le même `(country, year, slug)` (signal de
duplicate côté Numista, ou de slugger trop permissif), suffix `-{numista_id}`
+ flag `needs_review=true` + `review_action_hint='confirm_or_rematch_uncertain'`
+ `review_payload={kind, …}`.

Convention déjà documentée dans `referential-v2-progress.md §5.5`.

---

## 6. Architecture cible du pipeline refetch

### 6.1 — Orchestrateur

Nouveau script `ml/referential/refetch_numista_2eur.py` (ou refactor de
`import_numista.py`). Structure :

```
1. KeyManager().pick() → clé courante
2. Pour chaque pays eurozone + AD/MC/SM/VA :
   2a. /v3/types?issuer={iso}&face_value=2&page=N&count=50&lang=en
   2b. Pour chaque type retourné :
       i.   /v3/types/{nid}     → metadata complètes
       ii.  /v3/types/{nid}/issues → liste issues (= mint_releases)
       iii. Pour chaque issue :
            /v3/types/{nid}/issues/{iid}/prices?currency=EUR → prix par grade
3. Pipeline de transformation :
   a. fetch_or_create_type(payload, sb)  → eurio_id (Tier 1 ou Tier 2)
   b. UPSERT coins (metadata curated)
   c. UPSERT coin_source_refs (source=numista, native_id=nid, raw_payload=payload)
   d. INSERT coin_mint_releases (1 par issue)
   e. INSERT coin_market_prices (target_kind='mint_release' ou 'type' selon décision §3.1)
   f. Trigger download image obverse/reverse → upload Supabase Storage
4. À la fin :
   - Log des collisions (multiples nids → même slug)
   - Log des skipped (face_value != 2)
   - Stats : N nids fetched, N coins created, N updated, N quota left
```

### 6.2 — Quota budget estimé

Pour ~700 pièces 2€ × 3 endpoints (types + issues + 1+ prices par issue),
estimation pessimiste :
- 700 search calls (paginated) ≈ 30 calls
- 700 type detail calls ≈ 700 calls
- 700 issues calls ≈ 700 calls
- En moyenne 4 issues par type × 700 = 2800 prices calls

**Total ~4230 calls**. Avec 2 clés × 1800/mois = 3600. **Ça ne tient pas en
un mois sur 2 clés.**

Mitigations possibles :
- (a) Ne fetcher /issues + /prices que pour les types nouvellement créés ou
  modifiés (cache last_updated)
- (b) Fetcher prices uniquement pour issues "intéressantes" (les circulation,
  pas les BU/BE/Proof qui sont moins liquides)
- (c) Étaler sur 2 mois calendaires
- (d) Demander à l'utilisateur d'ajouter une 3e clé (NUMISTA_API_KEY_MUSUBI02)

➡️ **Décision à prendre Phase 0** avec l'utilisateur avant de lancer.

### 6.3 — Storage images

Pattern actuel : bucket `coin-images` Supabase Storage, layout
`{eurio_id}/{filename}` (cf `migrate_storage_layout.py`). À conserver.

URLs source Numista : `obverse.picture` / `reverse.picture` du payload `/v3/types/{nid}`.
Format : `https://en.numista.com/catalogue/photos/.../*.jpg`.

⚠️ **License** : Numista expose `obverse.picture_copyright` + `picture_license_name`
(souvent "CC BY-SA"). À stocker dans le row coins (champ `license` à ajouter)
et respecter au moment de la redistribution dans l'app Android.

### 6.4 — Mapping prix Numista → coin_market_prices

Table existante `coin_market_prices` :

```sql
CREATE TABLE coin_market_prices (
  id          bigserial PRIMARY KEY,
  eurio_id    text REFERENCES coins(eurio_id),
  source      text,        -- 'numista' nouveau, 'ebay' existant
  quality     text,        -- 'UNC' | 'TTB' | 'TB' (Eurio scale)
  p25         numeric, p50 numeric, p75 numeric,
  samples_count int,
  with_sales_count int,
  query_used  text,
  fetched_at  timestamptz NOT NULL DEFAULT now()
);
```

Pour Numista, `samples_count = 1` (une cote, pas N ventes), `p50 = price`,
`p25 = p75 = price` (pas de distribution).

Si l'option B (price par mint_release) est retenue, il faudra envisager :
- Migration : ajouter `target_kind` + `target_id` polymorphe (D8 du doc V2)
- Ou : table dédiée `mint_release_prices` (moins propre, mais isolé)

---

## 7. Phases proposées pour la nouvelle session

### Phase 0 — Cleanup & alignement (chunk court, ~30min)

**Objectifs :**
1. Re-lire ce kickoff + référentiel-v2.md §5.5 + référentiel-v2-progress.md
2. Mettre à jour la mémoire `reference_numista_no_price.md` → `reference_numista_prices.md` (cf §9)
3. Aligner avec utilisateur sur les **questions ouvertes §8** :
   - Quota stratégie (3e clé, ou phasé sur N mois, ou skip prices au début)
   - Granularité prix (Type vs Mint_release)
   - Storage images : keep filesystem ou re-route vers Supabase Storage
4. Préparer le **wipe SQL** (DELETE coins WHERE face_value=2.0 + cascade) et
   le présenter à l'utilisateur pour confirmation **avant exécution**.

**Livrable :** doc d'alignement court (5-10 lignes) avec les décisions
prises, sauvé dans `docs/research/numista-clean-refetch-progress.md` (suivre
le pattern de `referential-v2-progress.md`).

### Phase 1 — Wipe greenfield 2€ (chunk ~15min)

⚠️ **DESTRUCTIF — exiger confirmation explicite utilisateur avant `--apply`.**

Script `ml/referential/wipe_2eur_for_refetch.py` :
1. Fetch toutes les rows `coins WHERE face_value = 2.0`. Log les counts par
   `(country, is_commemorative)` pour audit.
2. Pré-conditions à vérifier :
   - Aucun user_collections ne référence ces coins (sinon STOP, l'utilisateur
     décide quoi faire)
   - Compter et logger les dépendants : variants, mint_releases, source_refs,
     market_prices, set_members, embeddings, confusion_map, etc.
3. Mode `--dry-run` (par défaut) → snapshot JSON des counts dans
   `ml/datasets/wipe_2eur_dryrun.json`
4. Mode `--apply` → DELETE coins (les FK ON DELETE CASCADE/SET NULL gèrent le reste)
5. Vérification post-wipe : `SELECT count(*) FROM coins WHERE face_value=2.0` → 0

**Audit visuel :** count avant → count après. Doit passer de ~2596 → 0.

### Phase 2 — Tier 2 slug generation refactor (chunk ~2h)

Centraliser la génération de slugs dans **un seul module** :
`ml/referential/numista_eurio_id.py`. Doit exposer :

```python
def eurio_id_from_numista_payload(payload: dict) -> str | None:
    """Pure function. Returns None if out of scope (not 2€)."""
    ...

MANUAL_NID_SLUG_OVERRIDES: dict[int, str] = {
    # Add entries with citation
}

def is_variant(catalog_name: str) -> tuple[bool, str | None]:
    """Detect variant suffix → (is_variant, finish or None)."""
    ...

def joint_issue_slug(catalog_name: str, year: int, country: str) -> str | None:
    """Joint-issue specific slug, cf JOINT_ISSUES list."""
    ...
```

Reprend la logique éparpillée dans :
- `audit_apply_common.eurio_id_from_catalog()`
- `audit_apply_common.detect_joint_issue()`
- `audit_apply_common.JOINT_ISSUES`
- `apply_3f_standards.standard_slug()`
- `eurio_referential.slugify()`

Tester avec un dataset de fixtures : `tests/test_numista_eurio_id.py` doit
inclure ≥ 50 cas (chacun avec un commentaire « source : nid X de Numista »)
couvrant : standard, commémo nationale, joint-issue, variant coloured, variant
hologram, redesigns (1st/2nd map), manual override.

**Livrable auditable :** `pytest -v tests/test_numista_eurio_id.py` passe à 100%.

### Phase 3 — Orchestrateur fetch + prices + images (chunk ~3-4h)

Refactorer (ou réécrire) `import_numista.py` en `refetch_numista_2eur.py`.
Sortie : écrit directement dans Supabase (plus de `coin_catalog.json` comme
source de vérité — il peut rester comme cache mais ne pilote plus rien).

Sous-étapes :
- **3a** Fetch only metadata + create coin rows (skip issues/prices). Audit
  visuel : count coins WHERE face_value=2.0 et source_refs numista. Devrait
  approcher ~700.
- **3b** Fetch issues → populate coin_mint_releases. Audit visuel : counts par
  mint_letter pour DE.
- **3c** Fetch prices → populate coin_market_prices (Type-level ou
  mint_release-level selon décision Phase 0).
- **3d** Download + upload images obverse/reverse.

Chaque sous-étape commit son progrès dans une table `refetch_progress` SQLite
ou un fichier `state/refetch_state.json` pour reprise après crash/quota.

**Livrables auditables** par sous-étape : counts SQL + un coin sample affiché
complet en stdout après chaque chunk.

### Phase 4 — Verifications & invariants (chunk ~1h)

Script `verify_refetch.py` qui valide :
- **Unicité** : aucun couple `(country, year, slug)` collisionné
- **Déterminisme** : `eurio_id_from_numista_payload(payload)` redonne le
  slug stocké (sample sur 50 coins random)
- **Couverture** : toutes les 21 issuer codes eurozone + AD/MC/SM/VA ont au
  moins quelques rows
- **Storage** : chaque coin a une obverse_url qui résout (HEAD 200)
- **Prices** : ≥ 80% des coins ont au moins un coin_market_prices avec
  source=numista
- **Sanity** : aucun coin avec `needs_review=true` (la queue doit être vide à
  la sortie d'un refetch propre)

**Livrable :** `numista-clean-refetch-progress.md` mis à jour avec les counts
finaux et un GO/NO-GO pour ouvrir la review queue aux humains.

### Phase 5 — Re-population infra adjacente (chunk ~30min)

Une fois les coins propres :
- Régénérer `app-android/src/main/assets/catalog_snapshot.json` via
  `go-task android:snapshot` (snapshot pour scan offline)
- Trigger `go-task ml:bootstrap-coins` pour synchroniser SQLite `coins` table
  (sources orchestrator dépend de ça)
- Relancer eBay scrape sur les nouveaux eurio_ids (lot small initial, puis
  full)

### Phase 6 — Adaptations needs-review UI (chunk ~1h)

Selon ce que Phase 4 laisse remonter (typiquement quelques dizaines de cas
ambigus au lieu de 32), adapter :
- Ajouter `review_action_hint` types si nouveaux patterns émergent (ex:
  `collision_tiebreaker` pour des coins suffixés `-{nid}`)
- Adapter `useCoinsReview.ts` types
- Ajouter panel UI si nouveau hint

Pas plus de 100 lignes de code attendu — l'infra UI est solide.

---

## 8. Questions ouvertes à régler en Phase 0

À poser à l'utilisateur **avant tout code** :

1. **Quota** : on est à ~4230 calls estimés pour un refetch full. 2 clés × 1800
   = 3600. Options :
   - (a) 3e clé Numista (NUMISTA_API_KEY_MUSUBI02)
   - (b) Skip /prices au premier refetch, juste metadata + images, refetcher
     prices en Phase ultérieure
   - (c) Étaler sur 2 mois calendaires (le 1er du mois reset les quotas)
   - (d) Ne fetcher prices que pour issues circulation (skip BU/BE/Proof)

2. **Granularité prix** : Type-level (1 row coin_market_prices par
   Type×grade, agrégé sur issues) ou Mint_release-level (1 row par
   issue×grade, plus volumineux mais plus juste) ?

3. **Mapping grades** : valider le mapping proposé §3.1 ou ajuster ?

4. **Storage images** : conserver l'actuel layout (Supabase Storage
   `coin-images/{eurio_id}/*.jpg`) ou changer ?

5. **Variants** : pendant le refetch, comment traiter les nids Numista qui
   sont des variants (coloured/hologram) ? Auto-création de `coin_variants`
   sous un parent classic, ou flag needs_review pour décision humaine ?
   Recommandation : auto si le sibling classic existe dans la même
   country/year, sinon needs_review.

6. **Joint-issues** : la liste `JOINT_ISSUES` dans `audit_apply_common.py` est
   datée. À refresh ? Vérifier 2025/2026 (Erasmus 2022 est dedans, mais y a-t-il
   eu d'autres joint-issues depuis ?).

7. **Manual overrides** : commencer avec 0 override et n'en ajouter qu'au cas
   par cas quand le pipeline génère un slug ambigu, ou bootstrap-er d'emblée
   avec les overrides connus (ex: VA 2017 2nd map, MT/VA portraits redesigns) ?

---

## 8bis. Réponses utilisateur (2026-05-16)

Décisions actées par Raphaël en réponse aux 7 questions ouvertes §8. **Source
de vérité — toute divergence avec §8 doit être lue ici.**

1. **Quota** → **non-bloquant**. On a **4 clés** Numista désormais
   (`MUSUBI00..03`), pas 2. Le budget de ~4230 calls tient confortablement
   sur 4×1800 = 7200/mois. → **on fait la totale** : metadata + /issues +
   /prices + images obverse + reverse. Aucune des mitigations (a)/(b)/(c)/(d)
   §6.2 n'est nécessaire.

2. **Granularité prix** → **Option B (mint_release-level)**. On préfère
   volumineux + juste plutôt que compact + approximatif. Si la DB doit être
   retouchée pour accommoder (ex: ajouter `target_kind`/`target_id`
   polymorphes sur `coin_market_prices`, ou table dédiée
   `mint_release_prices`), on retouche — un refetch complet est l'occasion.

3. **Mapping grades Numista → Eurio (3 vs 7)** → **à réfléchir, pas tranché**.
   Tension produit : app grand public (UNC/TTB/TB lisible par un kidam) vs
   aficionados (qui veulent les 7 grades Numista). Piste à explorer en Phase 0
   ou Phase 3c : **double exposition**
   - **Option A par défaut** (UNC/TTB/TB agrégés, clair pour le grand public)
   - **Option B disponible** pour aficionados (drill-down sur les 7 grades
     Numista bruts).

   Stockage implication : conserver les **7 grades bruts** dans le row de
   prix (champ raw JSON ou colonnes Numista séparées) **en plus** des 3
   agrégés Eurio, pour ne pas perdre l'info à l'ingestion. La présentation
   double (kidam-friendly + aficionado mode) sera tranchée côté UI/Android
   plus tard. **Ne pas hardcoder un seul mapping irréversible.**

4. **Storage images** → confirmé : layout actuel `coin-images/{eurio_id}/*.jpg`
   (Supabase Storage). **Obverse ET reverse** vont en storage (les deux faces).
   Pas d'autres images (edge, packaging, etc.) — uniquement avers + revers.

5. **Variants (coloured/hologram/etc.)** → **auto par défaut**. Si l'auto-binding
   sur un parent classic (même country/year) n'est pas possible (parent
   manquant ou ambigu), → `needs_review=true` avec une **règle explicite**
   à définir en Phase 2 (probablement : « pas de sibling classic dans la même
   `(country, year, denom)` → review »). Pas de fallback silencieux.

6. **Joint-issues** → liste `JOINT_ISSUES` actuelle suffisante. **Pas de
   nouveaux joint-issues** depuis Erasmus 2022. Le refetch complet rejouera
   la détection sur tout le corpus, donc rien à ajouter manuellement. Si le
   refetch fait remonter un cas qu'on aurait manqué, il partira en
   `needs_review`.

7. **Manual overrides** → **démarrer à 0**, `MANUAL_NID_SLUG_OVERRIDES = {}`.
   Les ambiguïtés détectées par le pipeline (collisions, slug indécidable,
   variants orphelins) partent en `needs_review` et seront résolues humainement
   via la queue admin. On ajoutera des overrides **a posteriori**, au cas par
   cas, uniquement quand la review humaine en fait émerger un qui mérite
   d'être figé pour les re-fetches futurs.

---

## 9. Mémoire utilisateur à mettre à jour

### À remplacer (l'ancien est faux)

`~/.claude/projects/-Users-musubi42-Documents-Musubi42-Eurio/memory/reference_numista_no_price.md`

Contenu obsolète : « Numista API v3 ne retourne aucune donnée de prix ». Le 2026-04-13 le test était fait sur `/v3/types/{id}/prices` (404) mais pas sur le bon endpoint `/v3/types/{id}/issues/{issue_id}/prices` qui retourne bien les prix.

**À remplacer** par un nouveau fichier `reference_numista_prices.md` avec :
- Endpoint exact + params
- Format de réponse (7 grades)
- Mapping Numista → Eurio (3 grades)
- Caveat : 1 prix par issue, pas par type — agrégation nécessaire

### Index à mettre à jour

`~/.claude/projects/.../memory/MEMORY.md` ligne actuellement :
```
- [Numista no price data](reference_numista_no_price.md) — API v3 n'expose aucun prix/cote, uniquement métadonnées
```

À remplacer par :
```
- [Numista prices](reference_numista_prices.md) — endpoint /issues/{id}/prices expose 7 grades, mapping vers UNC/TTB/TB Eurio
```

### À considérer (peut-être obsolète)

- `project_data_referential.md` — claims sur eurio_id construction, vérifier qu'elles restent valides post Phase 2.
- `reference_numista_ratelimit.md` — toujours valide (1800 calls/mois/clé), juste mettre à jour la date.

---

## 10. Critères d'acceptation finaux

La mission est terminée quand **tous** ces points sont validés :

- [ ] `pytest tests/test_numista_eurio_id.py` passe (≥ 50 cas)
- [ ] `SELECT count(*) FROM coins WHERE face_value=2.0` ≥ 650
- [ ] `SELECT count(*) FROM coins WHERE face_value=2.0 AND needs_review=true` = 0
- [ ] `SELECT count(*) FROM coin_source_refs WHERE source='numista'` ≥ 650 (un par coin)
- [ ] `SELECT count(DISTINCT eurio_id) FROM coin_market_prices WHERE source='numista'` ≥ 0.8 × N coins
- [ ] `SELECT count(*) FROM coin_mint_releases` ≥ 1500 (estimation : ~2 issues / type en moyenne)
- [ ] Spot-check 10 coins random : obverse + reverse image HTTP 200 sur leur URL
- [ ] `MANUAL_NID_SLUG_OVERRIDES` documenté avec citation source pour chaque entrée
- [ ] Mémoire `reference_numista_prices.md` créée, ancien `reference_numista_no_price.md` supprimé
- [ ] `docs/research/numista-clean-refetch-progress.md` rédigé avec stats finales et liste complète des overrides ajoutés
- [ ] Snapshot Android régénéré (`go-task android:snapshot`)
- [ ] Page admin `/coins/needs-review` ouverte, queue stable (< 30 cas attendus, vs 32 actuels — preuve que le refetch propre a éliminé le bruit)

---

## 11. Hygiène / non-régressions

- **NE PAS** toucher `app-android/src/main/java/com/musubi/eurio/ui/theme/Color.kt`, `Shape.kt`, `Spacing.kt` (auto-generated, cf CLAUDE.md R2)
- **NE PAS** créer des `TODO:` dans le code (la dette doit être trackée via
  `numista-clean-refetch-progress.md`, pas dans le code)
- **TOUJOURS** `go-task ml:apply-...-dry` avant `--apply` sur les scripts
  destructifs
- **TOUJOURS** confirmer avec l'utilisateur avant un DELETE en masse, même si
  scripté en dry-run
- **PROTO-FIRST ne s'applique pas à l'admin Vue** (cf
  `feedback_proto_first.md`) : la page review actuelle a été codée
  directement en Vue, c'est OK. Pour l'app Android par contre, la règle reste.

---

## 12. Conseils pratiques pour la prochaine session

- **Commencer par lire ce doc + référentiel-v2.md §5.5 dans cet ordre.** Sans
  le contrat §5.5 en tête, le slug generation va dériver.
- **Tester un seul pays d'abord** (Andorre = 8 commémos depuis 2014, petit
  volume, peu de chances de joint-issue piège). Si l'orchestrateur produit
  un eurio_id propre pour AD, étendre.
- **Bench le quota tôt** : faire un mini-refetch (1 pays) et mesurer le coût
  réel. Si 1 pays consomme 80 calls (au lieu des 20 estimés théoriques), le
  budget global doit être réévalué.
- **L'admin Vue page Sources** affiche déjà le quota Numista. Garder un œil
  dessus pendant les fetches.
- **NE PAS hardcoder les slugs** dans les scripts d'application. Si tu écris
  `eid = "fr-2017-2eur-..."` quelque part, c'est suspect. Tout doit venir de
  `eurio_id_from_numista_payload()`.
- **Si tu as un doute sur un slug**, ne devine pas — ajoute le nid dans
  `MANUAL_NID_SLUG_OVERRIDES` avec un commentaire `# TODO confirm with user`
  et flag `needs_review=true`. L'admin tranchera via la review queue.

---

## 13. Glossaire

- **eurio_id** — slug canonique Eurio, ex `fr-2017-2eur-auguste-rodin`. PK de
  `coins`.
- **nid** / **numista_id** — id natif Numista, ex `5054`.
- **Type** — niveau du modèle V2, = ligne `coins`. Le design canonique.
- **Variant** — finition graphique d'un Type (coloured / hologram / pattern /
  mule), ligne `coin_variants`.
- **Mint release** — émission d'un Type par atelier × année × format
  (CIRC/BU/BE/PROOF), ligne `coin_mint_releases`. Correspond à un `issue`
  Numista.
- **Issue** (Numista) — équivalent Numista d'un mint_release Eurio.
- **Joint-issue** — pièce commémorative émise par plusieurs pays sur le même
  thème (Erasmus 2022, EU Flag 2015, Euro Cash 2012, EMU 2009, Treaty of Rome
  2007). Chaque pays a un Type Eurio distinct lié à un même `design_group_id`.
- **Standard** — pièce de circulation non-commémorative (les "design de base"
  des cents et 1/2€ pour chaque pays).
- **Source_ref** — lien Type ↔ source externe (ligne `coin_source_refs`).
- **Tier 1 / Tier 2** — étages du contrat de re-fetch (§5).
- **Quota** — limite mensuelle Numista, 1800 calls/clé/mois. Géré par
  `KeyManager` qui rotate sur 429.

---

*Fin du document. Bonne mission. Si quelque chose dans ce doc s'avère faux,
mettre à jour ce fichier en priorité avant de coder — il sera relu par toutes
les sessions futures.*
