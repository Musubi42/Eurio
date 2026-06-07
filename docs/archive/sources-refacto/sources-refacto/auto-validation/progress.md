# Progress — auto-validation Dino

> Journal des chunks livrés, ce qui a marché vs ce qu'on avait théorisé,
> les ajustements en cours de route, les observations sur les vrais
> chiffres mesurés. Mis à jour à chaque chunk livré.

## État global

| Chunk | Statut | Date |
|---|---|---|
| 1. Foundations (module + ancres) | ✅ livré | 2026-05-04 |
| 2. Pipeline + backfill + API | ✅ livré | 2026-05-04 |
| 3. Front Dino dans le drawer review | ✅ livré | 2026-05-04 |
| 3.5. Country-aware re-rank (dual band) | ✅ livré | 2026-05-05 |
| **0. Visibilité du stream (préalable signal texte)** | ✅ livré | 2026-05-05 |
| **4. Extracteur `ListingTextSignals`** | ✅ livré | 2026-05-05 |
| **5. Étape pipeline `text_signal_extract` (sans décision)** | ✅ livré | 2026-05-05 |
| **6.a + 6.b Comparateur `vs_target` (pur) + persistance verdict + 6.d API** | ✅ livré | 2026-05-05 |
| **6.c Filtre dur `text_contradict_*` → `discarded_listings` + `route_decision='rejected_text'`** | ✅ livré | 2026-05-05 |
| **7. Panel "Texte" dans le drawer review (single + lot compact)** | ✅ livré | 2026-05-05 |
| 7. Panel "Texte" dans drawer review | Plus tard | — |
| 8. Combinatoire Dino × texte → auto-accept | Plus tard | — |
| 9. Rollback tooling page Coin | Plus tard | — |

### Pivot 2026-05-05 (post-chunk 3)

Le découpage initial chaînait directement vers "auto-accept" puis "signal
texte". Brainstorm avec Raphaël après audit visuel chunk 3 → recadrage :

1. **Le signal texte vient AVANT l'auto-accept** : sans deuxième signal
   indépendant, l'auto-accept retomberait sur du Dino-only que les chiffres
   chunk 2 (R@1=10 %) ont disqualifié, et que P1 du `vision.md` exclut.
2. **Avant d'ajouter un filtre, rendre visibles ceux qui existent**. Le
   pipeline a déjà 5 raisons de rejet en DB (`accept_listing` →
   `discarded_listings`) + un theme-drop silencieux, et le front n'expose
   rien de tout ça. Sinon on empile des boîtes noires.

D'où l'insertion d'un chunk 0 hors-séquence : visibilité du stream complet
(N0 brut Browse → N1 post-groups → N2 post-theme → N3 post-accept_listing →
review), avec endpoint `/discarded` et panel front. Périmètre détaillé dans
`vision.md` §"Découpage du chantier". Une fois livré, on attaque l'extracteur
`ListingTextSignals` (chunk 4) sur des données dont on comprend la
provenance.

## Chunk 1 — Foundations

### Livré

- Module `ml/foundation/` : `encoder.py`, `anchors.py`, `matcher.py`, `__init__.py`
- Refacto : `ml/eval/confusion_map.py` et `ml/api/distance_logic.py` consomment
  désormais `foundation.encoder` (single source of truth pour DINOv2)
- Migration schema : table `image_asset_dino_predictions` (PK composée
  `(asset_id, encoder_version, anchors_kind)`)
- Helpers store.py : `DinoPredictionRow`, `upsert_dino_predictions`,
  `get_dino_prediction`, `list_dino_predictions_for_asset`
- Script `ml/scripts/build_dino_anchors.py` + entrée Taskfile
  `ml:dino-anchors:build`
- Tests `ml/tests/test_foundation.py` (13/13 verts)

### Ancres construites

- 466 pièces 2€ commémo en DB → 376 ancres encodées (90 pièces sans
  `obverse.jpg` sur disque)
- Encoder `dinov2-vits14` (DINOv2 ViT-S/14, dim 384, sortie L2-normalisée)
- `ml/state/foundation_anchors_2eur_commemo.npz` ≈ 580 KB
- 17.7s de wall-time pour le bootstrap initial sur MPS (M4)

### Sanity checks au moment du livré

- L'obverse `ad-2014-2eur-20-years-in-the-council-of-europe` ré-encodée
  → top1 elle-même à `sim=1.0000` ✅
- Top2 dans le bank auto-similarity = `0.897` (cohérent avec la mémoire
  `feedback_dino_thresholds` : Dino inflate sur euros par construction)
- Tests existants : 48/49 verts (le 1 qui échoue était déjà cassé sur main,
  indépendant du chantier)

## Chunk 2 — Pipeline + backfill + API

### Livré

- Étape `auto_validate_dino` dans la pipeline 6 (devient 7) — fichier
  `ml/sources/_base/steps/auto_validate.py`
- Branchement orchestrateur entre `resolve` et `enqueue` ;
  `_VALID_STEPS` mis à jour
- Idempotence : skip si row existe déjà pour la même `(encoder_version,
  anchors_kind)`. `--force` recompute.
- Fallback gracieux : si la bank `.npz` est absente, on log une warning
  et on saute (ne casse pas le run)
- Script standalone `ml/scripts/backfill_dino_predictions.py` + entrée
  Taskfile `ml:dino-predictions:backfill`
- Endpoint `GET /review-queue/asset/{asset_id}/dino-suggestions` qui
  retourne le top-K enrichi avec metadata coin (country, theme, year,
  obverse_url) — 200 si présent, 404 sinon
- Modèles Pydantic `DinoSuggestion` + `DinoSuggestionsResponse`

### Audit visuel (backfill réel)

Backfill complet sur les 524 crops 2€ commémo en `needs_review` :

```
Predicted:          519
Skipped (existing): 5    (smoke test précédent)
Skipped (oos):      0
Errors:             0
Total time:         9.8s
Per-asset average:  18.9ms
```

