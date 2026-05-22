# Chantier — Découverte eBay par GROUPE (handoff)

> **État au 2026-05-21.** Document de reprise : où on en est, ce qui reste,
> et le changement de path du repo.

## Changement de path du repo

Le projet a été **déplacé** en cours de session :

- Ancien : `/Users/musubi42/Documents/Musubi42/Eurio`
- Nouveau : `/Users/musubi42/Documents/Musubi42/bizz/Eurio`

Conséquence : la mémoire auto de Claude Code est indexée sur l'ancien path
(`~/.claude/projects/-Users-musubi42-Documents-Musubi42-Eurio/`). À la
réouverture au bon endroit, un nouveau dossier mémoire sera créé — **ce
document-ci est la source de vérité pour reprendre**, pas la mémoire.

Un run a même planté en cours (`b5d72bf6…`) parce que le repo a bougé
pendant un retry de téléchargement (cwd supprimé).

## Le problème résolu

`build_query` produisait une requête eBay fonction de `(dénomination,
pays, année)` **uniquement** — le thème n'y est jamais. Deux commémos-
sœurs de la même année déclenchaient donc deux recherches byte-identiques,
et le post-filtre `theme_mismatch` **jetait** les listings de la sœur non
ciblée (149 faux rejets sur un seul run mesuré). Bascule : on découvre par
**groupe** `(dénom, pays, année)`, une recherche ramène toutes les sœurs,
chaque listing est **attribué** à sa pièce par le matcher de thème
multilingue. L'`eurio_id` reste la maille de stockage / review / prix,
mais cesse d'être la maille de découverte.

## Pré-requis livré avant la bascule

- **Pistes B + C** (theme matcher) : couverture i18n `coin_names_i18n`
  portée à de/es/it/nl pour 508 coins (1578 traductions LLM importées) ;
  `title_matches_theme` poole désormais les tokens de toutes les langues.
  Le matcher est fiable → la bascule groupée est sûre.

## État des chunks

| Chunk | Contenu | Statut |
|---|---|---|
| 1 | Cœur backend : `DiscoveryGroup`, `match_listing_to_group` (routeur 4 verdicts), `build_group_query`, `search_limit_for_group`, `discover()` groupé | ✅ committé (`9d65543`) |
| 2 | `v_ebay_freshness_groups`, endpoints `freshness-groups` + `run-preview`, quota group-aware, CLI groupes | ✅ committé |
| 3 | Front `EbayPilotPanel` groupé (buckets/slider/preview), trigger `discovery_groups` | ✅ committé |
| 4a | Retry downloads (`resume_failed_downloads`, endpoint `retry-downloads`, bandeau front) + `zero_crops` n'est plus une erreur | ✅ committé `cc25c01` |
| 4b | Breakdown relu pour runs groupés, UX retry (bascule onglet Logs) | ✅ committé `cc25c01` |
| 4c | `discovery_searches` résolues par groupe, panneau « Règles de filtrage » (`FilterRulesPanel`) | ✅ committé `cc25c01` |
| 5a | Relabel UI review : « Cible eBay » → « Pièce proposée / attribuée au listing » (`ReviewRightColumn.vue`, commentaires `SingleReviewView.vue`) | ✅ committé `d3a149e` |
| 5b | Candidats du groupe sélectionnables pour listings sans proposition (requête `coins` par `(country, year, 2€ commémo)`, champ `ReviewItem.group_candidates`, section front « Pièces du groupe ») | ✅ committé `d3a149e` |
| 5c | Commit différé des décisions review (fenêtre undo 10 s, fix re-décision 409) — *hors périmètre initial, livré en cours de session* | ✅ committé `2c515db` |
| 6 | Migration `v_ebay_freshness`, audit code mort, `progress.md` | ✅ committé (cf. ci-dessous) |

## Fichiers non committés (chunk 4a/4b/4c)

```
 M ml/api/sources_routes.py
 M ml/sources/_base/orchestrator.py
 M ml/sources/_base/steps/detect_crop.py
 M ml/tests/test_ebay_api.py
 M ml/tests/test_run_breakdown.py
 M admin/packages/web/src/features/sources/composables/useSourceDetail.ts
 M admin/packages/web/src/features/sources/pages/SourceRunDetailPage.vue
?? admin/packages/web/src/features/sources/components/FilterRulesPanel.vue
?? admin/packages/web/src/features/sources/composables/useFilterConfig.ts
```

## Décisions actées

- **`source_images.target_eurio_id`** change de sens : ce n'est plus « la
  pièce cherchée » mais « la pièce que le theme-match a attribuée au
  listing » (`None` si ambigu). Pivot du design : `price_aggregate`,
  `v_ebay_freshness`, le candidat de review lisent déjà cette colonne →
  ils marchent sans changement.
- **Limite de résultats variable** : `clamp(25 × K, 75, 200)`, K = nb de
  coins du groupe. Pagination > 200 = repoussée en V2.
- **Verdicts du routeur** : `single` (1 match), `lot` (≥2 → flag lot),
  `ambiguous` (indiscriminable → review sans cible), `no_match` (discard).
