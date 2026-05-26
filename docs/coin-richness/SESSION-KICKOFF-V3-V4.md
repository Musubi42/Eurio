# Kickoff — Session V.3 + V.4 + P.10 (post-prep, post-V.1, post-V.2)

> Document destiné à une **nouvelle session Claude Code** (ou à Raphaël lui-même
> en reprise). Lis-le **en entier** puis l'ordre de lecture §3 avant tout code.
>
> Date de rédaction : **2026-05-26** (fin session 3 — toute la prep livrée +
> wipe exécuté + cohorte 19 refetchée + BCE branchée).

---

## 1. TL;DR

La session précédente (2026-05-26) a livré **15 commits massifs** sur
`coin-richness/p3-schema` :

1. **Phase P complète** : P.5 (verify backup) + P.6 (wipe script) + P.7
   a/b/c.1/c.2/c.3/d (refetch SQLite-target) + P.9 (archive 12 fichiers
   legacy) + P.8 a/b/c (découplage admin Vue ↔ FastAPI).
2. **Wipe exécuté** : 15 476 rows référentielles supprimées, FK source
   enforced sur 6 tables source-aware, backup auto posé.
3. **V.1 cohorte 19** : refetch Numista de 19 NIDs (149 calls live + 38
   cache) → 19/19 OK. 391 prices, 149 mint_releases, 1 design_group
   (Treaty of Rome `eu-rome-2007`), 1 variant (Bleuet coloured).
4. **V.2 BCE partiel** : 12 images BCE sur FS pour 12 commemos de la
   cohorte (4 standards exclus, 3 commemos non matchés).
5. **Audit visuel** validé : liste 19 coins, images coexistent
   Numista+BCE en CoinDetailPage, badge DG, variant Bleuet.
6. **2 fixes audit** : P.8b.1 (CoinsPage) + P.8b.2 (_serve_canonical
   fallback chain).

**À faire cette session** :

- **V.3** — branchement eBay (discovery + price_aggregate) sur la cohorte 19
- **V.4** — tour admin final + GO/NO-GO scale 524
- **P.10** — bouclage des findings (8 fichiers Supabase data résiduels,
  BCE FS→DB, 3 commemos BCE non matchés, 4 résidus legacy P.9)
- **Phase F** (optionnel) — scale aux 524 coins eurozone

**Estimation** : V.3 ~2h (durée scrape eBay), V.4 ~1h, P.10 ~3-4h
selon ce qu'on traite. Phase F ~2h tournage + audit.

---

## 2. État DB + serveurs

### 2.1 DB state — vérifier au démarrage

```bash
# 1. Branche
git branch --show-current        # → 'coin-richness/p3-schema'
git log --oneline -5             # → 1e50877 → ee6d2ec ou plus loin

# 2. Counts post-V.1+V.2
sqlite3 ml/state/eurio.db <<'EOF'
SELECT 'coins', COUNT(*) FROM coins;                  -- 19
SELECT 'mint_releases', COUNT(*) FROM coin_mint_releases;  -- 149
SELECT 'prices', COUNT(*) FROM mint_release_prices;   -- 391
SELECT 'quotes', COUNT(*) FROM coin_market_quotes;    -- 55 (Numista Type-level)
SELECT 'images_db', COUNT(*) FROM coin_canonical_images;   -- 38 (numista_api URLs)
SELECT 'observations', COUNT(*) FROM coin_observations;    -- 153
SELECT 'design_groups', COUNT(*) FROM design_groups;  -- 1 (eu-rome-2007)
SELECT 'variants', COUNT(*) FROM coin_variants;       -- 1 (Bleuet coloured)
SELECT 'source_registry', COUNT(*) FROM source_registry;   -- 10
SELECT 'mints', COUNT(*) FROM mints;                  -- 29
EOF

# 3. BCE images sur FS (12 commemos)
ls ml/canonical_images/*/obverse_bce.webp 2>/dev/null | wc -l   # → 12

# 4. Backups disponibles
ls -lh ml/state/eurio.db.bak-*
#   eurio.db.bak-pre-p3-2026-05-25                  29M  (avant P.3, prep)
#   eurio.db.bak-pre-wipe-2026-05-26T00-19-22Z      29M  (avant wipe effectif)

# 5. Tests P-related
cd ml && .venv/bin/python -m pytest \
  tests/test_numista_eurio_id.py tests/test_country_iso2.py \
  tests/test_storage_migration.py tests/test_wipe_referential.py \
  tests/test_refetch_numista_2eur.py tests/test_numista_transforms.py \
  tests/test_numista_writer.py tests/test_cohort_refetch.py \
  tests/test_coins_routes.py -q                            # → 192 passed
```