→ **18.9ms par crop** sur MPS, pour DINOv2 + matcher + upsert SQL. C'est
imperceptible au sein du run de scrape (quelques secondes pour 50-100
crops typique d'un run eBay).

### Endpoint test

`GET /review-queue/asset/<id>/dino-suggestions` répond en JSON enrichi
avec `country`, `country_name`, `theme`, `year`, `obverse_url`
(pointant `/images/<numista_id>/source` qui est déjà servi par
`api/server.py`). 404 propre avec message explicatif quand l'asset n'a
pas de prédiction.

### Observations vs ce qu'on théorisait

**Théorie (vision + kickoff)** :
- DINOv2 zero-shot sur euros donne des sim tassées (mémoire
  `feedback_dino_thresholds`)
- Les top-K seront utiles comme suggestions pour l'humain, même si le
  top1 absolu est rarement la vérité
- Auto-accept naïf top1==target serait inefficace en V1

**Mesuré** sur les 524 crops réels :

| Métrique | Valeur |
|---|---|
| top1_sim p10 | 0.565 |
| top1_sim p25 | 0.678 |
| top1_sim p50 | 0.753 |
| top1_sim p75 | 0.797 |
| top1_sim p90 | 0.834 |
| spread top1−top2 p10 | 0.002 |
| spread p25 | 0.004 |
| spread p50 | **0.011** |
| spread p75 | 0.023 |
| spread p90 | 0.041 |
| **R@1** (top1 == target_eurio_id) | **10.1 %** |
| **R@5** (target ∈ top-5) | **20.6 %** |
| Target hors top-5 | **79.4 %** |

### Ce qui a confirmé la théorie

1. **Inflation Dino sur euros confirmée** : la médiane top1 est à 0.753
   avec un spread médian de 0.011 — toutes les commémo se ressemblent
   visuellement pour Dino zero-shot.
2. **Auto-accept top1==target en V1 = inefficace** : 10 % seulement.
   Décision V1 (no auto-accept) confirmée chiffres en main.
3. **Drift studio→eBay massif** : aucune sim ne dépasse 0.85 en p90,
   alors qu'entre obverses Numista entre elles le p25 était à 0.81 —
   le crop in-the-wild est un domaine vraiment différent.

### Surprises / désaccords avec la théorie

1. **R@5 à 20.6 %** est plus bas qu'espéré. On pensait que les top-K
   resteraient "du même genre" même si le top1 strict est faux. Mesure :
   80 % des targets sont **carrément hors top-5**. À creuser au chunk 3
   quand on regardera les cas en review : combien sont des reverse,
   combien sont des crops mauvais (capsule dominante), combien sont des
   "vraies pièces commémo" que Dino confond avec d'autres commémo.

2. **Performance bien meilleure que prévu** : 18.9ms/asset (estimé 50-100ms
   dans le kickoff). MPS sur M4 + lazy singleton = bien plus rapide.
   Conséquence : pas besoin de batcher ou paralléliser, le naïf marche.

3. **Spread médian 0.011** est encore plus tassé qu'attendu. Conséquence
   sur le futur auto-accept : on **ne peut pas** se baser sur un seuil
   absolu de spread (≥ 0.05 par exemple) sans rejeter quasiment tout. Il
   faudra des seuils relatifs (percentile-based) ou multi-signaux (texte
   + Dino qui convergent).

### Ajustements en cours de route

- **`current_step`** dans `source_runs` : pas de CHECK contraint mais
  `_VALID_STEPS` dans `run_logger.py` était hard-coded sur 6 valeurs.
  Tests cassés, ajout de `auto_validate` dans la liste, fix.
- **Singletons module-level** pour encoder + bank cache : 1er asset =
  ~200ms (load), suivants = ~20ms. Sans singleton on aurait 2s par
  call. À garder en tête si quelqu'un veut paralléliser plus tard
  (multi-process à éviter ; multi-thread OK avec ce pattern).
- **Fallback du `_flush`** : 2 chemins (Store helper si dispo, sinon
  SQL direct sur la connexion). Permet l'usage à la fois dans le
  pipeline (avec Store), dans le backfill (avec Store), et dans des
  tests qui n'ont qu'une raw connection.

### Tests

- 61/62 verts après chunk 2 — seul `test_lot_detail_detections_computed_from_real_raw`
  échoue (déjà cassé sur `main` avant tout ce chantier, indépendant)
- Idempotence vérifiée : 2e run du backfill avec mêmes assets → 0 predicted, 5 existing
- Endpoint testé via FastAPI TestClient → 200 + JSON cohérent et 404 propre

## Chunk 3 — Front review

### Livré

- Endpoint additionnel `GET /review-queue/{review_id}/dino-suggestions`
  qui résout `review_id → asset_id` en interne (le drawer single ne
  manipule que le `review_id`)
- Composable `useDinoSuggestions.ts` :
  - `fetchDinoSuggestionsByReviewId` / `fetchDinoSuggestionsByAssetId`
  - 404 traité comme "no suggestions" silencieux (Dino est aide,
    pas requis)
  - Helpers visuels `simTier`, `simTierColor`, `spreadLabel` —
    **percentile-relatif au top1 de la requête courante**, pas seuils
    absolus (cf. la mémoire `feedback_dino_thresholds` et les chiffres
    chunk 2 : sims tassées 0.6–0.85)
- Composant `DinoSuggestions.vue` avec deux variantes :
  - `standard` — panel droit du drawer single (5 cards verticales avec
    thumb obverse, sim, country/year/theme, bouton "Sélec.")
  - `compact` — strip horizontal sous chaque crop dans le drawer lot
    (vignettes 5 thumbs + sim courte, click = assigne directement)
- Plug `SingleReviewView.vue` : composant inséré entre `CandidateRow`
  et la card "sélecteur libre". Émet `select` → handler `onDinoSelect`
  qui réutilise le flow `freeSearchCandidate` existant
- Plug `LotDetailDrawer.vue` : composant compact entre les top
  candidates et les action buttons de chaque crop. Émet `select` →
  handler `assignFromDino` qui appelle `assignToCandidate` du flow
  existant
- Tokens.css respectés partout (var(--surface), var(--ink-*),
  var(--success), var(--gold-600), var(--ink-400), var(--indigo-700))

### Audit visuel

- Endpoint `GET /review-queue/{review_id}/dino-suggestions` testé via
  TestClient → 200 avec top-K enrichi (country_name, theme, obverse_url)
- Endpoint `GET /review-queue/asset/{asset_id}/dino-suggestions` testé
  au chunk 2, toujours OK
- Typecheck : aucune erreur dans les fichiers touchés (les erreurs vues
  dans `pnpm typecheck` sont 100 % préexistantes dans `audit/`, `lab/`,
  `sets/`, indépendantes)

### Choix de design

**Coloration percentile-relative** : on ne pouvait pas se baser sur des
seuils absolus (top1 médian = 0.753, spread médian = 0.011 d'après
chunk 2). Le composable `simTier(sim, top1)` colore en vert/gold/grey
selon le **ratio à top1 de la même requête** :
- ≥ 95 % de top1 → "top" (vert)
- ≥ 85 % de top1 → "mid" (gold)
- sinon → "low" (grey)

Idem pour le `spreadLabel` qui utilise des seuils empiriques choisis
sur la distribution mesurée chunk 2 :
- ≥ 0.05 → "net"
- ≥ 0.02 → "modéré"
- sinon → "tassé"

Ces labels guident l'œil de Raphaël sans rien décider.

**Pas de double-fetch** : le composant fetch lui-même via watcher sur
`reviewId|assetId`. Pas de prop drilling. Le drawer single change de
review_id → composant re-fetch automatiquement.

**Variant compact pour les lots** : 1 row par crop dans le drawer lot →
l'affichage standard prendrait trop d'espace. Le compact tient en
~30px de hauteur avec 5 thumbs cliquables.

### Surprises / ajustements

- Aucune. Le pattern visuel `var(--*)` direct dans `:style` des autres
  composants review (`CandidateRow.vue`) a été repris tel quel — pas
  besoin de Tailwind classes pour les tons.
- `DinoSuggestion` → pseudo-`ReviewCandidate` côté drawer single :
  réutilise le flow "freeSearchCandidate" existant plutôt que d'inventer
  un 3e mode de focus. Une seule UX validation, deux sources d'entrée
  (sélecteur libre F + suggestions Dino).

### Audit demandé à Raphaël

```bash
# Lancer l'API + dev server admin et observer
go-task ml:api &  # ou la commande équivalente du repo
cd admin/packages/web && pnpm dev

# Naviguer vers /review (mode single) → ouvrir un crop → vérifier que
# le panel "Suggestions Dino" affiche les top-5 avec thumbs Numista,
# que le spread est colorisé, que cliquer "Sélec." pré-remplit le
# candidat focus comme un sélecteur libre.

# Naviguer vers /review (mode lot) → ouvrir un lot → sous chaque crop,
# vérifier le strip compact "Dino" avec 5 mini-thumbs, cliquer une
# vignette → assigne ce crop à l'eurio_id.
```

### Observations attendues à reporter (chunk 4 input)

Sur quelques semaines de review avec ces annotations sous les yeux :
- Combien de fois le target final (humain validé) figure dans le top-5
  Dino, et à quel rang ?
- Combien de fois le top1 Dino est immédiatement validé sans hésitation
  vs corrigé ?
- Quel pattern sim/spread se dégage pour les "bonnes suggestions" vs
  les "à rejeter" ?
- Sur les revers, est-ce que le pattern "top1_sim bas + spread très
  faible" est consistant (preuve qu'on peut détecter les revers
  passivement) ?

Au bout de ~200 reviews avec annotations, on calibrera les seuils
auto-accept (chunk 4) à partir de la table `image_asset_dino_predictions`
joinée à `review_queue.decided_eurio_id`.

## Chunk 3.5 — Country-aware re-rank

### Pourquoi ce chunk

En auditant les chiffres du chunk 2 sur le terrain (drawer review en
prod), Raphaël a remarqué que la cible humaine était **souvent dans le
top 3-5** plutôt qu'en top 1, et que les listings eBay sont à ~80 % du
bon pays. L'idée : le `target_eurio_id` qu'on a déjà dans
`source_images` (issu de la query eBay parente) porte un signal pays
ISO2 qu'on peut utiliser pour **filtrer la bank avant le re-rank**, à
coût quasi-nul (mask numpy, pas de re-encoding).

### Mesure d'impact (avant code)

Sur les 524 crops déjà backfillés au chunk 2, en simulant un re-rank
country-restreint contre les 376 ancres :

| Métrique | Global (376 ancres) | Country-restreint (~20 ancres) |
|---|---|---|
| R@1 | 10.1 % | **34.0 %** (×3.4) |
| R@5 | 20.6 % | **65.6 %** (×3.2) |

75 des 178 hits country-R@1 étaient hors top-5 global — récupérés
uniquement grâce au filtre pays. Distribution des ancres par pays :
médiane 20, p25 11, p75 20 (24 pays au total).

Sims top1_country : 0.739 médiane quand right vs 0.679 quand wrong —
recouvrement large, **donc pas de seuil auto-accept exploitable seul**.
Le gain est UX (1 clic au lieu de 3), pas pipeline.

### Livré

- **Schema** : 8 nouvelles colonnes nullables sur
  `image_asset_dino_predictions` (`target_country`,
  `country_anchors_count`, `top_k_country_json`,
  `top1_country_eurio_id`, `top1_country_sim`, `top2_country_eurio_id`,
  `top2_country_sim`, `country_spread`) + index
  `idx_dino_pred_top1_country`. Migration via `Store._ensure_column`,
  schema.sql en miroir pour les bases neuves.
- **Foundation** : nouvelle fonction `top_k_match_country(query_vec,
  bank, target_country=, top_k=)` qui masque la bank par préfixe ISO2
  des `eurio_ids`. Retour `[]` si aucune ancre du pays cible.
