# V-1 — Filter fixes + downstream anomalies

> Rédigé 2026-05-18 après V-1 (e2e-pipeline-validation-kickoff §3). Tracks
> what was fixed in the scrape→filter pipeline, what remains as known
> downstream anomalies, and how the fixes were measured.

---

## 1. Bugs fixés ce chunk

### Bug B — `noise_title` rejetait les pièces normales `BU` / `FDC`

**Avant** : `NOISE_PATTERNS` (`ml/sources/ebay/filters.py`) incluait `bu\b`
au même titre que `proof`, `argent`, `or`, `colorisée`. Or "BU" = Brillant
Universel = **qualité de frappe d'une pièce de circulation standard**, pas
une variante hors-scope. Conséquence : tout listing FR mentionnant la
qualité ("Andorre 2017 2 Euro 100 Ans de l'Hymne D'Andorre BU FDC 85 000 ex")
était rejeté alors que c'était la pièce cible exacte.

**Fix** : retiré `bu\b` du regex. `be\b` (Belle Épreuve = proof) reste
rejeté à juste titre. `FDC` (Fleur De Coin) n'était pas dans le pattern,
donc rien à changer.

### Bug A — `theme_tokens` parlent anglais, eBay FR titles parlent français

**Avant** : `_theme_keywords` (`ml/sources/ebay/queries.py`) extrait des
tokens depuis le slug **anglais** de l'eurio_id
(`ad-2017-2eur-100-years-of-the-anthem-of-andorra` → `["anthem","andorra"]`).
`title_matches_theme` les matchait ensuite verbatim contre des titres
**français** ("100 ans de l'hymne d'Andorre"). Le code reconnaissait
déjà que "EBAY_FR titles are mostly in French" (queries.py:24) pour la
*query*, mais pas pour le matching theme. Conséquence : 80 %+ de
faux rejets `theme_mismatch` sur les commémos avec un thème non-trivial.

**Fix** : ajout de `THEME_TOKEN_FR_ALIASES` (dict EN→FR) + extension de
`title_matches_theme` pour matcher token EN OU alias FR. Dict cible :
toponymes (andorra→andorre, germany→allemagne…) + concepts récurrents
sur commémos 2€ (anthem→hymne, world→monde, alpine→alpin, peace→paix,
etc.). Étendre par run au fur et à mesure qu'on rencontre de nouveaux
thèmes.

### Mesure du delta (re-run sur les mêmes 2 coins, `force=true`)

| Métrique | Run pré-fix (`5c361b95`) | Run post-fix (`5a166018`) |
|---|---|---|
| `n_kept_results` | 6 | **45** |
| `n_listings` | 10 | 82 |
| `theme_mismatch` discards | 83 | 47 *(sibling commemos)* |
| `noise_title` discards | 5 | 2 |
| `n_raws_added` (MinIO `enrichment-raws`) | 0 | **72** |
| `n_crops_added` (MinIO `enrichment-crops`) | 0 | **70** |
| `n_review_enqueued` | 0 | **70** |

Le funnel post-fix sur ad-2017 : 50 summaries → 50 groups → **50 raw**
(0 theme drop sur le call) → 43 kept (filters) → 79 listings (multi-image
expansion). ad-2019 reste 50 → 3 → 2 (marché eBay réellement creux sur
cette commémo).

---

## 2. Anomalies résolues "en cascade" par le fix

### A1 — `review_queue` vide alors que des assets `needs_review` existent

**Hypothèse initiale** : bug dans `enqueue.py`.
**Réalité** : c'était un artefact du run pré-fix avec si peu d'image_assets
needs_review (4) qu'on ne pouvait pas distinguer "bug" de "rien à enqueuer".
Le run post-fix produit 70 `review_queue` rows comme attendu. → résolu.

### A2 — Crops sans `storage_path` dans le payload `/runs/<id>/listings`

