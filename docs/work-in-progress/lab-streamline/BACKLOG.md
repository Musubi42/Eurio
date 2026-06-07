# Lab Streamline — Backlog

> Point de reprise du chantier. Cohort pilote : `mix-zone-17` (id `b0299ca0252b`,
> **16 coins** après drop bleuet). ML API lab = `eurio.db`, port 8042 (`go-task ml:api`).
> Détail par chunk : voir les autres `.md` de ce dossier. Mémoire : [[project_lab_streamline]].

## ✅ Fait (ne pas refaire)

| Chunk | Résultat |
|---|---|
| 00 Smoke-run | Flow training lab validé e2e (cohort→bake→train→export→bench), itération `completed` sur `smoke-2`. |
| 01 Import CSV | `CohortNewPage` importe un CSV cohort (`csv.ts`). |
| 02 Réconciliation slugs | 16/17 captures device → `eval_real_norm/<new_slug>/` + captures. Map auditable `slug-reconciliation.json`. bleuet droppé (absent du pull). |
| 03a eBay scopé cohort (backend) | `sources/cohort_scope.py` + CLI `--cohort-id` + API `RunQueryBody.cohort_id`. |
| 03b eBay lab UI (§C3) | `GET /lab/cohorts/{id}/ebay-status` + `CohortDrawerEbay.vue` (table par coin + bouton scrape). |
| 04 Review filtrée cohort | `GET /review-queue?cohort_id=` + sélecteur Cohort dans `/review` (`?cohort=`). |
| Migration SQLite-only (domaine coin-refs) | `build_resolver`, `equivalence`, **`coin_lookup`** lisent eurio.db. `fetch_coin_refs`/imports morts supprimés. |
| 3 fixes câblage training | `_prepare` (classes_added), `_run_subprocess` (PYTHONPATH), resolver (eurio.db). |

## 🔜 Reste à faire

### A. §C4 « Crop / Review » sur la page cohort (NOUVEAU — design ci-dessous)
3 cartes cliquables (Queue manuelle / Auto-accept / CCProxy) **scopées cohort**, qui
redirigent vers `/review?cohort=<id>`. Pas de traitement crop inline (éviter le bloat).

- **Backend** : endpoint de comptage triage scopé cohort. Étendre l'`ebay-status` OU
  ajouter `GET /review-queue/triage-stats?cohort_id=` renvoyant `{manual_open, auto_ready,
  ccproxy_ambiguous}` filtrés par `source_images.target_eurio_id IN cohort`. (Le triage
  global vit déjà : voir `review_queue_routes.py` triage-stats + `foundation/thresholds.py`.)
- **Frontend** : `CohortDrawerCrop.vue` (§C4), 3 cartes style ReviewPage (cf. screenshot
  cabinet), liens `/review?cohort=<id>` (et idéalement `&plateau=manual|auto|ccproxy`).
- ⚠️ Les compteurs DOIVENT être cohort-scopés (pas les 203/51/371 globaux).

### B. §C5 Enrichissement (status + déclenchement)
Vue par classe : nb de **sources réelles distinctes** (Numista `obverse`/`real_*` +
crops eBay `training_eligible`) vs cible. Flag les classes sous le seuil.

- **Doctrine images/classe (tranché cette session)** : la cible d'entraînement ~50-100
  variants/classe/epoch (défaut `variant_count`) suffit. Le **seuil qui déclenche
  l'enrichissement compte les sources RÉELLES distinctes**, pas les augmentées. Faire
  100 variants depuis 1 photo ≠ 100 vraies vues. Reco : flag classe si < ~15 réelles
  distinctes → aller chercher plus d'eBay/review pour celle-ci, puis l'augmentation
  remplit jusqu'à la cible.
- L'augmentation effective reste l'étape **I2 bake** de l'itération (déjà câblée). §C5
  est surtout informatif + peut suggérer un scrape eBay ciblé sur les classes pauvres.
- Dépendance : `training_eligible = 0` partout aujourd'hui → il faut d'abord une **passe
  de review eBay** (via §C4) pour que des crops deviennent training-eligible.