- **Auto-validate step** : `_predict_one` consomme un
  `target_country` optionnel, calcule la deuxième bande et persiste
  les deux. Le pipeline orchestrateur dérive le pays de
  `source_images.target_eurio_id[:2].lower()`. NULL → fallback
  silencieux à la bande globale uniquement.
- **API** : `DinoSuggestionsResponse` étendu avec `target_country`,
  `country_anchors_count`, `country_spread`, `top1_country_*`,
  `top_k_country` (enrichi exactement comme `top_k`). Endpoints
  inchangés.
- **Front** : `useDinoSuggestions.ts` typé pour la nouvelle réponse
  + `DinoSuggestions.vue` rend deux bandes empilées. Bande pays en
  premier (bordure indigo, label "🌐 Pays cible {ISO2} · N ancres"),
  bande globale ensuite avec un titre "fallback si la query n'a pas
  le bon pays" (3 cards seulement quand la bande pays est présente,
  les 5 quand elle ne l'est pas). Coloration percentile-relative
  recalculée par bande (top1_country pour la bande pays, top1 pour la
  bande globale). Variant compact (drawer lot) : si country dispo, on
  remplace les vignettes globales par les country avec une bordure
  indigo + un petit globe à côté du `Dino`.

### Audit visuel

- **Backfill --force sur 524 crops** : 9.8 s, 18.8 ms/asset (identique
  au chunk 2 — le mask country ajoute ~0 ms vs le top-K global).
- **Vérification base** : `R@1 country = 178 / 524 = 34.0 %`,
  identique au chiffre simulé. Le code persiste exactement ce que la
  mesure prédit.
- **Endpoint smoke** : `GET /review-queue/asset/{asset_id}/dino-suggestions`
  répond 200 avec `target_country`, `top1_country_eurio_id`,
  `top_k_country` enrichi (5 candidats AD pour un crop AD).
- **Cas de Raphaël** (`andorre 2014 Fleur de coin…`) : top1 global =
  `pt-2017` (0.761), **top1 country = `ad-2014-2eur-20-years-…`
  (0.752)** ✅ — la bonne réponse remonte exactement comme prévu.
- **Foundation tests** : 7 nouveaux tests sur `top_k_match_country`
  (ISO2 case-insensitive, retour vide si pays absent, dim mismatch,
  clamp à n_country, blank target). 20/20 verts.

### Surprises / ajustements

- **Aucune régression** : l'absence du signal pays (e.g. mock source,
  test sans `target_eurio_id`) tombe gracieusement sur l'ancien
  comportement single-band. Tous les tests préexistants
  (`test_orchestrator`, `test_ebay_adapter`, `test_foundation` chunk
  1-2) restent verts.
- **schema.sql vs ensure_column** : la première tentative gardait
  `CREATE INDEX … (top1_country_eurio_id)` dans le schema.sql ; sur
  une base existante, `executescript` exécute le CREATE INDEX **avant**
  que `_ensure_column` n'ait ajouté la colonne, donc crash. Corrigé
  en sortant ce seul index du schema.sql (créé par `_bootstrap` après
  les ALTERs). Les autres `CREATE INDEX … IF NOT EXISTS` sur des
  colonnes pré-existantes restent dans schema.sql comme avant.
- **Front compact** : initialement prévu pour afficher dual band en
  compact aussi, j'ai préféré remplacer les vignettes globales par
  les country quand dispo (bordure indigo + icône). Plus lisible dans
  le strip horizontal du drawer lot.

### Limites connues (à acter pour chunk 4)

1. **Plafond ~80 % R@5**. La query eBay donne le bon pays ~80 % du
   temps (estimation Raphaël). Donc le R@5 country-aware (65.6 %)
   est déjà à 82 % du plafond atteignable avec ce signal seul. Marge
   restante = revers, capsules, drift query — pas un problème Dino.
2. **Pas d'auto-accept même avec country**. Distributions sim
   right/wrong se recouvrent (médianes 0.739 / 0.679). Reporter
   l'auto-accept à la convergence multi-signal (Dino country + texte
   OCR pays + spread).
3. **`target_eurio_id` faux**. Quand le seller a listé une pièce du
   mauvais pays, la bande country se trompe avec une fausse
   confiance. Mitigation : on garde la bande globale en fallback dans
   le drawer ; l'humain peut basculer.

### Snippets utiles

```sql
-- R@1 / R@5 country-aware
SELECT
  count(*) AS total,
  sum(CASE WHEN p.top1_eurio_id = si.target_eurio_id THEN 1 ELSE 0 END) AS r1_global,
  sum(CASE WHEN p.top1_country_eurio_id = si.target_eurio_id THEN 1 ELSE 0 END) AS r1_country
FROM image_asset_dino_predictions p
JOIN image_assets ia ON ia.id = p.asset_id
JOIN source_images si ON si.id = ia.source_image_id
WHERE si.target_eurio_id IS NOT NULL;

-- Distribution du gap (right/wrong) sur top1_country_sim
SELECT
  CASE WHEN p.top1_country_eurio_id = si.target_eurio_id THEN 'right' ELSE 'wrong' END AS verdict,
  round(p.top1_country_sim, 2) AS bucket,
  count(*) AS n
FROM image_asset_dino_predictions p
JOIN image_assets ia ON ia.id = p.asset_id
JOIN source_images si ON si.id = ia.source_image_id
WHERE si.target_eurio_id IS NOT NULL AND p.top1_country_sim IS NOT NULL
GROUP BY verdict, bucket ORDER BY verdict, bucket;
```

## Hypothèses de pivot pour les chunks à venir

À garder à l'esprit selon ce qui sortira de l'audit chunk 3 :

- **Si R@5 monte largement quand l'humain re-crop manuellement** : la
  pipeline `detect_crop` est le goulet, pas Dino. À adresser via piste 5
  (retrain YOLO rim-tight) avant d'investir plus dans Dino.
- **Si beaucoup de targets hors top-5 sont des reverse** : ajouter un
  classifier obverse/reverse en amont (idée déjà dans
  `auto-validator.md` §Failure modes). Pourrait être une simple sortie
  Dino (top1 reverse-sim vs top1 obverse-sim).
- **Si Dino confond systématiquement des commémoratives "communes"**
  (10 ans euro 2009, etc., même design national mais pays différent) :
  exclure ce sous-set du scope V1 ou ajouter signal OCR léger sur le
  nom du pays.
- **Si les sims absolues ne se calibrent pas même avec un set humain** :
  fine-tune Dino sur euros (P1 dans `coin-similarity-encoder-followup.md`).
  Investissement plus lourd, à n'engager qu'après preuve de besoin.

## Snippets utiles

```bash
# (Re)build des ancres
go-task ml:dino-anchors:build              # cache hit OK
go-task ml:dino-anchors:build -- --force   # recompute

# Tests fondation
go-task ml:dino-anchors:test

# Backfill prédictions
go-task ml:dino-predictions:backfill                     # ts crops 2€ commémo
go-task ml:dino-predictions:backfill -- --limit 10       # smoke
go-task ml:dino-predictions:backfill -- --force          # recompute existants

# Distribution rapide après backfill
sqlite3 ml/state/training.db "
  SELECT round(top1_sim, 2) AS bucket, count(*)
    FROM image_asset_dino_predictions
   GROUP BY round(top1_sim, 2) ORDER BY bucket;"

# R@1 / R@5 quick check
sqlite3 ml/state/training.db "
  SELECT
    sum(CASE WHEN p.top1_eurio_id = si.target_eurio_id THEN 1 ELSE 0 END) AS r1,
    count(*) AS total
  FROM image_asset_dino_predictions p
  JOIN image_assets ia ON ia.id = p.asset_id
  JOIN source_images si ON si.id = ia.source_image_id;"
```

## Chunk 0 — Visibilité du stream sources → review

Préalable au signal texte. Pourquoi on a inséré ce chunk hors-séquence :
cf. `vision.md` §"Pourquoi un chunk 0 hors-séquence" et la section "Pivot
2026-05-05" plus haut. En une phrase : avant d'ajouter un nouveau filtre,
on rend visibles ceux qui existent.

### Livré

- **Schema** : 2 colonnes additives sur `discovery_searches` —
  `n_summaries` (N0) et `n_after_groups` (N1). `n_raw_results` redéfini
  comme N2 (post theme-token drop) ; `n_kept_results` reste N3 (post
  `accept_listing`). Migration via `Store._ensure_column` ; schema.sql
  miroir pour bases neuves. Pas de breaking change : anciennes rows
  voient `n_summaries / n_after_groups = NULL`, le front retombe sur
  `n_raw_results`.
- **`DiscoverySearchRecord`** étendu avec `n_summaries`, `n_after_groups`.
  `record_discovery_search` écrit les nouvelles colonnes.
