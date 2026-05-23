# Numista clean refetch — Progress

> Compagnon de `numista-clean-refetch-kickoff.md`. Capture l'état du chantier
> chunk par chunk, les décisions actées et les écarts vs estimation.
> Démarré : 2026-05-16.

## État courant

| Chunk | Statut | Date |
|---|---|---|
| 0 — Alignement & migration prix | ✅ done | 2026-05-16 |
| 1 — Wipe greenfield 2€ | ✅ done | 2026-05-16 |
| 2 — Module slug pur + tests | ✅ done | 2026-05-16 |
| 3 — Bench AD | ✅ done | 2026-05-16 |
| 4 — Full refetch | ✅ done | 2026-05-16 |
| 5 — Verify + repop | ✅ done | 2026-05-16 |

---

## Décisions actées (kickoff §8bis + chunk 0)

1. **Quota** — 4 clés (`MUSUBI00..03`), budget large, on fait la totale (metadata + issues + prices + obverse + reverse).
2. **Granularité prix** — niveau **mint_release** (Option B kickoff §3.1).
3. **Schéma prix** — **table dédiée `mint_release_prices`** (cf migration §Migration prix ci-dessous).
4. **Mapping grades 7→3** — non figé. On stocke `grade_raw` (7 valeurs Numista) ET `grade_eurio` (3 valeurs Eurio, nullable). UI tranchera : Option A par défaut (UNC/TTB/TB agrégé) + drill-down Option B (7 grades bruts) pour aficionados.
5. **Storage images** — layout actuel conservé (`coin-images/{eurio_id}/*.jpg`), obverse + reverse uniquement.
6. **Variants** — auto si sibling classic même `(country, year, denom)` existe, sinon `needs_review=true`. Règle figée Phase 2.
7. **Joint-issues** — liste `JOINT_ISSUES` actuelle suffisante, pas de nouveaux depuis Erasmus 2022.
8. **Manual overrides** — démarrage à `MANUAL_NID_SLUG_OVERRIDES = {}`. Ajouts a posteriori via review queue.

---

## Pré-vol — counts 2€ avant wipe (2026-05-16)

Query : `WITH target AS (SELECT eurio_id FROM coins WHERE face_value=2.0) …`

| Entité | Count | Note |
|---|---:|---|
| `coins` 2€ | **616** | 559 commémo + 57 standard |
| `coins.needs_review=true` | 32 | héritage chunk 3e |
| `coin_variants` | 40 | finitions (coloured/hologram/…) |
| `coin_mint_releases` | 0 | table vide, conforme |
| `coin_source_refs` (total) | 2105 | dont 624 numista, 1481 autres sources |
| `coin_market_prices` | 800 | régénérables (eBay refetch après) |
| `coin_embeddings` | 7 | régénérables (training) |
| `coin_confusion_map` | 508 | régénérable post-refetch |
| `user_collections` | **0** | ✅ wipe safe |
| `set_members` | **0** | ✅ wipe safe |

**Écart vs kickoff §7.1** : la doc estimait `~2596 → 0`, valeur réelle `616 → 0`. Le `2596` du kickoff était une mauvaise lecture (probablement count `coins` global, pas filtré 2€). Le chiffre `616` est cohérent avec l'estimation du corpus 2€ Numista (~700, voir §6.2 kickoff).

### Question ouverte pré-wipe — source_refs non-numista

Les 1481 `coin_source_refs` non-numista sur des coins 2€ pointent vers d'autres sources (BCE, Wikipedia, ECB Mintage Reports, …). Deux options :

- **(a)** Wipe complet via cascade ON DELETE — on perd les bindings BCE/Wiki, à re-bootstrapper après. Cohérent avec « repartir greenfield ».
- **(b)** Wipe sélectif : DELETE coins 2€ MAIS conserver `coin_source_refs` détachés (orphelins) pour rebind après refetch. Plus complexe.

→ **À trancher avant chunk 1.** Recommandation : (a) pour la simplicité, on rebootstrappera ce qui était bootstrappé. Les sources de vérité (scripts bootstrap BCE/Wiki) sont versionnées et rejouables.

---

## Migration prix (à appliquer en chunk 0)

Fichier : `supabase/migrations/20260516_mint_release_prices.sql` (à créer).

