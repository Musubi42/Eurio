# Cohort Training Pipeline — eBay → images de training

> Doc vivant. Le tuyau qui transforme des annonces eBay en **images de training propres, classées par `eurio_id`**, en partant d'un set de pièces (cohorte) jusqu'à « >100 images prêtes par classe, sinon augmentation ». Source de vérité : `ml/state/eurio.db`.

Cohorte pilote : **mix-zone-17** (`b0299ca0252b`, draft, 16 classes AD/AT/BE/DE/ES/FI/FR/IT — dont `fr-2018-2eur-simone-veil`). Cockpit : `/lab/cohorts/b0299ca0252b`.

---

## Spec cible — VERROUILLÉE 2026-06-04

| Paramètre | Valeur | Note |
|---|---|---|
| Cible par classe | **> 100** images training | dépasser 100, pas un nombre exact |
| Seed primaire | crops eBay **réels validés** (`image_assets.training_eligible=1`) | reviewés + cropés |
| Facteur augmentation | **×10** par image native | 11 réels → 110 |
| Plancher réel | **~10** crops réels (« 10 % ») | sous ça, compléter via réfs |
| Filet de sécurité | réfs **Numista + BCE** (canonical obverse + BCE), aussi ×10 | garantit >100 même si eBay maigre / 0 (be-2007, es-1999) |
| Enrichissement | **= augmentation**, après **1 passe eBay unique** | pas de re-scrape en boucle par défaut |

Formule : `n_images ≈ 10 × (n_real_eligible + n_numista_ref + n_bce_ref)` doit être `> 100`.