- **eBay adapter** : refacto `_search_and_expand` → retourne
  `SearchExpandResult(rows, n_summaries, n_after_groups, theme_dropped)`
  au lieu d'une simple liste. `discover()` consomme ce dataclass et
  persiste les `theme_dropped` via `record_discarded` avec
  `reason='theme_mismatch'` (auparavant silencieux). Compteurs
  `n_summaries` / `n_after_groups` propagés au `DiscoverySearchRecord`.
- **API** : `DiscoverySearchItem` enrichi avec `n_summaries` /
  `n_after_groups`. **Nouvel endpoint** `GET
  /sources/{id}/runs/{run_id}/discarded` qui retourne les
  `discarded_listings` du run avec `reason`, `title`, `item_id`,
  `item_web_url`, `price`, `currency`, `raw_payload`. Filtres
  `?eurio_id=` et `?reason=`. Inclut une ventilation `by_reason` (count
  par raison) pour piloter les chips du front.
- **Front composables** : `useRunSearches.ts` étend `DiscoverySearchItem`
  avec les nouveaux compteurs. **Nouveau** `useRunDiscarded.ts` avec
  `fetchRunDiscarded`, types, helpers `reasonTone()` / `reasonLabel()`
  (mappings tons + libellés FR par raison de rejet).
- **Front page** `SourceRunListingsPage.vue` :
  - Panel "Discovery searches" affiche maintenant la chaîne complète
    `N0 summaries → +groups N1 → −theme N2 → −accept N3 kept`, en
    sommary global et par row.
  - **Nouveau panel collapsible "Listings rejetés pré-ingestion"** avec
    chips counter par raison cliquables (filtre actif), drill-down par
    listing (title, eurio_id ciblé, prix, lien eBay, payload JSON
    décompacté). Les chips sont colorisées par tonalité — `theme_mismatch`
    en gold (rejet "souple", listing potentiellement re-attribuable),
    `noise_title` en rouge (hors-scope), `year_mismatch` /
    `below_face` / `above_extreme` en warning, le reste en `ink-500`.

### Couvert / pas couvert

Couvert :
- 6 raisons de `accept_listing` (`noise_title`, `year_mismatch`, `non_eur`,
  `no_price`, `below_face`, `above_extreme`)
- Theme drop (`theme_mismatch`) — auparavant silencieux, désormais
  persisté et exposé.
- Funnel ventilé N0 / N1 / N2 / N3.

Pas couvert (volontairement, hors scope chunk 0) :
- Aucun nouveau filtre. Le signal texte arrive au chunk 4 (extracteur)
  puis 5 (étape pipeline) puis 6 (filtre `text_contradict_*`).
- Pas de fetch de la `description` eBay : les rejets s'appuient toujours
  uniquement sur le titre + aspects + prix/devise.
- Pas de modification de `accept_listing` ni du seuil `expected_year`.

### Audit visuel demandé à Raphaël

```bash
# 1. Re-trigger un run eBay (ou consulter un run existant)
go-task ml:api &  # ou la commande équivalente
cd admin/packages/web && pnpm dev

# 2. Naviguer vers /sources/ebay/runs/<run_id>/listings
#    Vérifier le panel "Discovery searches" : la chaîne
#    `N0 summaries → +groups N1 → −theme N2 → kept` apparaît dans le
#    summary header et dans chaque row de search.
#
# 3. Vérifier le panel "Listings rejetés pré-ingestion" :
#    - chips counter par raison (cliquables → filtre)
#    - expand par row → voir titre, eurio_id ciblé, lien eBay, payload
#    - filtre actif visible avec libellé FR de la raison
```

### Tests

- 41/41 verts sur `tests/test_ebay_adapter.py` + `tests/test_orchestrator.py`
- 57/57 verts sur l'ensemble des tests `sources/` + `ebay/` + base
  (`test_sources_base.py`, `test_ebay_*.py`)
- Typecheck front : 0 erreur dans `features/sources/` (les erreurs
  préexistantes dans `audit/`, `lab/`, `sets/` restent indépendantes).
- 18 fails pytest persistants ailleurs dans la suite ML (`test_augmentation`,
  `test_benchmark`, `test_normalize_listing`, `test_lab_api`,
  `test_review_lots_api`) sont préexistants sur `main`, indépendants de
  ce chantier.

### Snippets utiles

```bash
# Lister les rejets d'un run
curl "http://localhost:8000/sources/ebay/runs/<RUN_ID>/discarded" | jq

# Filtrer sur une raison
curl "http://localhost:8000/sources/ebay/runs/<RUN_ID>/discarded?reason=theme_mismatch" | jq

# Distribution des raisons sur tous les runs (debug DB)
sqlite3 ml/state/training.db "
  SELECT reason, COUNT(*) AS n
    FROM discarded_listings
   WHERE source = 'ebay'
   GROUP BY reason ORDER BY n DESC;"

# Funnel ventilé d'un run
sqlite3 ml/state/training.db "
  SELECT target_eurio_id,
         n_summaries, n_after_groups, n_raw_results, n_kept_results
    FROM discovery_searches
   WHERE run_id = '<RUN_ID>'
   ORDER BY created_at;"
```

## Chunk 4 — Extracteur `ListingTextSignals`

Module pur, no I/O. Premier signal indépendant de Dino. Pas encore
branché en pipeline (chunk 5) ni comparé au target (chunk 6).

### Périmètre + observations DB qui ont guidé le design

Sample de 30 `source_images.listing_title` + 15 `discarded_listings.title`
réels avant le code. Constats clés :

1. **Pays = quasi systématique en titre**, sous formes très variées :
   - Substantif FR/EN/DE/IT/ES (`ANDORRE`/`Andorre`/`Andorra`,
     `BELGIQUE`/`Belgium`/`Belgien`, `Autriche`/`Austria`/`Österreich`,
     `Pays-Bas`/`Netherlands`/`Niederlande`, …)
   - Adjectifs (`française`, `belge`, `allemande`, …)
   - Flags emoji 🇫🇷 occasionnels
   - **Codes ISO2 nus** (`FR`, `DE`) → trop de faux positifs sur
     sigles, on les **exclut**.
2. **Aspects eBay quasi vides** sur les summaries Browse
   (`localizedAspects = []` sur tous les samples). En pratique on
   travaille presque uniquement à partir du titre. L'extracteur
   accepte un `aspects: dict` optionnel pour les sources qui en
   peuplent (numista legacy, autres marketplaces), mais on ne s'y
   appuie pas.
3. **Naming trompeur dans la DB** : `source_images.listing_country`
   et `listing_year` sont en fait remplis avec les valeurs du
   *target* par l'adapter eBay (`coin.country`, `coin.year`), pas
   extraites du listing. L'extracteur reste donc utile : c'est lui
   qui produit le signal "ce que dit le texte", à confronter au
   prior.
4. **Multi-pays détecté = signal lot**, pas signal "ambigu". Un
   titre type `Andorra & France 2 Euro 2023` est un lot
   transfrontalier, traité comme tel.
5. **Plages d'années** (`2005-2025`, `1999 à 2014`) capturées comme
   tous les years individuels. La logique amont `year_mismatch`
   (filters.py) rejette déjà ces shop-listings.
6. **Identifiants Numista** (`KM527`, `KM:New`, `KM#3065`) sortent
   en theme tokens si on ne les drop pas — on les drop par règle
   `tok.startswith("km") and any(c.isdigit() for c in tok)`.

### Livré

- **Module** `ml/sources/text_signals/` :
  - `dictionaries.py` — `COUNTRY_NAMES` (ISO2 → set noms FR/EN/native),
    `COUNTRY_ADJECTIVES`, `COUNTRY_FLAGS` (emoji), `DENOMINATION_RE`,
    `YEAR_RE`, `REJECTION_MARKERS` (proof/metal/colored/error_struck/
    replica/fantasy), `LOT_KEYWORDS_RE`, `COUNT_X_RE`,
    `COUNT_PIECES_RE`, `STOP_WORDS`, `VALID_FACE_VALUES`.
  - `extractor.py` — `ListingTextSignals` dataclass frozen
    (`countries`, `years`, `denominations`, `theme_tokens`,
    `rejected_markers`, `is_lot`, `coverage`, `matched`) +
    `extract_listing_text_signals(title, *, aspects=None)`.
  - `__init__.py` — re-exports.
- **Tests** `ml/tests/test_text_signals.py` : **59 tests** couvrant
  pays (substantif/adjectif/flag/multi/codes nus exclus), années
  (single/range/multi/borne), dénominations (variantes
  `2€`/`2 EUR`/`0,50 €`/`2EUR`/multi), markers (proof, metal,
  error, replica), lot (keyword/compteur/multi-pays), coverage,
  theme tokens (drop pays/année/denom/KM, ordre préservé),
  end-to-end sur titres réels, dataclass hashable.