**Hypothèse initiale** : write-through MinIO cassé pour les crops.
**Réalité** : le run pré-fix n'avait simplement pas eu de crops `success`
au sens qui déclenche un upload. Le run post-fix peuple
`enrichment-crops/ebay/<run_id>/` avec 70 PNG. → résolu.

---

## 3. Anomalies traitées dans un second chunk (fix V-1.b, 2026-05-18)

### A3 — `n_crops_detected` reset à 0 par persist.py *(fixé)*

**Root cause** : `dedup.upsert_source_image` listait `n_crops_detected=?`
dans son UPDATE branch et bindait la valeur à `row.n_crops_detected`.
Or `persist.py` ne calcule jamais ce champ (default 0 sur la dataclass),
donc chaque idempotent rerun du step persist réécrivait le compteur à 0,
écrasant ce que `detect_crop.py` venait de poser.

**Fix** : retirer `n_crops_detected` de l'UPDATE dans `dedup.py`. Le
step `detect_crop` reste la seule autorité pour ce champ (il fait un
UPDATE direct après chaque crop détecté). L'INSERT garde la colonne
avec son default 0, ce qui est neutre.

**Migration** : one-shot SQL pour rebackfiller les 56 rows déjà
corrompues à partir de `COUNT(*) FROM image_assets WHERE
source_image_id = …`. Toutes les rows réalignées.

### A4 — `theme_tokens` incluait le pays → acceptait sibling commemos *(fixé)*

**Root cause** : pour `ad-2017-2eur-100-years-of-the-anthem-of-andorra`,
`_theme_keywords` retenait `["anthem", "andorra"]`. Une annonce
"2 Euro Andorre 2017 Pays des Pyrénées" (autre commémo AD 2017)
matchait sur "andorra"→"andorre" via le mapping FR du fix V-1.a, et
passait à tort `title_matches_theme`. La discrimination siblings
reposait alors uniquement sur `text_signal` en aval.

**Fix** : ajout d'un set `COUNTRY_SLUG_TOKENS` (25 noms anglais des
pays eurozone + microstates + "san"/"marino" pour San Marino) skippé
en plus des `STOP_WORDS` dans `_theme_keywords`. Smoke test :
`anthem` tokens ne matchent plus le titre "Pays des Pyrénées", et
matchent toujours le titre "100 ans de l'hymne".

**Impact attendu sur la précision** : sur ad-2017, ~30-40 listings
"Pays des Pyrénées" passaient en review humain alors qu'ils n'auraient
pas dû. Ils seront désormais `theme_mismatch` au scrape suivant.

### Bug-non-bug — 23 "errors" reportées dans `error_summary`

Les "errors" comptées par le run incluent les `crop_status='zero_crops'`
(detect_crop n'a rien trouvé sur l'image). Ce n'est pas une erreur
technique, c'est un rejet implicite légitime. À renommer / scinder dans
le compteur (`n_zero_crops` vs `n_errors`) pour clarifier l'UX.

---

## 4. Tests de régression smoke

Les deux fixes ont été couverts par des smoke tests inline (cf. session
log). À convertir en pytest si la roadmap inclut une CI sur `ml/`.

Cas verts :
- `"2 EURO ANDORRE 2017 100 ANS HYMNE COMMEMORATIVE NEUVE"` + tokens
  `["anthem","andorra"]` → match ✅
- `"Andorre, 2 Euro, 100 ans de l'hymne national..."` → match ✅
- `"Coupe du Monde 2019 Ski Alpin"` + tokens `["alpine","world"]` → match ✅
- `"Andorre 2017 2 Euro BU FDC"` → accept_listing OK ✅
- `"2 Euro Andorre 2017 PROOF Belle Épreuve"` → noise_title ✅
- `"2 Euro Andorre 2017 ARGENT"` → noise_title ✅

---

## 5. Prochaine session — V-2 review queue

Le run `5a166018a19c4e50b4cc383b4342f298` a 70 reviews ouvertes dans
`review_queue` côté ebay. V-2 (kickoff §3.V-2) peut démarrer directement
dessus, sans nouveau scrape.
