# Glossary

> Vocabulaire de la pipeline d'entraînement. Lis-le avant de plonger
> dans un sprint si tu reprends en cold start.

## Concepts métier

**Cohort** — sélection figée de pièces (eurio_ids) sur laquelle on itère.
Status `draft` (éditable) ou `frozen` (au 1er training launch). Une cohort
porte ses captures device et N iterations.

**Iteration** — un essai reproductible dans une cohort. Porte une recipe,
un seed, un snapshot d'augmentations sur disque, un training run, un
benchmark studio, une comparaison aug↔réelles, un APK cohortTest, des
live tests device.

**Recipe** — DSL d'augmentation (voir `ml/recipes/` ou la table
`augmentation_recipes`). Définit les transformations appliquées aux images
source pour produire les augmentations utilisées en training.

**Capture device** — photo prise avec l'app Eurio en mode debug, normalisée
par `scan/normalize_snap.py` (Hough → tight crop → black mask → 224×224).
Canonique par pièce, partagée entre toutes les iterations d'une cohort qui
contient cette pièce.

**Augmentation** — image générée par la recipe à partir des sources Numista
(et/ou des captures, selon la recipe). Stockée sur disque par iteration.

**Studio benchmark** — R@1/R@3/R@5 calculé sur les captures device avec
le modèle entraîné de l'iteration. Mesure interne, conditions contrôlées.

**Live test** — snap one-shot pris sur device avec l'app cohortTest dans
une condition prescrite (`bright`, `dim`, `tilt`). Log JSONL local, sync
vers admin pour analyse.

**Distance aug↔réelles** — cosine similarity entre centroid des
augmentations et centroid des captures, dans l'espace **DINO** (modèle
externe stable, pas l'ArcFace de l'iteration). Mesure si la recipe
ressemble visuellement à la réalité device.

## Concepts technique

**eurio_id** — slug canonique d'une pièce (ex: `fr-2007-2eur-standard`).
Norme cible du référentiel.

**numista_id** — id Numista (entier). Reliquat du début du projet, encore
utilisé pour les paths disque sous `ml/datasets/<numista_id>/`. Migration
vers `<eurio_id>` deferred.

**design_group_id** — id de regroupement de pièces partageant le même
design (ex: re-éditions, joint issues). Quand présent, l'ArcFace est
entraîné avec ce label au lieu d'`eurio_id`. Cf mémoire utilisateur
"ArcFace label = design_group".

**ArcFace** — modèle d'embedding de pièces, entraîné par iteration. Output
192-dim. Inférence on-device via TFLite.

**DINO** — modèle d'embedding pré-entraîné (DINOv2). Utilisé pour la
confusion map et la distance aug↔réelles. Pas réentraîné, sert d'étalon
visuel neutre.

**App full** — l'app Android complète actuellement en dev. `applicationId
= com.musubi.eurio`. Embarque vault, profile, scan, onboarding, etc.

**App cohortTest** — flavor Gradle dédié, `applicationIdSuffix =
.cohorttest`. Scan-only, embedded model, embedded catalog filtré, pas de
Supabase. Build par cohort+iteration.

**Capture protocol** — les 6 conditions fixes du capture device :
`bright_plain`, `dim_plain`, `daylight_plain`, `bright_textured`,
`tilt_plain`, `close_plain`. Définies dans `CaptureProtocol.kt`.

**Live test conditions** — les 3 conditions des live tests on-device :
`bright`, `dim`, `tilt`. Hardcoded (D-008). Distinctes du capture protocol :
moins de conditions, plus rapide à exécuter.

## Endpoints (préfixe API)

Tous sous `/lab/` pour la pipeline cohort, sauf training/benchmark
historiques.

- `/lab/cohorts` — CRUD cohorts
- `/lab/cohorts/{id}/coins` — mutation pièces (draft only)
- `/lab/cohorts/{id}/captures/*` — capture flow (acté)
- `/lab/cohorts/{id}/iterations` — création/listing
- `/lab/cohorts/{id}/iterations/{iid}` — detail
- `/lab/cohorts/{id}/iterations/{iid}/stop` — sprint 1, stop training
- `/lab/cohorts/{id}/iterations/{iid}/augmentations` — sprint 1, generate/list
- `/lab/cohorts/{id}/iterations/{iid}/aug-vs-real` — sprint 2
- `/lab/cohorts/{id}/iterations/{iid}/test-app/build-info` — sprint 3
- `/lab/cohorts/{id}/iterations/{iid}/live-tests/*` — sprint 4

## Files & paths réguliers (références rapides)

| Quoi | Où |
|---|---|
| Captures device canoniques | `ml/datasets/<numista_id>/captures/<step>.jpg` |
| Augmentations par iter | `ml/datasets/<numista_id>/augmentations/<iid>/sample_*.jpg` |
| SQLite ML state | `ml/state/training.db` |
| Cohort CSV | `ml/state/cohort_csvs/<slug>.csv` |
| Live test logs | `ml/state/live_test_logs/<iid>.jsonl` |
| Cohort test bundle | `ml/output/cohort_test_<iid>/` |
| App scope on device | `/sdcard/Android/data/<applicationId>/files/Documents/` |