- **Audit visuel** (script ad-hoc, 30 source_images + 15
  discarded_listings) : extraction conforme aux attentes.
  Borderline observés et acceptés en V1 :
  - `Set 1 ct.` matche `is_lot=True` via "set" (= coffret cents,
    correct sémantiquement).
  - `Série courante` matche `is_lot=True` via "série"
    (légèrement faux positif mais ces listings ne devraient pas
    auto-accept de toute façon).
  - `BU original` matche `proof` (cohérent avec
    `accept_listing.NOISE_PATTERNS` qui rejette aussi BU).

### Bugs corrigés en cours de route

- `DENOMINATION_RE` : le `\b` final cassait les matches `2€` et
  `0,50 €` (le caractère `€` n'est pas word-char, donc le boundary
  word/non-word ne tenait pas après lui). Fix : `(?:€|eur(?:os?)?\b)`
  — pas de `\b` après le symbole monétaire, mot `euro/euros`
  fermé proprement.
- `COUNT_PREFIX_RE` exigeait le mot "pièces|coins|münzen" après
  le compteur. Du coup `2 x 2 EURO ANDORRE` ne triggait pas le lot.
  Fix : split en deux regex, `COUNT_X_RE` (`\d+\s*x\s+\S`) +
  `COUNT_PIECES_RE` (`\d+\s*(pièces|coins|münzen)`).

### Tests

- 59/59 verts sur `tests/test_text_signals.py`
- 108/108 verts sur l'ensemble `text_signals + ebay + orchestrator
  + sources_base`. Aucune régression sur les chunks 0-3.

### Ce qui n'est PAS livré (volontairement, périmètre chunks suivants)

- **Chunk 5** : étape pipeline `text_signal_extract` qui consomme
  cet extracteur, écrit dans une nouvelle table
  `listing_text_signals` (1 row par listing eBay, indexée par
  `ebay_item_id`). Persistance backfillable.
- **Chunk 6** : comparateur `vs_target(sig, target_eurio_id) →
  Literal["convergent","partial","absent","contradict"]`. Filtre
  dur "contradict" écrit dans `discarded_listings(reason='text_*')`.
- **Chunk 7** : panel front "Texte" dans drawer review.
- **Chunk 8** : combinatoire Dino × texte → auto-accept.

### Audit demandé à Raphaël

```python
# Script ad-hoc disponible dans la conversation, à reprendre si besoin :
import sqlite3
from sources.text_signals import extract_listing_text_signals

conn = sqlite3.connect("ml/state/training.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT target_eurio_id, listing_title FROM source_images "
    "WHERE listing_title IS NOT NULL ORDER BY RANDOM() LIMIT 30"
).fetchall()
for r in rows:
    sig = extract_listing_text_signals(r["listing_title"])
    print(r["target_eurio_id"], "→", sig)
```

Et pour les tests :
```bash
go-task ml:venv -- pytest tests/test_text_signals.py -v
```

Si tu vois des cas dans la pratique où l'extraction te paraît
fausse / contre-intuitive, on ajuste les dictionnaires et les
patterns. Le prochain chunk 5 (persistance + backfill) confirmera
sur l'ensemble des 783 source_images.

## Chunk 5 — Étape pipeline `text_signal_extract` + persistance

Le chunk 4 a livré l'extracteur pur. Le chunk 5 le branche dans la
pipeline orchestrateur, persiste les sorties, et backfill les
source_images existants pour qu'on ait des données pour le chunk 6.
Aucune décision ici (rien n'est rejeté, rien n'est auto-validé).

### Livré

- **Schema** : nouvelle table `listing_text_signals` (PK
  `source_image_id` REFERENCES source_images ON DELETE CASCADE,
  `extractor_version`, `countries_json`/`years_json`/`denominations_json`
  /`theme_tokens_json`/`rejected_markers_json`, `is_lot`, `coverage`
  CHECK, `matched_json`, `computed_at`). Index sur `coverage` et
  `is_lot WHERE is_lot=1`.
- **Store** : dataclass `ListingTextSignalsRow` + méthodes
  `Store.upsert_listing_text_signals` (UPSERT sur source_image_id,
  ON CONFLICT DO UPDATE), `Store.get_listing_text_signals`,
  `Store.has_listing_text_signals`.
- **Step pipeline** `ml/sources/_base/steps/text_signal.py` :
  `run_text_signal_extract(conn, run, source_image_ids, force,
  store)` — idempotent (skip si row existe pour
  `extractor_version='v1'`), persiste via Store si fourni sinon SQL
  direct sur la conn (pour les tests / backfill avec raw connection).
- **Orchestrateur** : step `text_signal` ajouté dans `PIPELINE_STEPS`
  et `run_logger._VALID_STEPS`. Branché entre `persist` et `download`
  — le titre est dispo dès `persist`, et la position permet au
  chunk 6 (filtre `text_contradict_*`) d'éviter le download inutile
  des listings clairement contradictoires.
- **Backfill standalone** : `ml/scripts/backfill_text_signals.py`
  + entrée Taskfile `ml:text-signals:backfill`. Args
  `[--source ebay] [--limit N] [--force]`. Affiche un résumé +
  distribution coverage/is_lot.
- **API** : 2 endpoints dans `review_queue_routes.py` (cohérent avec
  les patterns dino-suggestions) :
  - `GET /review-queue/asset/{asset_id}/text-signals` — résout via
    `image_assets.source_image_id`.
  - `GET /review-queue/{review_id}/text-signals` — résout via
    `review_queue.image_asset_id` puis l'asset.
  Réponse Pydantic `TextSignalsResponse` avec tous les champs +
  `listing_title` + `target_eurio_id` joints depuis `source_images`.
  404 propre si le step n'a pas tourné.
- **Tests** `ml/tests/test_text_signal_step.py` (8 tests) :
  persistance, idempotence, force-recompute, titre vide, titre NULL,
  batch multi-images, source_image manquant, input vide.

### Backfill réel sur 783 source_images

```
Extracted:           783
Skipped (existing):  0
Skipped (empty):     0
Errors:              0
Total time:          0.38s
Per-image average:   0.48ms
```

**Distribution coverage × lot** :

| coverage | is_lot=0 | is_lot=1 |
|---|---|---|
| rich | **548** | 156 |
| sparse | 61 | 18 |

→ **548/783 = 70 % des listings sont "rich + non-lot"** → candidats
prime pour le futur auto-accept (chunk 8). Les 156 rich+lot sont à
analyser au chunk 6 (lot transfrontalier ↔ multi-country signal
indépendant utile, vs lot intra-pays pour lequel le crop ne nous dit
pas laquelle des pièces du coffret est sur l'image).

**Distribution pays détectés** (top) : AD=356, AT=199, BE=190, LU=28
(via union économique BE↔LU), FR=12, ES=6, IT=4. Cohérent avec les
batches commémo scrapés.

**Distribution markers de rejet** : seulement 28 `error_struck`
+ 12 `colored` sur 783. Ratio bas attendu — les vrais hors-scope
(`proof`, `metal`) ont déjà été virés par `accept_listing` en amont,
donc ne sont pas dans `source_images`.

### Tests

- 8/8 verts sur `tests/test_text_signal_step.py`
- 67/67 verts sur l'ensemble `text_signals + step + ebay_adapter +
  orchestrator`. Aucune régression.

### Hors-scope (volontairement, repris au chunk 6)

- Pas de comparateur `vs_target` — c'est l'objet du chunk 6.
- Pas de filtre dur (`text_contradict_*` → `discarded_listings`)
  — chunk 6.
- Pas de panel front "Texte" dans le drawer review — chunk 7.
- Pas de combinaison Dino × texte — chunk 8.

### Audit demandé à Raphaël

```bash
# Vérifier la distribution
sqlite3 ml/state/training.db "
  SELECT coverage, is_lot, COUNT(*) AS n
    FROM listing_text_signals
   GROUP BY coverage, is_lot ORDER BY coverage, is_lot;"

# Spot-check : voir les signaux d'un listing identifié
sqlite3 ml/state/training.db "
  SELECT lts.*, si.listing_title
    FROM listing_text_signals lts
    JOIN source_images si ON si.id = lts.source_image_id
   ORDER BY RANDOM() LIMIT 5;"

# Tester l'endpoint API (FastAPI doit tourner)
curl http://localhost:8000/review-queue/asset/<ASSET_ID>/text-signals | jq