### C. eBay inclut les standards (voir prompt séparé)
`v_ebay_freshness_groups` filtre `is_commemorative = 1` → les 2 standards de la cohort
(`at-2002`, `es-1999`) sont `non_scrapable`. Élargir le scrape pour couvrir les standards.

### D. Run PC 16 classes (chunk 06)
Une fois enrichissement OK : gros run ArcFace sur les 16 (PC 1080 Ti). Smoke déjà prouvé.

## 🪙 Mission parallèle — qualité du crop (session dédiée)
Les crops eBay sont **souvent mauvais** (trop serrés, couronne coupée ; sur bimétal,
Hough accroche l'anneau interne au lieu du rim ~36 % — déjà noté `normalize_snap.py:124` ;
cas catastrophiques de sous-cercle parasite). Piste : crop multi-pass adaptatif (classifier
l'image puis adapter les params). **Statut : pas encore résolu, c'est connu et imparfait.**
Re-crop possible sans re-scrape (`--crop-pending` / `recrop_with_config.py`). Prompt de
handoff déjà fourni en session. Impacte directement la qualité de l'enrichissement (B).

## 🧭 Pour la prochaine session — pièges & patterns (lire avant de coder)

### Sources de données (le piège n°1 de cette session)
- **eurio.db (`ml/state/eurio.db`) est LA source de vérité.** Plusieurs modules pointaient
  encore vers Supabase ou un JSON legacy (`class_resolver`, `coin_lookup` lisait
  `eurio_referential.json`). **Avant de débugger un "0 / None / 404", vérifie quelle source
  le module lit.** Pattern de migration : lire eurio.db en read-only (`sqlite3.connect(f"file:{path}?mode=ro", uri=True)`).
- `coins` : `numista_id` est une **colonne directe** (pas `cross_refs.numista_id` comme l'ancien Supabase).
- `training.db` existe mais est **legacy non utilisé** par l'API lab (qui ouvre `eurio.db`).
- Migration restante : **domaine `coin_confusion_map`** (table absente d'eurio.db, vit
  encore dans Supabase ; `zone_resolver` dégrade en orange). Chantier à part.

### Subprocess / training
- Le runner lance les subprocess avec `cwd=ML_DIR` mais il faut **`PYTHONPATH=ML_DIR`**
  dans l'env (sinon `ModuleNotFoundError: eval`). Déjà fixé dans `_run_subprocess`.
- Lab iterations : label space **eurio_id** ; `--only-classes` = `classes_added` (cohort),
  PAS `classes_after` (registre global). Logs de run gzippés dans `training_run_logs`.
- **Doctrine A tenue par le code** : `prepare_dataset` ne prend que `obverse*`/`real_*` en
  train ; `val/` = device snaps (`eval_real_norm/`). Captures device = hold-out, jamais train.

### Outillage
- **Le tool Bash (zsh) casse sur les heredocs `<< 'EOF'`** → écrire un fichier temp `.py`
  et l'exécuter (`python3 /tmp/x.py`).
- **eBay = passes user-owned, manuelles.** Ne JAMAIS lancer un scrape autonome (même
  `--dry-run` consomme le quota Browse). Travailler sur les raws existants.
- Le serveur ML :8042 est celui de Raphaël, en `--reload` → les edits Python sont repris.
- Navigateur : le MCP chrome-devtools ne peut pas piloter le Chrome déjà ouvert de Raphaël
  → audit visuel à sa charge.

### Patterns front (admin web Vue)
- `vue-tsc --noEmit` a des **erreurs pré-existantes ailleurs** (audit, coins, sets) → ne
  filtrer que TES fichiers.
- Tiroirs cohort = composant `DrawerSection` (`number/title/state/summary` + slot `#body`),
  `DrawerState` = empty|partial|ready|running.
- vue-query : hooks dans `useLabQueries.ts` (`LAB_KEYS`), wrappers fetch dans `useLabApi.ts`.
  Trigger sources eBay = `POST /sources/ebay/runs {cohort_id}`.

### Donnée à trancher
- **bleuet** : numista_id diverge — CSV `134283` vs eurio.db `134685`. À vérifier au chunk catalogue.

## État git
Rien de commité (doctrine chunk-by-chunk). Fichiers touchés : voir chaque doc de chunk.
Branche : `sources-jo-wikipedia`.
