# HANDOFF — « Reprendre une cohorte jusqu'à l'entraînement »

> Pour une nouvelle session Claude Code (repo Eurio). Auto-suffisant, **preuve-first**.
> Écrit 2026-06-15. Cartographie produite par 5 explorations parallèles du code + `ml/state/eurio.db`.
>
> **Méthode de lecture (cf. `feedback_handoff_quality`)** : tout chiffre ci-dessous est daté du 2026-06-15 sur la DB locale. **Re-vérifie sur données réelles avant d'agir** — les requêtes SQL de §8 sont faites pour ça. Les pointeurs `fichier:ligne` peuvent avoir bougé : confirme par grep.

---

## 0. Ta mission

Vérifier qu'on peut **reprendre une cohorte** (ex. `mix-zone-17`) et la mener **bout-en-bout** : eBay → download → crop → probe → recrop → routing (auto-accept / ccproxy / manuel) → **assez d'images par classe** → **entraînement** → modèle qui reconnaît. Dire ce qui est prêt, ce qui manque, ce qu'on peut améliorer, et si le `work-in-progress` est utile.

## 1. TL;DR — verdict

**On ne peut PAS lancer un training utile sur `mix-zone-17` aujourd'hui.** Le pipeline d'acquisition marche, mais :

- **Goulot #1 — débit de review** (le vrai blocage). Cible = **100 images entraînables/classe** (`ml/training/foundation/enrichment.py:8-13`). Réel mix-zone-17 : **0/16 classes** atteignent 100 ; moyenne ~26, max 90 (`at-2005`), min **0** (`be-2007`). Les crops EXISTENT mais attendent une décision : ex. `de-2020` = 117 images totales, **17 éligibles**, 72 en `needs_review`. → il faut **trancher la queue** (manuel + ccproxy + auto-accept), pas re-scraper.
- **Goulot #2 — la cohorte ne définit PAS les classes du training**. Une cohorte pilote l'**enrichissement eBay** + le **bench hold-out** ; mais les classes d'un run viennent de `training_staging` (séparé). Ce **joint** (cohorte → staging) n'est pas automatique. Voir §6.
- **Blocages secondaires** : bug zero_crops EMU/globe non résolu (WIP non committé) ; standards d'une cohorte non scrapés ; `auto_validate` peut être silencieusement skippé si banque d'ancres absente.

**En clair** : l'acquisition est bonne ; ce qui manque pour fermer la boucle = **du débit de décision** + **brancher la cohorte sur le staging du training** + finir 2-3 trous.

---

## 2. La pipeline, étage par étage (eBay → review)

Orchestrateur : `ml/sources/_base/orchestrator.py::run_pipeline()`. Lancé par `go-task ml:src:ebay:run` (qui pose `EURIO_CENSUS_RECOVER=1`).