# Re-trigger un run eBay et observer le step text_signal
go-task ml:api &  # ou la commande équivalente
# trigger run depuis admin → chercher "[text_signal]" dans les logs
```

Le **kickoff complet du chunk 6** est dans
[`chunk-06-text-comparator-kickoff.md`](./chunk-06-text-comparator-kickoff.md).
À reprendre dans une nouvelle session.

## Chunk 6.a + 6.b — Comparateur `vs_target` (pur) + persistance verdict + API

Première moitié du chunk 6 : comparateur testable + 3 colonnes additives
+ enrichissement de `TextSignalsResponse`. **Aucune décision pipeline** :
le verdict est calculé et persisté, mais aucun listing n'est rejeté
(filtre dur reporté à 6.c après audit).

### Décisions actées (post-brainstorm)

- **1 axe contradict suffit** pour basculer en `contradict`. À monitorer ;
  durcissement à 2 axes si > 15 % de la distribution.
- **`convergent` = 3/3 axes confirmés** (le doc kickoff §"Verdict global"
  était ambigu : la matrice disait `n_convergent == n_present` mais le
  cas #3 explicite `partial` pour 2/3). Le code suit les cas explicites
  du doc, pas la matrice.
- **`partial` = entre les deux** (au moins 1 convergent, 0 contradict,
  pas tout convergent).
- **Normalisation pays** : extracteur produit ISO2 uppercase, `coins.country`
  uppercase aussi, slug `eurio_id` lowercase. Le comparateur normalise
  les deux côtés en lowercase au moment de la comparaison — pas de
  migration des données.

### Livré

- **Module** `ml/sources/text_signals/comparator.py` :
  - `TargetIdentity` (dataclass frozen) — identité target chargée
    depuis `coins`.
  - `VsTargetVerdict = Literal["convergent","partial","absent","contradict"]`.
  - `VsTargetComparison` (dataclass frozen) avec `verdict`,
    `contradictions`, `convergences`, target snapshot.
  - `compare_to_target(signals, target)` — pure, no I/O.
  - `load_target_identity(conn, eurio_id)` — DB helper qui lit
    `coins`. Country normalisé lowercase à la sortie.
- **Re-exports** dans `ml/sources/text_signals/__init__.py`.
- **Schema** : 3 colonnes additives sur `listing_text_signals` —
  `vs_target_verdict TEXT CHECK(...)` (NULL autorisé pour les rows
  pré-chunk-6 ou sans target connu), `contradictions_json TEXT NOT NULL
  DEFAULT '[]'`, `convergences_json TEXT NOT NULL DEFAULT '[]'`.
  Migration via `Store._ensure_column`. Index
  `idx_listing_text_signals_verdict` créé dans `_bootstrap` après
  `_ensure_column` (pas dans `schema.sql` pour ne pas péter
  `executescript()` sur les bases pré-existantes — même pattern que
  chunk 3.5).
- **`ListingTextSignalsRow`** étendu (`vs_target_verdict`,
  `contradictions`, `convergences`). `Store.upsert_listing_text_signals`
  + `_row_to_text_signals` mis à jour.
- **Step pipeline** `text_signal.py` : après extraction, charge
  `target_eurio_id` depuis `source_images`, appelle
  `load_target_identity` → `compare_to_target` si target trouvé. Aucune
  décision (pas de `discarded_listings` écrit). Verdict NULL silencieux
  si pas de target ou target absent de `coins`.
- **API** : `TextSignalsResponse` enrichi avec `vs_target_verdict`,
  `contradictions`, `convergences`. Endpoints inchangés. Lecture
  rétro-compatible (utilise les colonnes si présentes).
- **Backfill** : `--force` recompute le verdict en place via le step
  existant (réutilise toute la mécanique chunk 5). Le script affiche
  désormais aussi la distribution `vs_target_verdict`.
- **Tests** :
  - `ml/tests/test_text_comparator.py` (16 tests) — 9 cas du doc kickoff
    + edges : case-insensitive, year-out-of-range, range boundaries,
    ordre stable, multi-contradiction, identité du target.
  - `ml/tests/test_text_signal_step.py` étendu (+6 tests) — verdict
    persisté convergent/contradict/partial, NULL si target inconnu,
    NULL si pas de `target_eurio_id`, recompute sur force après ajout
    coin.

### Audit visuel — backfill réel sur 783 source_images

```
Extracted:           783 / 0.46s / 0.59ms par image
Coverage:  rich=704, sparse=79
is_lot:    0=609, 1=174
```

**Distribution `vs_target_verdict`** :

| verdict | n | % |
|---|---|---|
| convergent | 695 | **88.8 %** |
| partial | 76 | 9.7 % |
| contradict | **7** | **0.9 %** |
| ∅ (target inconnu) | 5 | 0.6 % |

**Très loin des ~10 % théorisés** sur `contradict`. Explication : les
filtres upstream (`accept_listing.year_mismatch`, `theme_mismatch`,
`noise_title`) ramassent déjà la majorité des listings franchement
mal-targetés *avant* d'arriver à `source_images`. Le comparateur attrape
le résidu — peu nombreux mais nets.

**Audit manuel des 7 contradicts** — précision **100 %** :

| Contradiction | Listing | Target |
|---|---|---|
| `denomination` | `lot de 2 pieces Andorra 2016 de 1 euro` | `ad-2016-2eur-radio-tv` |
| `country` | `Espagne 2005/2025 - 2 Euro Commemorative` | `at-2005-2eur-state-treaty` |
| `country` (×2) | `2 Euros FRANCE 2018 Simone Veil` | `at-2018-2eur-republic` |
| `year` (×2) | `Belgique 2005` / `Belgique 2010` | `be-2006-2eur-atomium` |
| `country` | `Pièce 2008 Finlande Portugal RFA` | `be-2008-2eur-human-rights` |

Tous des cas réels où la query eBay a chopé un listing mal-indexé chez
un autre pays/année. Le filtre dur 6.c rejetterait ces 7 listings
sans risque.

**Sample des partials** : beaucoup de cas où le titre exposé "2 centimes
d'euro" ou "Choisissez votre année" — l'extracteur regex ne capte pas
la forme "X centimes d'euro" (DENOMINATION_RE ne matche que
`X euro|€|EUR`). Conséquence : un listing 2-cent BE-2006 reste en
`partial` (country+year convergent, denom absent au lieu de contradict).
**False-negative sur `contradict`** — pas un false-positive. Le listing
ne sera pas auto-accepté (chunk 8 exigera `convergent`), il ira en
review humaine. Safe.

À noter pour chunk 4 follow-up : étendre `DENOMINATION_RE` à
"X centimes/cents/cent d'euro" si on veut récupérer ces vrais
contradicts. Pas requis pour chunk 6.

### Tests

- 89/89 verts sur `tests/test_text_comparator.py +
  test_text_signal_step.py + test_text_signals.py`.
- 158/158 verts sur l'ensemble `text_signals + step + ebay_adapter +
  orchestrator + sources_base + foundation`. Aucune régression.

### Go / no-go pour chunk 6.c

**Recommandation : GO.**

- Précision 100 % sur les 7 contradicts. Pas d'échantillon à corriger.
- Volume bas (0.9 %) → faible gain mais sans risque.
- L'écosystème filtres existe : panel front "Listings rejetés"
  (chunk 0) absorbera les chips `text_contradict_*` automatiquement.

À faire au chunk 6.c :
- Câbler le step pour écrire dans `discarded_listings` (reason
  `text_contradict_<axe>`) sur verdict=`contradict`.
- Marquer `route_decision='rejected_text'` sur `source_images`.
- Filtrer dans `run_download` les sources avec `route_decision='rejected_text'`.
- Ajouter `reasonLabel`/`reasonTone` côté front pour chips gold.
- Re-trigger la pipeline ou backfill pour matérialiser les rejets.

### Snippets utiles

```bash
# Re-backfill du verdict (force)
go-task ml:text-signals:backfill -- --force

# Distribution actuelle
sqlite3 ml/state/training.db "
  SELECT COALESCE(vs_target_verdict,'∅') v, COUNT(*) n
    FROM listing_text_signals
   GROUP BY vs_target_verdict ORDER BY n DESC;"

# Lister les 7 contradicts pour audit
sqlite3 ml/state/training.db "
  SELECT lts.contradictions_json, si.listing_title, si.target_eurio_id
    FROM listing_text_signals lts
    JOIN source_images si ON si.id = lts.source_image_id
   WHERE vs_target_verdict='contradict';"

