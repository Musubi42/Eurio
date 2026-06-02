# Lab Streamline — cockpit d'expérience bout-en-bout

> Chantier : faire de `/lab` le point de contrôle unique du cycle de vie d'une
> expérience sur **une cohort**, de la création jusqu'au run ArcFace. Cohort
> pilote : **`mix-zone-17`** (17 commémoratives 2 €).

## Doctrine actée (2026-06-02)

**Doctrine A — train/bench split tenu.**

- **Bench / hold-out** = les **captures device** de `mix-zone-17` (photos prises au
  `/dev/capture`, pullées via `capture:pull`). Elles ne servent QUE d'évaluation
  (R@1). Jamais dans le training. Cf. `project_training_bench_split`,
  `project_crop_format_ablation`, PRD R1.
- **Training** = **Numista augmenté** (`obverse.jpg`) **+ eBay scrapé & reviewé**,
  passés par l'enrichissement (augmentation → centaines d'images/classe).

> ⚠️ Conséquence : on ne fait JAMAIS passer les captures device dans le bake/train.
> Le lab doit matérialiser ce mur (sources training ≠ sources bench).

## Le parcours cible dans `/lab`

Pour une cohort, depuis le lab, pouvoir :

0. **Reset** — purger cohorts/itérations de test (clean slate côté lab seulement).
1. **Créer la cohort depuis un CSV** (`mix-zone-17.csv` → 17 classes).
2. **Captures device** — voir la complétude (qui a ses angles), rapatrier/sync.
3. **Scrape eBay scopé à la cohort** (pas global par groupe).
4. **Review** des images eBay de la cohort (`/review`, filtres manuel/auto/IA).
5. **Enrichissement** — augmentation → centaines d'images/classe (training only).
6. **Run** — smoke (2 classes / 3 epochs, Mac) pour valider le flow, puis gros run PC.

## État des lieux (ce qui existe vs à construire)

| Étape | Existe | Trou à combler |
|---|---|---|
| 0. Reset lab | `DELETE /lab/cohorts/{id}`, delete itération | pas de purge bulk |
| 1. Cohort depuis CSV | `POST /lab/cohorts` (eurio_ids[]) | **upload CSV → parse colonne eurio_id** |
| 2. Captures device | `captures/status`, `captures/sync` (Hough→224→`datasets/{nid}/captures/`) | **réconciliation slugs** (cf. ci-dessous) |
| 3. eBay scopé cohort | scrape complet (discover→…→enqueue), MinIO | **scope `--cohort-id`** (auj. par groupe denom/pays/année) |
| 4. Review cohort | `/review` + filtres manuel/auto/IA, auto-accept Dino, Claude | **filtre cohort sur `review_queue`** |
| 5. Enrichissement | `bake` (variant_count, défaut 100) → `datasets/{nid}/augmentations/{iid}/` | overlays désactivés (Phase 2) ; brancher eBay reviewé comme source |
| 6. Run ArcFace | `launch-training` (IterationRunner : bake→train→export→bench) | smoke-run scripté à valider |

## Blocage connu — mismatch de slugs eurio_id

Le device pull existant (`app-android/debug_pull/20260429_214408/`) a été pris
**avant le renommage des slugs verbeux** (chantier D). Sur les 17 du CSV :

- ✅ **5 matchent exactement** : `at-2005-...austrian-state-treaty`,
  `fi-2016-...von-wright`, `fi-2017-...independence`,
  `fr-2008-...french-presidency`, `fr-2018-simone-veil`.
- ⚠️ **11 ont un slug divergent** (ex. `de-2020-german-polish-reconciliation`
  sur disque = `de-2020-50-years-since-the-kniefall-von-warschau`).
- ❌ **1 absente** du pull : `fr-2018-...bleuet-de-france`.

→ Avant que les 17 captures servent de hold-out : **re-pull avec le bon CSV poussé**
(propre) **ou** table d'alias slug→slug. Le smoke-run contourne en prenant 2 des 5
qui matchent. CSV marqué `# mode=ablation` : à confirmer vs le pull existant.

## Suivi des chunks

| # | Chunk | Statut | Doc |
|---|---|---|---|
| 00 | Smoke-run (2 classes / 3 epochs, flow validation) | ✅ livré | [00-smoke-run.md](./00-smoke-run.md) |
| 01 | Import CSV → cohort | ✅ livré | (csv.ts + CohortNewPage.vue) |
| 02 | Réconciliation slugs + sync captures 17 | ✅ livré (16/17, bleuet manquant) | [02-slug-reconciliation.md](./02-slug-reconciliation.md) |
| 03a | eBay scopé cohort — backend (CLI + API) | ✅ livré | [03-ebay-cohort-scope.md](./03-ebay-cohort-scope.md) |
| 03b | eBay scopé cohort — lab UI (statut + trigger) | ⬜ | — |
| 04 | Review filtrée cohort | ⬜ | — |
| 05 | Enrichissement (eBay reviewé → sources training) | ⬜ | — |
| 06 | Gros run PC (17 classes) | ⬜ | — |

### Bugs câblage trouvés+corrigés via le smoke (2026-06-02)

Le smoke run a prouvé que le flow training lab **n'avait jamais tourné end-to-end
contre eurio.db**. Trois fixes (détail dans 00-smoke-run.md) :
1. `training_runner._prepare` — itération lab restreinte à `classes_added` (cohort),
   plus `classes_after` (catalogue global).
2. `class_resolver.build_resolver` — lit **eurio.db** (`coin_refs_from_sqlite`), plus
   Supabase (doctrine SQLite-only enfin respectée côté training).
3. `training_runner._run_subprocess` — force `PYTHONPATH=ML_DIR` (subprocess robuste
   au mode de lancement du serveur).

### Migration Supabase → eurio.db (doctrine SQLite-only)

**Domaine coin-refs : ✅ TERMINÉ.** `build_resolver` + `coin_refs_from_sqlite` lisent
eurio.db ; `eval/equivalence.py` migré ; `fetch_coin_refs` (Supabase) + imports morts
`httpx`/`Iterable` **supprimés** de `class_resolver.py`. Vérifié : 689 coins / 87 design_groups,
offline. `load_env` (helper env Supabase) conservé : encore utilisé par les outils de
**projection app** (`seed_supabase`, `promote_iteration`) qui écrivent légitimement vers
Supabase = read-model Android.

**Domaine `coin_confusion_map` : ⬜ migration suivante.** Table **absente d'eurio.db**
(vit seulement dans Supabase). `zone_resolver` **dégrade proprement** (→ zone `orange` par
défaut si Supabase off) donc le training ne casse pas. Migration = ajouter la table à
eurio.db + faire écrire `eval/confusion_map.py` dedans + rebrancher les 5 consumers
(`zone_resolver`, `preview_augmentations`, `check_real_photos`, `api/server.py`,
`coins_review_routes`). Chantier séparé, hors scope lab-streamline immédiat.

Légende : ⬜ pas démarré · 🔜 prêt à lancer · 🔄 en cours · ✅ livré · ⏸️ bloqué