### Décisions (déléguées au dev, actées)
- **Rescue** (`commemo_in_standard_run:{eurio_id}` & hors-cible valides) : **persist + dédup automatiques** en base ; **attribution au training en 1 clic assisté** (pas d'auto-attribution — motif heuristique, on ne pollue pas une classe).
- **Review** : **singles d'abord** (72 % de la queue = lots, faible valeur pour une classe) + **accept DINOv2 top-1 en 1 clic** pour débloquer les 95 % bloqués. **CCProxy** reste optionnel/différé (était buggé — cf. mémoire `project_claude_vision_bench`).

---

## Carte des 9 étages (+ ruptures)

`cohorte → ① discover/filtre/attribution → ② persist/text_signal → ③ download → ④ detect/crop → ⑤ resolve+DINOv2 → ⑥ review/reclassement → ⑦ export training → ⑧ enrichissement`

Code : `ml/sources/_base/orchestrator.py` + `steps/*.py` ; adaptateur `ml/sources/ebay/*.py` ; API `ml/api/*.py` ; front `admin/packages/web/src/features/{lab,bench,crop-bench,review}`.

**4 ruptures de la chaîne (état réel mix-zone-17, 2026-06-04) :**
- **A — Fin de chaîne débranchée** *(fondateur)* : `ml/training/prepare_dataset.py` lit le **FS** (`datasets/<nid>/real_*.jpg`), **pas** `image_assets.training_eligible` ; cible 100 inexistante (`_MIN_REAL_SOURCES=15` seul seuil). → les crops validés ne rejoignent jamais le dataset.
- **B — Goulot review** : 1 389 crops, **32 `training_eligible` (2,3 %)** ; pas de reviewer/CCProxy actif ; 72 % de la queue = lots.
- **C — Amont incomplet** : `be-2007` & `es-1999` = **0** scrape ; `fr-2018` affamée (59 raws → 11 crops → 0 reviewé) ; **yield crop ~25 %** (65–82 % zero_crops).
- **D — Dédup & rescue** : `discarded_listings` sans `UNIQUE(source,source_ref)` → 1 084 doublons (36 %), 92 % des rejetés absents de `discovery_log` → re-fetch infini ; rescue inexistant (mais peu de candidats dans cette cohorte car standards pas lancés).

---

## Plan d'implémentation (chunks, ordonné — R0)

> Implémentation **séquentielle** (chunks dépendants + fichiers partagés : parallèle = conflits). Blueprint précis par chunk produit par le workflow `cohort-pipeline-impl-blueprint`.

| # | Chunk | Effort | Touche (principal) |
|---|---|---|---|
| **C-1** | **Fin de chaîne : training_eligible → dataset + cible >100 (×10, seeds Numista/BCE)** *(fondateur, rupture A)* | L | `ml/training/{prepare_dataset,iteration_augmentations,iteration_runner}.py`, `lab_routes.py` |
| C0 | Dédup strict des jetées (`UNIQUE(source,source_ref)` + discovery_log) | S | `schema.sql`, `dedup.py`, `discover.py` |
| C1 | Rescue backend (`commemo_in_standard_run` → persist) + `POST /discarded/{id}/rescue` | M | `ebay/adapter.py`, `dedup.py`, `sources_routes.py` |
| C2 | `is_rescue_candidate` + `GET /lab/cohorts/{id}/discard-summary` | S | `schema.sql`, `dedup.py`, `lab_routes.py` |
| C3 | Constante `TRAINING_TARGET`=100 + `gap_to_target` + `never_scraped` | S | `lab_routes.py`, `lab/types.ts` |
| Cr | Review unblock : singles-first + accept DINOv2 top-1 1-clic | M | `review_queue_routes.py`, `features/review` |
| C4 | §C7 UI enrichissement (barre eligible/cible, CTA rescrape, badge jamais-scrapé) | S | `CohortDrawerEbay.vue`, `useLabApi.ts` |
| C5 | §C5 `CohortDrawerRescue.vue` (jetées + rescue 1-clic) | M | `CohortDrawerRescue.vue` (new), `CohortDetailPage.vue` |
| C6 | Champ `eurio_id` libre dans la review (rescue cross-classe) | S | `features/review`, `CohortDrawerCrop.vue` |
| C7 | Colonne download + statut run live | M | `lab_routes.py`, `types.ts`, `CohortDrawerEbay.vue`, `useLabQueries.ts` |
| C8 | §C6 Dédup/Déjà-vu (informatif) | S | `lab_routes.py`, drawer |
| C9 | Deeplink crop-bench scopé (`?eurio_ids=`) | S | `crop_bench_routes.py`, `CohortDrawerEbay.vue` |

Front cible : cockpit `CohortDetailPage` = §C1..§C7. On **ne fusionne pas** bench-audit / crop-bench (audiences distinctes) — deeplink scopé seulement.

---

## À tester / décider par le PO (smoke visuel, backend + dev server up)

Sur `/lab/cohorts/b0299ca0252b` (mix-zone-17) sauf indication :
- **§C7 enrichissement** : barre `n_projected/100` + gap par classe ; badge **rouge « jamais scrapé »** sur `be-2007` & `es-1999` ; bouton **Rescraper** masqué si gap=0.
- **§C5 Jetées & Rescue** : apparaît **entre §C3 et §C4** ; clic **Reclasser** sur un `commemo_in_standard_run` → crée la row `source_images` (`download_status=NULL` → à re-télécharger) ; idempotent.
- **§C6 dédup** : `n_duplicates` doit tendre vers 0 (post-migration C0).
- **Review** (`/review`) : carte **Suggestion Dino** + bouton **Accept [D]** visible si prédiction, absent sinon ; queue **singles d'abord** ; mode Libre (F) → **champ eurio_id libre** (taper `simone`/`be-2007` → rescue cross-classe).
- **Crop-bench** : bouton **« Voir qualité crops »** (§C3) → `/crop-bench?cohort=…` avec badge **Scope : mix-zone-17 (16 classes)** + cartes filtrées ; « tout voir » reset.
- **C-1 augmentation** : un bake doit produire ~100 samples pour `fr-2018-simone-veil` (seedés BCE+Numista, 0 crop eBay) et ~160 pour `at-2005` (15 eBay + réfs).

**Décisions encore ouvertes** : débit review réel pour atteindre le plancher ~10 crops/classe (sinon rouvrir CCProxy) ; faut-il auto-rescuer (vs 1-clic) les `commemo_in_standard_run`.

---

## Ordre d'exécution (conflict-aware, 2026-06-04)

`C0 → C-1 → Cr → C1 → C3 → C2 → C4 → C7 → C8 → C5 → C6 → C9`

⚠️ **WIP concurrent non-commité** sur presque tous les fichiers partagés (`lab_routes.py`, `CohortDrawerEbay.vue`, `types.ts`, `useLabApi.ts`, `useLabQueries.ts`, `review_queue_routes.py`, `crop_bench_routes.py`, `store.py`, `schema.sql`). Protocole : **édition additive**, lire le working tree avant chaque chunk. Idéalement lande/commit ce WIP avant d'attaquer les chunks qui touchent ces fichiers. Seuls `iteration_augmentations.py` (C-1), `ebay/adapter.py` + `standards.py` (C1) sont clean.

## Journal
- **2026-06-03** — Revue lecture seule du tuyau (workflow `cohort-training-pipeline-review`, run `wf_e4a3ef92-987`). Carte 9 étages + 4 ruptures + état mix-zone-17.
- **2026-06-04** — Spec verrouillée (cible >100 / plancher 10 / ×10 / enrichissement=augmentation / seeds Numista+BCE). Décisions rescue & review actées.
- **2026-06-04** — Blueprint d'implémentation (workflow `cohort-pipeline-impl-blueprint`, run `wf_bd15179b-e32`) : 12 chunks designés + ordre conflict-aware ci-dessus + carte des conflits de fichiers.
- **2026-06-04** — **C-1 cœur livré** (`ml/training/iteration_augmentations.py`, sans WIP) : réfs BCE/EUR-Lex JO injectées comme seeds (`_canonical_ref_images`), cible dynamique `_target_per_coin` (×10/source, plancher 100), `CoinAugReport` enrichi (`n_real_ebay`/`n_ref_images`/`below_floor_real`). Tests `ml/tests/test_iteration_augmentations.py` ✅ 2/2. Reste de C-1 (surface report I2 dans `lab_routes.py`) reporté au cluster lab_routes (WIP). NB : 2 échecs **pré-existants** dans `test_augmentation.py` (layer schemas/seed), hors périmètre.
- **2026-06-04** — Base remise au propre : commits `2210bb6` (snapshot WIP session concurrente) + `3042628` (C-1).
- **2026-06-04** — **11 chunks restants exécutés** (workflow `cohort-pipeline-execute`, run `wf_82f184e5-750`, séquentiel conflict-aware). Tous `done`. Commits `64414ae` (backend C0/C1/C2/C3/Cr/C7/C8/C9-backend) + `f39e766` (front C4/C5/C6/C7/C8/C9/Cr-front). **Vérif d'intégration : 0 régression** — les 21 échecs pytest + 7 erreurs TS sont **pré-existants** (fichiers non touchés ; `create_cohort` byte-identique à la base ; aucun nouveau TS dans un fichier des chunks).
  - **Effets de bord DB live** (tests des agents) : (1) migration C0 jouée sur `eurio.db` → `discarded_listings` 2979→1895 (1084 doublons supprimés, garde 1ʳᵉ occurrence ; 107 paires multi-reason réduites à 1 row), +1658 `discovery_log` en `rejected` (guards re-fetch). (2) Cr a tranché **1 item de review** en test (`n_pending` 580→579).
  - **Dette ciblée connue (follow-ups, hors périmètre des chunks)** : reject d'`image_assets` croppées (bench/review) PAS encore tracé en `discarded_listings`/`discovery_log` ; rows rescuées rétroactivement ont `storage_path/download_status=NULL` → re-download requis avant crop ; `_MIN_REAL_SOURCES` alias à retirer ; bouton bulk-rescue (`POST /sources/discarded/bulk-rescue`) à câbler ; audit multi-reason perdu sur les 107 paires dédupliquées.
- **2026-06-04** — **Quick-win lot/single livré.** Routing `enqueue._kind_for_source_image` via `listing_text_signals.listing_kind` (au lieu du seul `is_lot_suspected` FR/EN) + vocabulaire **multilingue enrichi** dans `text_signals/dictionaries.py` (DE/ES/IT/NL : KMS/Kursmünzensatz/Satz/cofre/cartera, compteurs `N valores/piezas/münzen/stück`, plage `1 cent–2 euro`). Bench : faux-single **12→4** (résidu = détecteur-only), faux-lot ~1→4 (surtout listings réellement multi vus de 1 photo + 1 « aus KMS »). Multi-années **testé puis retiré** (sur-captait les « pick your year » = 1 pièce). Backfill `scripts/backfill_listing_kind_routing.py` (idempotent, dry-run par défaut) appliqué cohorte : 175 `listing_kind` reclassés, **9 single→lot** re-routés (dont `aae133f1fa` Austria+Italia ✓), `review_queue.kind` aligné. Tests `tests/test_lot_detection.py` ✅ 14/14. **Reste = chantier détecteur visuel** (les 4 résidus « titre nomme 1 / image en montre N » + le rappel 55 % zéro-crop sur emballé).
- **2026-06-04** — **Bug lot/single investigué + bench census v0** (cf. [coin-census-bench.md](./coin-census-bench.md)). Règle actuelle (`enqueue._kind_for_source_image`) = titre `LOT_PATTERNS` (FR/EN) OU `n_crops>1` ; échoue car le détecteur sous-détecte (55 % `n_crops=0` sur pièce visible) et le regex titre rate les lots IT/ES/DE/énumérés. Census LLM-vision (110 raws) : **48 % des vrais lots mal classés single/pending** (training poison), **13/13 ont un titre de lot explicite** (`3x`/`KMS`/`VALORES`/multi-pays). Design retenu : règle titre **étroite** multilingue (quick win ~0 FP) + détecteur visuel `propose→verify→fusion-identité(avers/revers)→dedup→count` (vrai chantier, bench-first).
- **2026-06-04** — **Détecteur visuel census : mesuré → designé → v1 → audité → CLÔTURÉ** (cf. [census-detector-design.md](./census-detector-design.md)). Commits `25fb85f`/`959961c`/`fe276b1`/`674a4c7`. (1) **Plafond sans entraînement** (3-way YOLO-low/FastSAM-DINO/baseline, harnais `scripts/measure_census_ceiling.py`) : le **rappel est résolu off-the-shelf** — YOLO existant @conf 0.10 récupère **89 %** des 55 % zéro-crop et tue le faux-single **48 %→0 %** (c'était conf=0.35+filtres stricts qui jetaient des pièces visibles). SAM2/entraînement non justifiés. (2) **v1 livrée = `yolo@0.10 + ① nms_only`** (`scan/census.py`, banque DINO coin-ness, `tests/test_census.py` 10✅) : domine yolo brut, **poison 0 %**, faux-lot 64 %=review. (3) **Gate is-coin ② NON adopté** : échange poison↔faux-lot 1:1 ; **audité** (workflow 4 Sonnet `wf_a95d6db2-8fa`, bugs R0 corrigés) ; **extension banque (cause B) testée = négatif**. **Plateau acté (PO), sous-chantier clos.** Câblage prod de `nms_only` différé.
- **2026-06-05** — **Cockpit fiabilisé (4 chantiers WS, branche `sources-jo-wikipedia`, non commités).** Déclencheur PO : « rien ne bouge » dans le cockpit. Diagnostic empirique (base live, backend orphelin `--reload` mort depuis ~19h = servait du code figé) : la persistance des reviews MARCHAIT, mais 4 défauts d'affichage/câblage trompaient.
  - **WS2 — Enrichissement dynamique** : fin du `×10` codé en dur (3 endroits) + incohérence de seed affichage↔bake. Helper unique `foundation/enrichment.py` (`facteur = ceil(100/seed)`, `projection`, `MIN_REAL`, `CANONICAL_REF_SOURCES`). `lab_routes._cohort_funnel_status` expose `n_seed`/`aug_factor`/`below_real_floor` ; `iteration_augmentations._target_per_coin` utilise la même formule. Front : « **N img · {seed} réels ×{facteur}** » + jauge seed vs plancher 10. Ex at-2005 : 22 réels ×5 = 110 (avant 220/100). Tests `test_iteration_augmentations` réécrits ✅.
  - **WS3 — Rescue sœurs visible** : `funnel-status.rescued_to_sisters` (crops `training_eligible=1` scrapés sous un groupe cohort mais réattribués à une pièce sœur hors-cohort — 19 crops / 9 sœurs sur mix-zone-17). Lane neutre dans `CohortDrawerEbay`. Jamais comptés dans le seed d'une pièce cohort.
  - **WS4 — Recrop relibellé** : `_coin_tail.n_zero_crops` exposé ; bouton par pièce diagnostiqué (**Reviewer N** / **Recropper N** / **Scraper|Rescraper**) au lieu du « rescrape » no-op. Cœur recrop extrait dans `scan/recrop_zero.py` (partagé CLI `recrop_cohort_census` + nouvel endpoint background `POST /lab/cohorts/{id}/coins/{eurio_id}/recrop-zero`, additif, sans quota eBay).
  - **WS1 — Lanes de review PERSISTÉES** *(le cœur)* : colonne `review_queue.lane` (`manual|auto_accept|ccproxy`) + `lane_source` (`auto|human`, sticky) — fini l'heuristique recalculée à l'affichage. Règle de routage centralisée `foundation/review_lanes.py` (`auto_candidate→auto_accept`, `partial+divergent→ccproxy`, `unknown→manual`). Écrite à l'enqueue + re-route post-Dino (jamais les `human`). Backfill `scripts/backfill_review_lanes.py` (2645 items : manual 469 / auto 158 / ccproxy 2018). Endpoints : filtre `lane` sur `GET /review-queue`, `triage-stats.by_lane` (compte SQL, plus de recompute), `POST /{id}/move-lane` (→manual sticky), auto-accept filtre `lane='auto_accept'` + décochés→manual, ccproxy batch filtre `lane='ccproxy'`. Front : 3 cartes lisent `by_lane`, carte manuelle deep-linke `?lane=manual`, bouton « Faire en manuel » dans `SingleReviewView`. Tests `test_review_lanes` ✅. Migration pré-bootstrap (idempotente) + `schema.sql`. Backup `eurio.db.bak-pre-lanes`.
  - **Vérif intégration** : helper/lane/lot/census/augmentation tests ✅ ; smoke live OK (`by_lane` {manual:6, auto:6, ccproxy:217} cohort-single ; move-lane round-trip sticky). **2 échecs pytest pré-existants** confirmés par stash (`test_orchestrator` FK price_aggregate coins-vide, `test_review_lots_api` détection-sur-raw) + 7 erreurs TS pré-existantes — hors périmètre. **Reste : audit visuel PO + WS5 (mini-bench ccproxy 5-10 crops avec oracle humain avant le volume).**