Si un check échoue : **arrêter et investiguer** avant V.3.

### 2.2 Serveurs admin

```bash
# Backend (port 8042)
cd /Users/musubi42/Documents/Musubi42/bizz/Eurio/ml
go-task api

# Frontend (port 5173 ou fallbacks 5174-5177)
cd /Users/musubi42/Documents/Musubi42/bizz/Eurio/admin/packages/web
pnpm dev
```

CORS configuré pour les ports 5173-5177. Si Vite prend 5178+, ajouter
au CORS dans `ml/api/server.py:60-65`.

### 2.3 Sanity check live admin

Une fois les serveurs up :
```bash
curl -s http://127.0.0.1:8042/coins/lookups/source-counts
# → {"numista":19,"bce":0,"wikipedia":0,"lmdlp":0,"ebay":0}

curl -s 'http://127.0.0.1:8042/coins?fv=2&limit=1' | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(f'total={d[\"total\"]}')"
# → total=19
```

URL admin : http://localhost:5173/coins?fv=2 (ou port assigné par Vite).

---

## 3. Ordre de lecture

1. Ce kickoff (5 min).
2. `ROADMAP-DB.md` §0 progress log + §7 V.* (10 min).
3. `findings-numista-api.md` (5 min) — comportements API + cas Bleuet
   coloured = 2 issues (BU+Proof seulement), Treaty of Rome joint-issue
   non exposé par Numista mais détecté côté pure function.
4. **Skim** : `SESSION-KICKOFF-IMPLEMENTATION.md` + `SESSION-KICKOFF-P5-P6.md`
   si tu reprends après pause longue (>1 semaine).
5. Mémoires : `feedback_sqlite_only_doctrine.md`, `feedback_ebay_pass_user_owned.md`,
   `project_coin_richness.md`.

---

## 4. V.3 — Branchement eBay (~2h)

### 4.1 Stratégie

L'utilisateur a déjà des pipelines eBay en place
(`ml/sources/ebay/cli.py` + `discover_*` + `price_aggregate.py`). Le but
de V.3 :

1. **Discovery** des annonces eBay correspondantes à la cohorte 19.
2. **Price aggregate** → row(s) `coin_market_quotes` (source=`ebay_browse`,
   condition_normalized UNC/TTB/TB).

eBay = user-owned pipeline manuel (cf. mémoire
[[feedback-ebay-pass-user-owned]]) — **ne pas auto-trigger**. Demander
à Raphaël s'il veut lancer ou si une pass eBay récente est utilisable.

### 4.2 Plan V.3

```bash
# 1. Lister les eurio_ids cohorte
sqlite3 ml/state/eurio.db "SELECT eurio_id FROM coins ORDER BY eurio_id"

# 2. Voir si discovery_searches contient déjà des hits récents pour ces 19
sqlite3 ml/state/eurio.db \
  "SELECT eurio_id, COUNT(*) FROM discovery_log dl
   JOIN coins c ON c.numista_id = dl.numista_id
   GROUP BY eurio_id"
# (À adapter selon le schéma exact discovery_log)

# 3. Demander à Raphaël : pass eBay manuelle ou utiliser data existante ?
```

### 4.3 Critères de succès V.3

- ≥ 5 coins de la cohorte 19 ont une row `coin_market_quotes` avec
  `source='ebay_browse'`
- CoinDetailPage affiche les prix eBay (le bloc "Prix de marché eBay"
  doit virer "Pas encore fetchés" pour ces coins)
- Aucune divergence majeure avec les cotes Numista (UNC ≈ Numista UNC à
  ±30%)

---

## 5. V.4 — Tour admin final + GO/NO-GO scale 524 (~1h)

### 5.1 Checklist tour visuel

Pour chaque coin de la cohorte 19 ouvert dans CoinDetailPage :

- [ ] Titre cohérent (slug post-V.1)
- [ ] Images obverse + reverse Numista visibles
- [ ] Image BCE coexistant (si applicable — 12/19)
- [ ] Description du design présente (texte Numista)
- [ ] eurio_id affiché en bas
- [ ] Prix eBay affiché (post-V.3) — bloc "Prix de marché eBay"
- [ ] Pour les 1 joint-issue (Treaty of Rome DE) : badge **DG `eu-rome-2007`**
- [ ] Pour le 1 variant (Bleuet coloured) : 3 thumbnails et description
  contient "Coloured"
- [ ] Pour le multi-mint (Bremen) : visible que 5 ateliers × 3 issue_types
  = 15 mint_releases (vérifiable via `/coins/{eurio_id}/prices` qui
  renvoie le `mint_release_level`)