| # | Étape | Fichier | Écrit en DB |
|---|---|---|---|
| 1 | **Discover** (Browse API, par groupe `(denom,pays,année)` ; EBAY_DE + EBAY_ES ; theme-match) | `steps/discover.py:71` → `ebay/adapter.py:162` | `discovery_log`, `discovery_searches`, `discarded_listings` |
| 2 | **Persist** (dedup `UNIQUE(source,source_ref)`) | `steps/persist.py:35` | `source_images` |
| 2.5 | **Text-signal** (regex titre → `listing_kind`, `condition`, `sold_qty`) | `steps/text_signal.py` | `listing_text_signals` |
| 3 | **Download** raw → MinIO `enrichment-raws` | `steps/download.py:47` | `source_images.storage_path/status` |
| 4 | **Detect & Crop** (multi-Hough + YOLO-low → `nms_concentric` → **gate probe `face_scores`** τ≈0.065 → **recovery `score_recover.recover_crop`** si vide) | `steps/detect_crop.py:90` → `vision/normalize_snap.py:1094`, `vision/census.py`, `vision/score_recover.py` | `image_assets`, `source_images.crop_status` (`success`/`zero_crops`/`error`), `detections_json` |
| 5 | **Resolve** (phash dedup ; sinon `needs_review`) | `steps/resolve.py` | `image_assets.resolution_status`, `pending_quotes` |
| 5.5 | **Auto-validate DINOv2** (embedding vs banque d'ancres → face/denom + top-k) | `steps/auto_validate.py::run_auto_validate_dino` | `image_asset_dino_predictions`, `image_assets.face/denom` |
| 6 | **Enqueue** (pre-gates face=reverse / denom=not_2eur → reject ; sinon `consensus_verdict` → **lane**) | `steps/enqueue.py:201` | `review_queue`, `consensus_verdicts` |
| 7 | **Price aggregate** (single only, par tier) | `steps/price_aggregate.py:61` | `coin_market_quotes` |

**Crops & probe** (les briques qu'on a améliorées cette semaine, cf. `[[project_review_improvements]]` / `[[project_score_guided_recovery]]`) :
- Probe = `vision/census.py::face_scores` (régression logistique sur embedding DINO → P(pièce entière) ∈ [0,1], `fragment_face_probe.npz`).
- Recovery score-guided = `vision/score_recover.py::search_best_crop` (balaye rayon ± centre, garde le meilleur scoré). `EURIO_CENSUS_RECOVER=1`.
- `crop_status` réel (2026-06-15) : `zero_crops=3178`, `success=2788`, `NULL=1660`.

---

## 3. Routing en lanes & image entraînable

**Lane** posée à l'enqueue par `ml/review/validation/consensus.py::consensus_verdict` :
- `strong_accept` → **auto_accept** (l.81) · `no_signal`/`dual_contradict`/défaut → **manual** (l.60,66,314) · `crop_cap`/`text_contradict_rescue`/`dino_mismatch`/`partial` → **ccproxy** (l.73-105).
- Pre-gates `enqueue.py` : `face=reverse` (l.258) / `denom=not_2eur` (l.283) → reject terminal.
- Override humain `/move-lane` → `lane_source='human'` (sticky, l'auto-triage ne le retouche pas, `auto_validate.py:789`).

**Une image devient entraînable** quand une décision (humain, auto-accept batch, ou Claude-ack) pose :
```
image_assets.training_eligible = 1  AND  resolution_status = 'manual'
```
(les 3 chemins : `review_queue_routes.py:1889`, `:3589`, `:4154`). `eurio_id` + `face` écrits dans le même UPDATE. ⚠️ `auto_accept`/`auto_dino` ne sont PAS des valeurs de `resolution_status` — tout résolu = `'manual'`.

**Rejetés** : `resolution_status='rejected'`, récupérables via `/restore` (→ `needs_review`, `training_eligible=1`, lane manual, exclus de l'auto-triage). **Skippés** : juste `priority+=50` + `decision_notes='skipped'`, l'item reste `open`.

État DB (2026-06-15) : `needs_review=2345`, `manual=1011` (dont **973 training_eligible**), `rejected=1362`, `pending_match=297`, `auto_phash=81`.

---

## 4. Cycle de vie d'une cohorte

Table **`experiment_cohorts`** (`ml/store/cohorts.py`) : `eurio_ids_json` (liste dénormalisée, PAS de join), `status ∈ {draft, frozen}`, `zone`, `frozen_at`. `cohort_jobs` (scrape_ebay / recrop_zero / census_recover, avec `pid` anti-orphelin). ⚠️ `cohort_members` existe mais **0 ligne** = schéma mort.

- **Créer** : `POST /cohorts` → `create_cohort()`.
- **Geler** : automatique + **irréversible** au 1er `POST /cohorts/{id}/iterations` (`lab_routes.py:578-581`). Pas d'endpoint freeze explicite.
- **Reprendre / modifier une frozen** : `POST /cohorts/{id}/clone` → nouveau draft mêmes eurio_ids (`lab_routes.py:507`).
- **Scope eBay** : `ml/sources/cohort_scope.py:44::cohort_ebay_groups` expand eurio_ids → `(denom,pays,année)` (commémo) / `(denom,pays)` (standard) ; variantes EU marquées `non_scrapable`.
- **Scope review/funnel** : `GET /cohorts/{id}/funnel-status`, `discard-summary`, `rescue-candidates`, `dedup-status` (scopés par eurio_ids).

**Cohortes réelles (2026-06-15)** :

| id | name | status | eurio_ids | notes |
|---|---|---|---|---|
| `b0299ca0252b` | **mix-zone-17** | draft | 16 | la + vivante (jobs scrape/recrop réels) |
| `587ed48dc06e` | smoke-2 | frozen | 2 | 1 iteration complète (preuve bout-en-bout minimal) |
| `be-2eur-standard-obverse-eval` | (idem) | frozen | 5 | id = slug ; `frozen_at` NULL (bootstrap hors-API) |

---

## 5. Le point critique : assez d'images par classe ?

**Cible = 100 images entraînables/classe** (`ml/training/foundation/enrichment.py:8-13`).

Distribution réelle **mix-zone-17** (toutes source `ebay_wild`, 2026-06-15) — voir requête §8.A :

```
at-2005 austrian-state-treaty .... 90      de-2020 reconciliation ... 17
fr-2008 presidency ............... 41      ad-2014 .................. 17
it-2016 plautus .................. 37      fr-2018 simone-veil ...... 16
fr-2016 mitterrand ............... 32      es-1999 juan-carlos-i .... 9   (STANDARD)
es-2016 segovia .................. 30      at-2002 .................. 5   (STANDARD)
it-2016 donatello ................ 28      be-2007 albert-ii ........ 0
be-2011 womens-day ............... 25
fi-2017 100-years ................ 24      → 0/16 classes ≥ 100. Moyenne ~26.
fi-2016 von-wright ............... 22
de-2007 mecklenburg .............. 20
```

**Diagnostic (clé)** : ce n'est **pas** un manque d'acquisition. Exemples :
- `de-2020` : **117** images totales, **17** éligibles → 72 en `needs_review` non décidées.
- `fi-2016` : 168 totales, 22 éligibles. `fi-2017` : 148 totales, 24 éligibles.
- `be-2007` : 108 totales, **0** éligible (72 needs_review, 27 rejected).

→ **Le travail manquant = trancher la queue** (le débit humain/Claude), pas relancer eBay. **Quantifié (vérifié 2026-06-15 via §8.A) : ~594 items `needs_review` en attente de décision sur cette seule cohorte** — c'est ça qu'il faut écouler. Les 2 standards (`at-2002`, `es-1999`) sont bas parce que **non scrapés** (cf. `lab-streamline/05-ebay-standards.md`, PLANIFIÉ). (Les chiffres exacts bougent au fil de tes reviews — relance §8.A.)

---

## 6. De la cohorte à l'entraînement (le joint non-évident)

**Une cohorte ne définit PAS directement les classes d'un run de training.** Deux mondes :

- **Classes du run** = `training_staging` (table eurio.db : `class_id, class_kind, aug_recipe_id`). L'UI `/training` diff la staging vs le dernier run. État : **7 classes stagées** (2026-04-30, possiblement périmées vs mix-zone-17).
- **Cohorte** = pilote l'**enrichissement eBay** + le **bench hold-out** (captures device), via `experiment_iterations` (FK `cohort_id`). Snapshot des eurio_ids au gel.

⚠️ **À clarifier dans la session** : comment on passe des eurio_ids d'une cohorte → `training_staging` pour lancer un run sur exactement ces classes. C'est le maillon le moins documenté/automatisé.

**Label ArcFace** = `COALESCE(coins.design_group_id, eurio_id)` (`ml/training/eval/class_resolver.py:1-9`). `class_kind` ∈ {`design_group_id`, `eurio_id`}.

**Split training / bench** (deux mécanismes disjoints) :
- eBay wild → flag `image_assets.training_eligible` (995 à 1 en DB).
- Captures device (cohorte) → bench seulement. Garde **hard-fail** `train_embedder.py:56-74` (`SystemExit("Data leak detected")` si un path training résout vers `ml/data/real_photos/`). Convention de nommage : training = `obverse*.jpg`/`real_*.jpg` dans `datasets/<numista_id>/` ; bench = `ml/data/real_photos/`.

**Entrée training** : `ml/training/pipeline.py::TrainingPipeline.run()` (6 étapes : suppression → prepare → train arcface → embeddings → seed Supabase → validate per-class). Lancée par l'UI `/training` (les `go-task ml:train*` sont des raccourcis CLI). ⚠️ `model_classes` est **Supabase-only** ; en eurio.db c'est `training_run_classes`.

---

## 7. Checklist « prêt à entraîner » + trous

**Gates réels** (`prepare_dataset.py`, `train_embedder.py`, `pipeline.py`) :
1. `datasets/<numista_id>/obverse.jpg` ou `real_*.jpg` présent par classe stagée.
2. Classe stagée a un `numista_id` connu (sinon skip **silencieux**).
3. ≥1 classe en `training_staging` (sinon `SystemExit`).
4. Aucun path → `ml/data/real_photos/` (garde anti-fuite).
5. `m_per_class=4` images/classe minimum **après augmentation** (sinon le sampler PyTorch crashe **en cours de run**).

**Trous / risques (à traiter ou acter)** :
1. **Pas de gate « min images/classe »** avant lancement → une classe pauvre crashe le sampler en plein run. **Recommandé** : un preflight qui refuse/averti < seuil (réutiliser la requête §8.A).
2. **Débit de review** = le vrai blocage (§5). Pistes : lancer un **batch ccproxy** (Claude) sur les `partial`/`divergent`, et l'**auto-accept** sur les convergents, pour vider sans tout faire à la main.
3. **Bug zero_crops EMU/globe** non résolu (`crop-rim-overfit/HANDOFF.md`, ~61% sur certains runs AT) — WIP non committé. Réduit l'acquisition sur les bimétal à gros motif central.
4. **Standards non scrapés** (`at-2002`, `es-1999`) → `lab-streamline/05-ebay-standards.md`.
5. **`auto_validate` (step 5.5) silencieux si banque d'ancres absente** → face/denom/Dino vides → tout part en manuel. Vérifier `image_asset_dino_predictions` se remplit (§8.D).
6. **1660 `source_images` en `crop_status=NULL`** (jamais croppées : `download_only` non suivi, ou raws pré-pipeline). À re-cropper (`--crop-pending <RUN_ID>`) si récupérables.
7. **Anchors DINO non reliés au cycle training** : après un run / un renommage de slug, rebuild **manuel** obligatoire sinon la review Dino casse (top1 → eurio_id mort) : `go-task ml:dino-anchors:build -- --force [--kind 2eur_commemo|2eur_all]` puis `ml:dino-predictions:backfill -- --force --kind ...`.
8. **Merge DB Mac↔PC manuel** si training sur PC (`ml/README-training.md`).
9. **Joint cohorte → training_staging non automatisé** (§6).

---

## 8. Vérifs à lancer (copier-coller)

> DB locale : `ml/state/eurio.db`. Acquérir le verrou MinIO d'abord si serveur canonique (cf. `deployment-topology.md`). Backup avant toute mutation.

### A. Images entraînables par classe pour une cohorte
```sql
WITH cohort_ids AS (
  SELECT value AS eurio_id
  FROM experiment_cohorts, json_each(eurio_ids_json)
  WHERE name = 'mix-zone-17'           -- ← change la cohorte ici
)
SELECT ia.eurio_id,
       COUNT(*) FILTER (WHERE ia.training_eligible=1 AND ia.resolution_status='manual') AS eligible,
       COUNT(*) FILTER (WHERE ia.resolution_status='needs_review')                      AS pending,
       COUNT(*)                                                                          AS total
FROM image_assets ia
WHERE ia.eurio_id IN (SELECT eurio_id FROM cohort_ids)
GROUP BY ia.eurio_id
ORDER BY eligible ASC;   -- les classes à débloquer en premier en haut
```
Lis : `eligible` vs 100. Si `pending` est gros → c'est du **débit de review** (pas d'acquisition).

### B. État du funnel cohorte (API)
```bash
curl -s "http://127.0.0.1:8042/cohorts/<COHORT_ID>/funnel-status" | python3 -m json.tool
```

### C. Répartition lanes restantes (à trancher)
```bash
curl -s "http://127.0.0.1:8042/review-queue/triage-stats" | python3 -m json.tool   # by_lane = vérité
```

### D. auto_validate tourne bien ? (sinon tout part en manuel)
```sql
SELECT anchors_kind, COUNT(*) FROM image_asset_dino_predictions GROUP BY anchors_kind;
-- attendu : 2eur_all + 2eur_commemo non vides
```

### E. crops jamais traités
```sql
SELECT crop_status, COUNT(*) FROM source_images GROUP BY crop_status;
```

## 9. Commandes clés
```bash
go-task ml:src:ebay:run -- --cohort-id <ID>      # scrape+crop scopé cohorte (CENSUS_RECOVER=1)
go-task ml:src:ebay:run -- --crop-pending <RUN>  # re-crop des raws non croppés
go-task ml:src:ebay:status                       # quota eBay + derniers runs
go-task ml:dino-anchors:build -- --force --kind 2eur_all   # APRÈS train/rename
go-task ml:dino-predictions:backfill -- --force --kind 2eur_all
go-task ml:train-arcface                          # raccourci CLI (sinon UI /training)
go-task ml:db:sync                                # push eurio.db → MinIO (sans relâcher le verrou)
```

## 10. À lire (dans l'ordre)
1. `docs/operations/deployment-topology.md` — qui tourne où (verrou eurio.db).
2. `ml/README-training.md` — protocole Mac/PC.
3. `docs/work-in-progress/cohort-pipeline/README.md` — pipeline complet + 4 ruptures (LIVRÉ-WIP, indispensable).
4. `docs/work-in-progress/cohort-pipeline/COCKPIT-DEBUG-HANDOFF.md` — état cockpit `/lab` (bugs).
5. `docs/work-in-progress/lab-streamline/BACKLOG.md` — reste à faire + pièges.
6. `docs/work-in-progress/autovalidation-redesign.md` — modèle verdict/lane actuel.
7. `docs/work-in-progress/crop-quality-overhaul/00-diagnostic-and-architecture.md` — état crop eBay.
8. `docs/work-in-progress/crop-rim-overfit/HANDOFF.md` — bug zero_crops EMU/globe (actif, non committé).

⚠️ **Périmés / ne PAS suivre** : `docs/research/training-guide.md`, `docs/research/detection-pipeline-unified.md` (partie crop), `cohort-pipeline/REBUILD-*.md`, `crop-forensics/*`, `docs/research/ml-scalability-phases/`. `collaborative-review/README.md` dit « conception » mais le code est livré (lire `09-vps-deploy.md`).

## 11. Note de contexte
Branche `sources-jo-wikipedia` : l'arbre contient du **WIP multi-sessions non committé** (crop-rim-overfit `/fragment-audit`, etc.) en plus des 3 commits review livrés ce 2026-06-15 (perf crop editor, fix queue manuelle, Dino rank + auto-crop). Ne stage que tes fichiers. La review admin marche bien maintenant — le maillon faible de la boucle cohorte→training est **le débit de décision** + le **joint cohorte→staging**.