# Test endpoint enrichi (FastAPI doit tourner)
curl http://localhost:8000/review-queue/asset/<ASSET_ID>/text-signals | jq
```

## Chunk 6.c — Filtre dur `text_contradict_*`

Branchement du verdict `contradict` du chunk 6.b en décision pipeline :
le step `text_signal` écrit dans `discarded_listings` et marque
`source_images.route_decision='rejected_text'`. Le step `download` saute
ces sources_images — économie de quota CDN + cycles `detect_crop` sur
des listings clairement mauvais.

### Livré

- **Step `text_signal.py`** : après extraction + verdict, agrège les
  contradicts puis `_apply_text_contradict_rejections` :
  - `DELETE FROM discarded_listings WHERE source = ? AND source_ref = ?
    AND reason LIKE 'text_contradict_%'` (idempotence force-recompute).
  - `record_discarded_listing(reason=f"text_contradict_{axe}", title=…,
    raw_payload={contradictions, convergences, signals, target})`.
  - `UPDATE source_images SET route_decision='rejected_text',
    route_reason=axe`.
  - `n_rejected_contradict` exposé sur `TextSignalResult`.
- **Step `download.py`** : 5 lignes au début de la boucle pour skipper
  les `route_decision='rejected_text'`. Comptés en `n_skipped`.
- **Front** `useRunDiscarded.ts` :
  - `REASON_TONE` : `text_contradict_country/year/denomination` →
    `var(--gold-600)` (rejet souple, target potentiellement faux,
    cohérent avec `theme_mismatch`).
  - `REASON_LABEL` : libellés FR par axe ("Pays du titre ≠ pays du
    target", etc.).
  - Le panel `SourceRunListingsPage.vue` consomme déjà ces helpers,
    aucun changement de composant.
- **Tests** `test_text_signal_step.py` (+3 tests) :
  - `test_contradict_writes_discarded_and_route_decision` — payload
    JSON cohérent + `route_decision`/`route_reason` posés.
  - `test_no_rejection_on_convergent` — pas d'écriture parasite.
  - `test_force_recompute_does_not_duplicate_discarded` — idempotence.
- **Fixture** étendue (5 ALTER TABLE) pour répliquer les colonnes
  `_ensure_column` qui ne sont pas dans `schema.sql` (route_decision,
  route_reason, vs_target_verdict, contradictions_json, convergences_json).
  En sync avec `Store._bootstrap`.

### Audit visuel — re-backfill 783 listings

```
Extracted: 783 / 0.40s / 0.52ms par image
rejected_contradict=7
```

Distribution `discarded_listings` (filter `text_contradict_*`) :

| reason | n |
|---|---|
| text_contradict_country | 4 |
| text_contradict_year | 2 |
| text_contradict_denomination | 1 |

`source_images.route_decision='rejected_text'` posé sur les 7 listings
avec `route_reason` portant l'axe.

### Tests

- 17/17 verts sur `tests/test_text_signal_step.py`
- 92/92 verts sur `text_comparator + step + extracteur`
- 141/141 verts sur l'ensemble `text_signals + ebay + orchestrator +
  sources_base`. Aucune régression.
- Front : aucune erreur typecheck dans `features/sources/`. Les erreurs
  préexistantes (`audit/`, `lab/`, `sets/`) restent indépendantes.

### Audit demandé à Raphaël

```bash
# 1. Lancer l'API + dev server admin
go-task ml:api &
cd admin/packages/web && pnpm dev

# 2. Naviguer vers /sources/ebay/runs/<run_id>/listings (un run récent)
#    Vérifier le panel "Listings rejetés pré-ingestion" :
#    - chips counter par raison incluent text_contradict_country/year/denomination
#    - tonalité gold (rejet souple, comme theme_mismatch)
#    - drill-down par row affiche le payload (contradictions/convergences/signals/target)
#    - libellés FR explicites ("Pays du titre ≠ pays du target")

# 3. Re-trigger un run eBay et observer "[text_signal] ... rejected_contradict=N"
#    dans les logs ML. Le step download skippera N listings supplémentaires.
```

### Snippets utiles

```sql
-- Distribution des rejets text_contradict_*
SELECT reason, COUNT(*) AS n
  FROM discarded_listings
 WHERE reason LIKE 'text_contradict_%'
 GROUP BY reason ORDER BY n DESC;

-- Source_images en rejected_text avec leur titre + target
SELECT si.source_ref, si.target_eurio_id, si.route_reason, si.listing_title
  FROM source_images si
 WHERE si.route_decision = 'rejected_text';

-- Cross-check : un contradict en DB doit avoir une row discarded_listings
SELECT lts.source_image_id, si.source_ref,
       lts.contradictions_json, dl.reason
  FROM listing_text_signals lts
  JOIN source_images si ON si.id = lts.source_image_id
  LEFT JOIN discarded_listings dl
    ON dl.source = si.source AND dl.source_ref = si.source_ref
   AND dl.reason LIKE 'text_contradict_%'
 WHERE lts.vs_target_verdict = 'contradict';
```

### Hors-scope (rappels)

- ❌ Pas de panel front "Texte" dans le drawer review — chunk 7.
- ❌ Pas de combinaison Dino × texte → auto-accept — chunk 8.
- ❌ Pas de bouton "réinjecter" sur les rejets — V1 minimaliste, le
  re-fetch passe par une autre query.
- ❌ Extracteur regex `DENOMINATION_RE` ne capte pas "X centimes d'euro" —
  follow-up chunk 4 si on veut récupérer les false-negatives
  partial→contradict (ex. "Belgique 2006 2 centimes" qui reste partial
  au lieu d'être contradict).

## Chunk 7 — Panel "Texte" dans le drawer review

Surface visuelle du verdict + axes côté reviewer. Le filtre dur
chunk 6.c a déjà retiré les `contradict` de la queue ; ce qui reste à
reviewer est essentiellement `convergent` / `partial` / `absent`. Le
panel donne à Raphaël le *pourquoi* du verdict en un coup d'œil, pour
qu'il puisse pondérer les suggestions Dino en conséquence.

### Décisions de design

- **Variante standard** : panel sous la card "Listing source" du
  drawer single (= colonne gauche, après l'input listing). Cohérent
  avec la sémantique : le texte est l'interprétation du titre affiché
  juste au-dessus.
- **Variante compact** : strip horizontal dans le header du drawer lot
  (= au niveau listing, pas par crop, puisque le signal est partagé).
- **Pas de cliquable / décisionnel** : aide visuelle pure, P5 vision
  ("audit en /review"). L'œil compare Texte ↔ Dino ↔ Suggestions.
- **Glyphes ASCII** (`✓ ✗ ⊘`) au lieu d'icônes lucide pour parité
  visuelle avec `CandidateRow.vue` / monospace ambient.
- **Per-axis state recomputé côté front** depuis
  `convergences/contradictions` retournés par l'API — pas de double
  appel, cohérent avec `comparator.py::_country_axis` etc.

### Livré

- **Composable** `admin/packages/web/src/features/review/composables/
  useTextSignals.ts` :
  - `fetchTextSignalsByReviewId(reviewId)` /
    `fetchTextSignalsByAssetId(assetId)` — 404 silencieux.
  - Type `TextSignalsResponse` (mirror Pydantic chunk 6.d).
  - Helpers visuels : `verdictTone`, `verdictColor`, `verdictLabel`,
    `axisState`, `axisStateColor`, `axisStateGlyph`.
- **Composant** `admin/packages/web/src/features/review/components/
  TextSignals.vue` :
  - Variante `standard` : header (icône Type + verdict colorisé) →
    liste 3 axes (pays / année / denom) avec glyphe ✓/✗/⊘ +
    valeurs détectées + raw matchers entre parenthèses → chips
    secondaires (`is_lot` gold, `rejected_markers` rouge, `coverage`
    si pas rich) → footer extracteur version.
  - Variante `compact` : strip 1 ligne avec `Texte · convergent ·
    ✓ pays · ✓ année · ✓ denom · [lot]`. Tooltip par axe pour
    afficher les valeurs détaillées.
  - Lazy fetch via watcher sur `reviewId|assetId` — re-fetch
    automatique quand le drawer change d'item.
  - Tones : convergent=`var(--success)`, partial=`var(--gold-600)`,
    contradict=`var(--danger)`, absent/null=`var(--ink-400)`.
- **Plug `SingleReviewView.vue`** : import + `<TextSignals
  :review-id=… variant="standard" />` inséré juste après la card
  `Listing source` dans la colonne gauche.
- **Plug `LotDetailDrawer.vue`** : import + computed
  `firstAssetId` (premier asset du premier image, le signal vit au
  niveau listing donc 1 fetch suffit pour tout le lot) +
  `<TextSignals :asset-id=… variant="compact" />` dans le header,
  sous les badges meta.

### Audit visuel demandé à Raphaël

```bash
go-task ml:api &
cd admin/packages/web && pnpm dev
# Naviguer /review (Single) :
#   - Sous "Listing source" un panel "Signal texte" apparaît
#   - Verdict colorisé en haut à droite (convergent vert / partial gold)
#   - 3 axes pays/année/denom avec ✓ / ⊘ et valeurs extraites
#   - chip "lot" gold quand is_lot=true
# Naviguer /review (Lot) :
#   - Header du drawer lot : strip "Texte · <verdict> · ✓ pays · ✓ année..."
#   - Tooltip par axe au survol affiche les valeurs détaillées
```

### Tests

- Aucun test E2E — composant pur d'aide visuelle, le composable a la
  même structure que `useDinoSuggestions.ts` (testé via vues).
- Backend : 141/141 verts (héritage chunk 6).
- Front : zéro erreur TS dans `features/review/`. Une régression
  préexistante surfacée et fixée
  (`SingleReviewView.vue::onSearchSelect` — mismatch
  `string | null` → `string` sur `canonical_thumb_url`, fixé via
  fallback `?? ''`).

### Hors-scope (rappels)

- ❌ Pas d'auto-accept (chunk 8 — combinatoire Dino × texte).
- ❌ Pas de panel "Auto-validate" (chunk 8 — verdict combiné).
- ❌ Pas de re-fetch quand le verdict est null (target inconnu) — on
  affiche un fallback explicite "Target non résolu — comparaison
  impossible".

### Snippets utiles

```bash
# Tester l'endpoint enrichi sur un asset connu
curl http://localhost:8000/review-queue/asset/<ASSET_ID>/text-signals | jq