```sql
CREATE TABLE mint_release_prices (
  id               bigserial PRIMARY KEY,
  mint_release_id  text NOT NULL REFERENCES coin_mint_releases(id) ON DELETE CASCADE,
  source           text NOT NULL,                    -- 'numista' (futur: autres)
  grade_raw        text NOT NULL,                    -- 'g'|'vg'|'f'|'vf'|'xf'|'au'|'unc'
  grade_eurio      text,                             -- 'UNC'|'TTB'|'TB' (nullable si grade_raw='g')
  price            numeric NOT NULL,
  currency         text NOT NULL DEFAULT 'EUR',
  fetched_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (mint_release_id, source, grade_raw, fetched_at)
);

CREATE INDEX idx_mint_release_prices_release ON mint_release_prices(mint_release_id);
CREATE INDEX idx_mint_release_prices_source  ON mint_release_prices(source);

COMMENT ON TABLE mint_release_prices IS
  'Prix par grade Numista (7 grades bruts) attachés à une mint_release. Le grade_eurio dérivé est agrégé en lecture côté app/admin pour la vue grand public (UNC/TTB/TB). Le grade_raw reste disponible pour drill-down aficionado.';
```

**Mapping `grade_raw` → `grade_eurio`** (calculé à l'insertion par le script ingestion, pas via trigger DB) :

| grade_raw | grade_eurio |
|---|---|
| `unc` | `UNC` |
| `au`, `xf` | `TTB` |
| `vf`, `f`, `vg` | `TB` |
| `g` | `NULL` (ignoré en lecture Eurio) |

**Note** : `coin_market_prices` reste **intacte** pour les sources agrégées (eBay velocity). `mint_release_prices` est strictement pour les cotes officielles par grade.

---

## Chunk 3 — Bench Andorre ✅ (résultats)

**Orchestrateur livré** : `ml/referential/refetch_numista_2eur.py` (paramétré par
`--country`, supporte `--all-eurozone`, `--dry-run`/`--apply`, `--skip-prices`,
`--skip-images`).

**Andorre — résultats `--apply` :**

| Métrique | Valeur |
|---|---:|
| Search hits | 33 |
| Skipped (non-2€) | 9 |
| Coins créés | **24** |
| Mint releases | **52** (~2.2 issues/Type) |
| Price rows | **103** (~7 grades × certaines issues; certains issues n'ont pas tous les grades) |
| Images obverse uploaded | 24 |
| Images reverse uploaded | 24 |
| API calls totaux | **110** (1 search + 33 details + 24 issues + 52 prices) |
| Design groups | 0 (AD n'a pas de joint-issues) |
| needs_review | 0 |

**Slugs sample (24/24 propres)** :
- `ad-2014-2eur-council-of-europe`, `ad-2014-2eur-standard-1st-type`
- `ad-2017-2eur-anthem-of-andorra`, `ad-2017-2eur-the-pyrenean-country`
- `ad-2022-2eur-currency-agreement-between-andorra-and-eu`
- `ad-2025-2eur-bearded-vulture`, `ad-2025-2eur-games-of-the-small-states-of-europe`

**Quota après bench** : 4 clés × 28 calls ≈ 0.4% du budget mensuel consommé.

### Extrapolation full corpus 2€

Hypothèse linéaire à partir d'AD : 110 calls / 24 coins.
- Cible ~600 coins (cf wipe : 616 coins 2€ avant)
- Estimation : 600 × (110/24) ≈ **2750 calls** API
- Budget 4 clés : 7200/mois → ~38% consommé
- **Confortable**. Images non comptées (CDN direct, hors quota).

### Bugs corrigés pendant chunk 3
1. `_VALUE_PREFIX_RX` case-sensitive — fixé en chunk 2
2. Numista API requiert `q="2 euros"` — ajouté
3. `issuer` param ≠ ISO2 — utilise des slugs FR/EN curated (`andorre`, `belgium`, `bulgarie`...); map en dur dans `NUMISTA_ISSUER_CODE`
4. `/issues` endpoint retourne `list` direct, pas `{"issues": [...]}` — handlé
5. Issue field est `comment` (singulier), pas `comments` — utilisé pour heuristic `_detect_issue_type` (CIRC par défaut, BU si "coincard"/"BU", PROOF si "proof"/"BE")

---

## Chunk 4 — Full refetch ✅ (résultats)

**Stratégie exécutée :** 1 passe complète `--all-eurozone` (sans AD déjà fait au chunk 3), puis 2 corrections de bugs Numista, suivies de re-runs ciblés DE et LT.

**Résultats finaux** (snapshot 2026-05-16 ~02:50 UTC) :

| Métrique | V1 (avant wipe) | V2 (refetch) | Δ |
|---|---:|---:|---:|
| coins 2€ | 616 | **656** | +40 |
| Pays distincts | 23 | **25** | +2 (BG, LT) |
| Commémoratives | 559 | 600 | +41 |
| Standard | 57 | 56 | -1 |
| coin_variants | 40 | 0 | -40 (variants tous flaggés needs_review) |
| coin_mint_releases | 0 | **3308** | nouveau |
| mint_release_prices | 0 | **7000** | nouveau (7 grades Numista bruts) |
| Joint-issues actifs | (legacy) | 5 / 87 membres | rome 13 / emu 16 / euro-cash 18 / eu-flag 21 / erasmus 19 |
| Images uploadées | (n/a) | ~1310 obverse + 1310 reverse | Supabase Storage WebP |

**Quota Numista consommé** : ~6196 / 7200 mensuel (86%). Remaining ~500 calls/key.

### Bugs trouvés + corrigés pendant chunk 4

1. **`issuer=germany`** (V1) → résolvait l'historique allemand (Pomeranie, Saxe...). Code correct = `allemagne` (FR), pas l'anglais.
2. **`issuer=lithuania`** → 400 Bad Request (placeholder `lithuania_section`). Code correct = `lituanie`.
3. **`_extract_country_iso2`** acceptait `issuer.name="Germany"` mais pas `"Germany, Federal Republic of"`. Refacto : ajout de `_NUMISTA_CODE_TO_ISO2` (map slug → ISO2) en source primaire ; name_map devient fallback.

### needs_review post-refetch

- **28 variants** (coloured/hologram/gilded/pattern/mule) détectés mais non encore bindés à un parent → à traiter en chunk 6 (UI review) selon la règle « auto si sibling classic même `(country, year, denom)` existe, sinon needs_review ».
- 1153 skipped out-of-scope (résultats search non-2€-EUR, normalement filtrés).
- 0 coin avec `needs_review=true` côté coins table (la queue chunk 3e est intacte mais vide pour la 2€).

### Coverage joint-issues

| Theme | Year | Members observed | Members expected (~) |
|---|---:|---:|---:|
| Rome | 2007 | 13 | 13 (eurozone members 2007) |
| EMU | 2009 | 16 | 16 |
| Euro Cash | 2012 | 18 | 17–18 |
| EU Flag | 2015 | 21 | 19+ |
| Erasmus | 2022 | 19 | 19 |

Tous dans la marge attendue (Numista catalog reflète occasionnellement des variantes nationales en plus).

### Bilan de coût Numista

Estimation initiale : 2750 calls. Réel : **6196 calls** (2.25× plus). Cause : Numista a beaucoup plus de Types 2€ (variants, BU coincards séparés, sub-types) que les 616 V1. Le filtre `face_value=2 EUR` rejette 1153 résultats search (54% des hits search). Budget tient confortablement.

---

## Chunk 5 — Verify + repop ✅ (résultats)

**Verifier livré** : `ml/referential/verify_refetch.py` — 8 checks d'invariants.

### Résultats verify

| # | Check | Résultat |
|---|---|---|
| 1 | Unicité (country, year, slug) | ✅ 656 coins, 0 duplicates |
| 2 | Couverture eurozone | ✅ 25/25 pays |
| 3 | coin_source_refs numista | ✅ 656/656 (100%) |
| 4 | mint_release_prices coverage | ✅ 648/656 (98.8%) — bien au-dessus du seuil 80% |
| 5 | mint_releases | ✅ 600 commémos ont ≥ 1 release |
| 6 | Images HTTP 200 (sample 20) | ✅ 40/40 |
| 7 | needs_review=true | ✅ 0 |
| 8 | Determinism (sample 50) | ✅ 50/50 re-derive identiques |

**0 failures, 0 warnings.**

### Repop

- **Android snapshot** : régénéré via `go-task android:snapshot` — `app-android/src/main/assets/catalog_snapshot.json` passe de 1148 KB → 1315 KB (+15%).
- **Bug repéré + corrigé** : refetch écrivait `coins.images` en LIST (mid-shape), snapshot attend DICT (current-shape `{role: [{source, url}, ...]}`). SQL migration appliquée sur les 656 rows + orchestrateur corrigé pour la prochaine fois.
- **ml:bootstrap-coins** : side-quest non-critique. Lit `eurio_referential.json` (scrape Wikipedia/Numista) plutôt que Supabase — désynchronisé du refetch. Nécessite une étape « export Supabase coins → JSON » qui n'est pas trackée comme task aujourd'hui. À traiter séparément si la pipeline ML SQLite en a besoin.
- **eBay relance** : explicitement déféré (Phase 5 séparée).

---

## Livrables chunk 0 ✅

- [x] Décisions §8bis du kickoff actées
- [x] Pré-vol counts collectés
- [x] Schéma `mint_release_prices` rédigé
- [x] Migration `supabase/migrations/20260516_mint_release_prices.sql` créée et **appliquée** (table vide, 8 colonnes, 2 index, CHECK constraints)
- [x] Source_refs non-numista : **wipe cascade complet** (option a) — rebootstrap après refetch
- [x] Migration appliquée maintenant (avant wipe)

→ **Chunk 0 done. Attente GO utilisateur avant chunk 1 (wipe destructif).**