- **`zero_crops` n'est plus une erreur** : une image sans pièce
  détectable trace `crop_status='zero_crops'` sans gonfler `n_errors`.
- **Retry downloads** : 1 seule tentative au run initial (échec « simple »,
  état persisté en DB) ; `resume_failed_downloads` rejoue download → … →
  price_aggregate sur les seuls listings échoués, attaché au même run.

## Points en suspens / bugs connus

1. **Bandeau retry — vérifié OK (2026-05-22).** Le fix (bandeau hors du
   bloc `v-else-if="data"`, `snapshot` posé via `Promise.allSettled`
   avant la propagation d'erreur breakdown) est validé : endpoint
   `GET /runs/{id}` sert `n_downloads_failed`, le bandeau s'affiche.
   Vérifié sur le run `7a007d3e…` (25 downloads `failed`).
2. **Run `b5d72bf6…` — caduc.** Entre l'écriture de ce doc et la reprise,
   son état a changé : `status=success`, **0** download `failed` (les 174
   ont été rattrapés). Plus rien à rattraper. Runs avec échecs résiduels
   si besoin de tester le retry : `7a007d3e…` (25), `fdc99320…` (2).
3. La barre de tests a ~4 échecs pré-existants hors périmètre
   (`normalize_listing`, `review_lots` — OpenCV/fixtures), sans rapport.

## Chunk 5a — livré (non committé)

Relabel UI : `source_images.target_eurio_id` n'est plus « la pièce
cherchée » mais « la pièce attribuée au listing par le theme-match ».
Le libellé « Cible eBay / scrape par eurio_id » de la colonne de review
était donc faux. Livré dans `ReviewRightColumn.vue` :
« Pièce proposée » / sous-titre « attribuée au listing ». Commentaires
de `SingleReviewView.vue` alignés. Aucun changement de logique :
`_build_target_candidate()` sert déjà la bonne pièce.

## Chunk 5b — livré (non committé)

Pour les listings sans proposition (`target_eurio_id` NULL → verdict
theme-match ambigu), le payload `ReviewItem` expose désormais
`group_candidates` : toutes les 2 € commémoratives du groupe
`(pays, année)`. Reconstitué sans migration depuis
`source_images.listing_country` / `listing_year` →
`coins WHERE country=? AND year=? AND face_value=2 AND is_commemorative`.

- backend `review_queue_routes.py` : `_fetch_group_candidates()` (batch,
  1 requête par `(pays, année)` distinct), champ `ReviewItem.group_candidates`,
  peuplé dans `list_queue` quand `target_candidate is None`.
- front : section « Pièces du groupe » dans `ReviewRightColumn.vue`
  (visible si pas de proposition), event `group-select` géré par
  `SingleReviewView.vue` (même voie que la sélection libre — validable
  ⏎ directement). Quotes marché préchargées pour ces candidats.
- tests : `ml/tests/test_review_group_candidates.py` (4 cas).

## Chunk 6 — livré (2026-05-22)

- **Migration `v_ebay_freshness`** : la vue devient la *projection*
  per-eurio_id de `v_ebay_freshness_groups` (JOIN sur denom/pays/année)
  — chaque pièce hérite de la freshness de SON groupe, plus de ses seuls
  listings attribués. Sans ça, une pièce dont le groupe a bien été
  cherché mais à qui aucun listing n'a été attribué (toutes les sœurs
  l'ont capté, ou verdict ambigu → `target_eurio_id` NULL) apparaissait
  `never enriched` et la queue la re-ciblait indéfiniment. Les deux vues
  passent en `DROP VIEW`/`CREATE VIEW` (idempotent, met à jour les DB
  existantes au bootstrap). Appliqué aussi à `training.db` : 26 groupes
  enrichis → 35 pièces `fresh` (vs poignée auparavant). Test de cohérence
  `test_v_ebay_freshness_inherits_group_freshness`.
- **Docstrings « cible eBay »** alignées sur la sémantique theme-match
  (`ReviewItem.target_eurio_id`, `_build_target_candidate`, `LotDetail`,
  endpoint `/ebay/freshness`).
- **Code mort** : audit fait — **rien à retirer**. Le chemin de
  découverte per-eurio_id (`target_eurio_ids`, `_iter_subqueries`,
  résolution `target_eurio_id` → groupe dans l'adapter eBay) est un
  point d'entrée *intentionnel* de re-scrape manuel d'une pièce précise
  (`go-task ml:src:ebay:run -- --target-eurio-ids …`). Le matcher legacy,
  lui, avait déjà été retiré au cutover V2.

## Vérifs faites sur le run réel `b5d72bf6…` (6 groupes BE 2011-2016)

- 7 commémos couvertes, 1140 listings, **0 listing non attribué**.
- Attribution thème vérifiée sur la paire ambiguë BE-2016 (Child Focus vs
  Rio Olympics) : titres allemands routés correctement.
- 13 quotes prix (UNC/TTB/TB, p10/p50/p90), 455 crops tous en review_queue.
- Breakdown groupé OK après fix : affiche les 7 pièces avec leurs stats.