Tour visuel = ouvrir les 19 pages. Estimer 2-3 min par coin.

### 5.2 Critère GO/NO-GO scale 524

**GO** si :
- Toutes les pages chargent (no console error bloquant)
- ≥ 80% des coins ont images Numista + BCE + prix eBay
- Joint-issue (Treaty of Rome) et variant (Bleuet) rendent correctement
- Renames eurio_id n'ont pas produit de slugs absurdes
- Pas de bug d'affichage majeur

**NO-GO** si :
- Un bug systémique non anticipé (ex: design_description vide partout)
- Mismatch prix Numista vs eBay > 50% sur > 50% des coins (signal
  d'arnaque dans le matching eBay)
- Renames qui cassent la sémantique (ex: 2 coins distincts → même slug)

### 5.3 Si GO → décision produit

L'utilisateur tranche : **lancer Phase F (scale 524)** maintenant ou
plus tard. Si oui, voir §6.

---

## 6. Phase F — Scale aux 524 coins eurozone (out-of-scope si NO-GO ou
report)

### 6.1 Plan

```bash
# 1. Générer la liste des 524 NIDs (cohorte étendue)
# Sources possibles :
#   - cohort_validation_19.txt + autres cohortes
#   - Numista search par pays + face_value=2
#   - 21 pays eurozone + AD/MC/SM/VA + joint-issues UE

# 2. Refetch en batch avec garde-fou quota
.venv/bin/python -m scripts.refetch_numista_2eur \
  --nids-file ml/state/cohort_524.txt --apply

# Estimation quota : ~12 calls/coin × 524 ≈ 6300 calls
# Quota restant (post-V.1 + smoke tests) : ~3 470 calls/mois
# → Phase F nécessite étalement sur 2 mois OU une 7e clé Numista
```

### 6.2 Pré-conditions Phase F

- V.4 GO validé
- Quota Numista disponible (vérifier `KeyManager.status()`)
- Plan d'audit visuel échantillonné (impossible de tour les 524) — sample
  50 coins random + cas spéciaux (joint-issues, variants).

---

## 7. P.10 — Bouclage findings (~3-4h selon priorité)

Findings capturés en session 3 à reprendre :

### 7.1 BCE pipeline n'écrit pas en DB (P10-A)

`coin_source_refs.bce_official` = 0 post-V.2 alors que 12 images BCE
existent sur FS. **Conséquence** : le filtre "BCE" liste retourne 0,
agrégation `has_bce` cassée.

**Options** :
- (a) Modifier le pipeline BCE pour écrire `coin_canonical_images` +
  `coin_source_refs` quand canonical_promote réussit (cf.
  `ml/sources/bce/pipeline.py:312` `_bce_canonical_promote_fs`).
- (b) Reconstituer côté endpoint via scan FS au load
  (`/coins/lookups/source-counts` regarde aussi les fichiers
  `_bce.webp` présents).

Option (a) plus propre (provenance first-class).

### 7.2 Fuzzy match BCE — 3 commemos non matchés (P10-B)

Treaty of Rome 2007 DE, Donatello 2016 IT, Plautus 2016 IT — le
matching slug fuzzy de `BceAdapter._match_entry` échoue. Investiguer :

- BCE expose-t-elle ces 3 coins ?
- Si oui, quel est le theme_slug BCE vs le slug coin ?
- Adapter `_slug_score` ou ajouter `MANUAL_BCE_OVERRIDES`.

### 7.3 8 fichiers Supabase data résiduels (P10-C)

Mon audit P.8b initial avait grep trop restrictif. Liste :
```
features/coins/composables/useArbitrage.ts
features/augmentation/composables/useStagedCoins.ts
features/confusion/composables/useConfusionMap.ts
features/audit/pages/AuditPage.vue
features/review/composables/useCoinsSearch.ts
features/sets/composables/useCoinSeries.ts
features/sets/composables/useCriteriaPreview.ts
features/sets/components/CuratedMembersPicker.vue
```

Plus l'auth (`router.ts`, `Login`, `AuthCallback`, `AppLayout`) qui reste
volontairement sur Supabase.

Endpoints FastAPI à ajouter probablement :
- `GET /coins/search?q=` (full-text pour useCoinsSearch)
- `GET /coin-series/` (pour useCoinSeries)
- Audit log endpoint si on veut conserver la feature
- `GET /coins/staging` pour training (ou refactor côté training pipeline)
- `GET /coins/criteria-preview` (DSL evaluator côté backend)

### 7.4 4 résidus legacy P.9 (P10-D)

Scripts kept en place car importers actifs :
- `ml/referential/refetch_numista_2eur.py` (Supabase) ←
  `ml/scripts/discover_numista_recent.py` (admin live)