# Pour valider visuellement un cas convergent / partial / contradict :
sqlite3 ml/state/training.db "
  SELECT lts.source_image_id, ia.id AS asset_id,
         lts.vs_target_verdict, si.listing_title
    FROM listing_text_signals lts
    JOIN source_images si ON si.id = lts.source_image_id
    JOIN image_assets ia ON ia.source_image_id = si.id
   WHERE lts.vs_target_verdict IN ('partial','convergent')
   ORDER BY RANDOM() LIMIT 5;"
```

## Chunk 7.b — Sélecteur libre inline + hover preview + colonne droite figée

Refacto UX du `/review` (single) en préparation chunk 8 : avec
l'auto-accept, les cas qui restent en queue sont par construction les
plus durs (Dino top1_country ≠ target ou texte partial/absent). Donc le
sélecteur libre va être utilisé bien plus souvent — il fallait qu'il
n'écrase plus le crop à identifier.

### Décisions de design (post-discussion Raphaël 2026-05-05)

- **Sélecteur libre = swap in-place** dans la colonne droite, plus de
  modal qui couvre le crop. Toggle segmented `[🤖 Auto · 🔍 Libre]`
  remplace l'ancien bouton "Sélecteur libre · F". F bascule, Esc en
  mode Libre repasse en mode Auto. Reset à `'auto'` à chaque changement
  d'item (la suggestion auto reste le défaut).
- **Sélection d'une pièce → repasse Auto** automatiquement pour
  afficher le banner gold "Sélection libre" + permettre validation ⏎.
  Le pick fait passer la pièce dans `freeSearchCandidate` (path
  inchangé).
- **Source données = table `coins` Supabase** (même que `/coins` page).
  Plus de mock placehold.co. Cascade `country + face_value +
  is_commemorative` mappée depuis le `denomination` synthétique du
  selector.
- **25 pays** (21 eurozone + AD, MC, SM, VA), tri alphabétique par
  code ISO. Affichage code-only (pas de drapeau) en grille 7 cols pour
  tenir dans 560px.
- **Affichage résultats = liste de rows** (même style que
  `DinoSuggestions` standard) au lieu d'une grille de vignettes —
  permet de voir image + eurio_id complet (wrap multi-lignes au
  besoin) + année/commémo.
- **Hover preview** sur les rows (Dino + sélecteur libre) :
  `position: fixed` + Teleport vers `<body>`, anchored au-dessus de la
  row hovée, flip auto en dessous si pas la place, `pointer-events:
  none` pour ne jamais voler le focus. ~220×270px, fade-in 120ms.
  Décision clé : *au-dessus* de la row, pas en dessous, pour que le
  curseur ne traverse jamais le preview en descendant vers la row
  suivante.
- **Colonne droite à largeur fixe** (560px) au lieu de `1fr` qui
  laissait le contenu pousser la colonne et écraser la gauche. Grid =
  `minmax(0,1fr)_560px`.
- **Plus de scroll de page complète** : grid `overflow-hidden`, chaque
  colonne gère son propre scroll. Crop / listing source / signal texte
  restent visibles à gauche. En mode Libre, le panel a un split
  interne : cascade `shrink-0` figée en haut, résultats `flex-1
  overflow-y-auto` qui scrollent indépendamment.
- **Modal `CoinSearchModal` conservé** pour `LotReviewDetailPage` (où
  la colonne droite est déjà prise par les crop cards) — pas de
  breaking change sur le flow lot.

### Livré

- **Composable** `admin/packages/web/src/features/review/composables/
  useCoinsSearch.ts` :
  - `searchCoins()` requête Supabase `coins` au lieu du mock. Map
    selector denomination ('1c'…'2eur-comm') → `face_value` +
    `is_commemorative`. Thumb via `firstImageUrl(coin)` (helper
    partagé `@/shared/utils/coin-images`).
  - `EURO_COUNTRIES` étendu à 25 (ajout AD/MC/SM/VA), trié par code
    ISO.
  - `DENOMINATIONS` enrichi avec `faceValue` + `commemorative` pour
    le mapping DB.
- **Composant** `admin/packages/web/src/features/review/components/
  CoinHoverPreview.vue` *(nouveau)* :
  - Floating preview, props `imageUrl + eurioId + label + anchorRect`.
  - Position auto au-dessus / flip en dessous selon espace dispo.
  - Teleport `<body>` pour échapper aux scroll containers parents.
  - `pointer-events: none`, fade-in 120ms.
- **Composant** `admin/packages/web/src/features/review/components/
  FreeSelectorPanel.vue` *(nouveau)* :
  - Variante inline du sélecteur libre. Cascade pays (grille 7×4
    code-only) → dénom (pills wrap) → année (scroll horizontal).
  - Résultats en liste de rows : thumb 36×36 + eurio_id wrap +
    année/commémo + bouton "Sélec." gold.
  - Hover preview sur chaque row via `CoinHoverPreview`.
  - Layout interne : `flex h-full flex-col`, cascade `shrink-0`,
    résultats `min-h-0 flex-1 overflow-y-auto`.
  - Émet `select` avec `CoinSearchEntry`.
- **Plug `DinoSuggestions.vue`** :
  - Import `CoinHoverPreview`.
  - `hoveredKey + hoveredRect + hoveredSuggestion` refs, handlers
    `onRowEnter / onRowLeave` sur les `<li>` des bandes pays + globale
    (variante standard).
  - Rendu `<CoinHoverPreview>` à la fin de la section standard.
- **Refacto `SingleReviewView.vue`** :
  - State `mode: 'auto' | 'free'`, reset à `'auto'` dans
    `resetForCurrent()`.
  - Sub-header : segmented toggle `[Sparkles Auto] [Search Libre F]`
    avec bg `var(--ink)` sur l'actif. Plus de bouton modal.
  - F (`useReviewKeybinds.onOpenSearch`) → `toggleMode()`.
  - Esc en mode Libre → retour Auto (au lieu de fermer overlay).
  - Aside swap : Auto = Top N + Dino + banner gold ;
    Libre = `<FreeSelectorPanel>` flex-1.
  - Grid changée : `lg:grid-cols-[2fr_1fr]` →
    `lg:grid-cols-[minmax(0,1fr)_560px]` (largeur fixe à droite).
  - Wrapper outer : `flex-1 overflow-y-auto px-8 py-6` →
    `grid flex-1 overflow-hidden px-8 py-6`. Colonne gauche `min-h-0
    overflow-y-auto`, aside `min-h-0 overflow-hidden`. Mode Auto a un
    inner wrap `flex min-h-0 flex-1 overflow-y-auto`.
  - Suppression import + usage `CoinSearchModal` (toujours utilisé par
    `LotReviewDetailPage` qui le conserve).
  - Help overlay : "F · Sélecteur libre (overlay)" → "F · Bascule
    mode Auto / Sélection libre".

### Audit visuel demandé à Raphaël

```bash
go-task ml:api &
cd admin/packages/web && pnpm dev
# /review (single) :
#   - Toggle visible en haut à droite, Auto sélectionné par défaut
#   - F bascule en mode Libre, Esc retourne Auto
#   - Mode Libre : pays code-only en grille, dénom en pills, années en
#     scroll horizontal (test FR · 2€ commémo : ~25 années dispo)
#   - Hover sur une row de résultat → preview ~220px au-dessus
#   - Hover sur les rows DinoSuggestions → même preview
#   - Click "Sélec." → retour mode Auto, banner gold, ⏎ valide
#   - Crop à résoudre reste TOUJOURS visible (pas de scroll de page)
#   - Liste résultats scrolle dans son conteneur, cascade reste figée
#   - Item suivant → repart en mode Auto par défaut
# /review (lot) :
#   - Modal CoinSearchModal toujours fonctionnel (inchangé)
```

### Tests

- Zéro erreur TS dans `features/review/` (les errors restantes sont
  préexistantes dans `features/sets/` et `features/audit/`).
- Pas de test E2E — refacto UX pure, comportements observables.

### Hors-scope (chunk 8.d et au-delà)

- ❌ Pas de badge `≈ auto` "presque auto-accepté" sur les Dino top1
  (chunk 8.d ou plus tard).
- ❌ Pas de filtre review queue pour exclure `auto_dino_text` (déjà
  filtré en amont par `resolution_status='needs_review'`, à vérifier
  côté chunk 8).
- ❌ Hover preview sur la variante `compact` de `DinoSuggestions` (lot
  drawer) — pas demandé, les tiles compactes sont trop petites pour
  une zone de hover utile.