- `ml/referential/import_numista.py` ← 5 importers
- `ml/scripts/migrate_canonical_schema.py` ← `referential_routes.py:941`
- `ml/scripts/bootstrap_coins_from_referential.py` ← 2 tests actifs

Refactor en parallèle de P10-C (la refonte admin Vue → FastAPI permet
de bouger ces dépendances).

### 7.5 Données i18n / aliases / observations enrichies (P10-E)

Post-V.1, les coins Numista n'ont **pas** d'i18n LLM ni d'aliases mined
(ces tables ont été wipées, V.1 ne les ré-alimente pas — c'est un flow
séparé). Re-lancer si besoin :
```bash
go-task ml:llm-coin-aliases
go-task ml:import-i18n-results
go-task ml:patch-be2017-ghent-i18n
```

---

## 8. Doctrines à respecter (rappels)

- **SQLite-only** : eurio.db source de vérité. Tout nouveau write data
  passe par les transforms purs + writer → FK source.
- **Provenance first-class** : `source` = registry ID (`numista_api`,
  `bce_official`, `ebay_browse`, ...). Multi-source = multi-row.
- **NID-keyed cohort** : `cohort_validation_19.txt` reste la clé externe.
  Les eurio_ids sont des **sorties** du refetch.
- **Pas de rollback auto** : si V.3 pète, on discute avant de remonter
  depuis backup.
- **eBay = user-owned** : ne pas auto-trigger une pass eBay (cf. mémoire
  [[feedback-ebay-pass-user-owned]]).
- **Chunk-by-chunk + audit visuel** : terminer V.3, livrer, audit, puis V.4.

---

## 9. Pièges connus (résumé findings session 3)

### 9.1 — `executescript()` commit implicite

Python `sqlite3.executescript()` commit la transaction pendante. Solution
adoptée : autocommit mode (`isolation_level=None`) + split sur `;` +
`execute()` statement par statement. Cf. `ml/scripts/wipe_referential.py`.

### 9.2 — `NumistaSlugResult.variant_finish` (pas `.finish`)

Bug capturé en P.7d : l'attribut du dataclass `NumistaSlugResult` est
`variant_finish`, pas `finish`. Fix dans `numista_transforms.coin_variant_row`.

### 9.3 — Renames eurio_id silencieux

Numista renomme régulièrement les titres → la pure function produit des
slugs différents au refetch. La cohorte 19 a vu plusieurs renames
(Bremen, Schwerin→Mecklenburg, etc.). Les anciens slugs disparaissent de
`coins` mais les références dans `training_run_classes`, `cohort_members`,
`review_queue.candidate_eurio_ids_json` deviennent orphelines. Accepté
pour cette session, rebuild au prochain training.

### 9.4 — Pipeline BCE FS-only (pas dans DB)

Cf. §7.1. Affiché côté admin via `/referential/canonical/...` qui scanne
le FS. `_serve_canonical` a un fallback chain BCE → numista → unknown
depuis P.8b.2 (`1e50877`).

### 9.5 — Vite ports fluctuants

Vite prend 5173 si dispo, sinon 5174, 5175, 5176, 5177... CORS configuré
pour les 5 ports. Si Vite prend 5178+, ajouter à `ml/api/server.py:60-65`.

### 9.6 — `api.server` import résolution dans tests pytest

Pour rebinder un Store tmp en test, `from api.server import app` **avant**
le bind override, sinon le bind initial (production) écrase le rebind.
Cf. `tests/test_coins_routes.py:fixture tmp_store`.

---

## 10. État final attendu fin de cette session

- ✅ V.3 livré : prix eBay sur ≥5 coins de la cohorte 19
- ✅ V.4 livré : tour visuel des 19 coins par Raphaël + décision GO/NO-GO
- 🟡 P.10 livré partiellement (selon temps) : P10-A et/ou P10-B priorité haute
- ❓ Phase F : lancée ou différée selon décision V.4
- ✅ ROADMAP §0 mis à jour avec Session 4
- ✅ Commit propre par chunk

---

## 11. Liens utiles

- `docs/coin-richness/ROADMAP-DB.md` — roadmap canonique
- `docs/coin-richness/findings-numista-api.md` — findings API Numista
- `docs/coin-richness/SESSION-KICKOFF-IMPLEMENTATION.md` — context phase P initial
- `docs/coin-richness/SESSION-KICKOFF-P5-P6.md` — kickoff session 3
- `ml/state/cohort_validation_19.txt` — NIDs cohorte
- Commits session 3 : `ee6d2ec` (P.5) → `1e50877` (P.8b.2)
