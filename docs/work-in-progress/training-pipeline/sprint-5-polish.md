# Sprint 5 — Polish : dashboard cross-cohort + GC + doc finale

> Durée estimée : 2 jours
> Pré-requis : Sprints 1-4 complets. La pipeline marche end-to-end pour
> 1 cohort, ce sprint la rend supportable à long terme.
>
> **Cold start** : lis `vision.md` pour rappel global, `decisions.md`
> entièrement (toutes les décisions cumulées), `progress.md` pour voir
> l'état du repo après les 4 sprints.

## Goal

Trois choses :
1. **Cross-cohort dashboard** : vue agrégée pour comparer recipes/cohorts
   à grande échelle (récup l'ancienne valeur de `/benchmark` sans le
   confondre avec le pilotage cohort).
2. **Garbage collect des augmentations et bundles** : empêcher que le
   disque sature à mesure qu'on accumule iterations.
3. **Doc utilisateur finale** : workflow complet step-by-step dans un
   `docs/training-pipeline/USER_GUIDE.md` (différent du vision.md, plus
   tutoriel).

## Scope

### Inclus

- Page `/lab/dashboard` (ou intégrée à `/lab` home) :
  - top recipes par R@1 live moyen
  - pièces "difficiles" (low live R@1 sur N iterations différentes)
  - distribution des distances aug↔réelles globalement
- Endpoint `DELETE /lab/cohorts/{cid}/iterations/{iid}/augmentations`
  + bouton "Purger augmentations" en iteration detail (read-only après)
- Job de cleanup automatique : à la création d'une nouvelle iteration
  dans une cohort `frozen` qui dépasse N iterations (e.g. 5), proposer
  la purge des plus anciennes failed
- Suppression définitive de la route `/benchmark` et de la page
  `BenchmarkPage.vue`
- `USER_GUIDE.md` orienté "comment je crée et fais avancer une cohort"

### Exclus

- Multi-utilisateur (toujours hors-scope)
- Auto-tuning de recipes basé sur les métriques (idée pour plus tard)

## Tasks

### A. Dashboard cross-cohort (~1 jour)

1. **Endpoint** `GET /lab/dashboard` :
   - `top_recipes`: agrégation recipe_id × moyenne live R@1 sur toutes
     les iterations qui l'ont utilisée
   - `difficult_coins`: coins avec live recall_at_1 moyen < 0.5 sur ≥3
     iterations
   - `distance_distribution`: histogramme des cosines aug↔réel sur toutes
     les iterations
2. **Composant** `LabDashboardPage.vue` :
   - 3 cartes (top recipes, difficult coins, distance distrib)
   - liens vers les iterations concernées
3. **Routing** : `/lab/dashboard` accessible depuis le top de `/lab` home
   (lien discret, pas un menu principal séparé).

### B. Garbage collect (~½ jour)

4. **Endpoint** `DELETE /lab/cohorts/{cid}/iterations/{iid}/augmentations`
   - 409 si l'iteration est `running`
   - sinon : `shutil.rmtree` du dossier sous `<numista_id>/augmentations/<iid>/`
     pour chaque pièce de la cohort
5. **Endpoint** `DELETE /lab/cohorts/{cid}/iterations/{iid}/test-bundle`
   - efface `ml/output/cohort_test_<iid>/`
6. **UI** : boutons "Purger" dans iteration detail (sous §3 et §5
   respectivement), avec confirm dialog.
7. **Auto-cleanup soft** : à la création d'une iteration dans une cohort
   ayant ≥5 iterations dont au moins 2 `failed`, afficher un banner "5
   iterations dans cette cohort, X MB d'augmentations stockées. Purger
   les `failed` ?".

### C. Suppression définitive `/benchmark` (~½ jour)

8. Retirer la route `/benchmark` du router
9. Supprimer `admin/packages/web/src/features/benchmark/` (composables,
   pages, types) — vérifier qu'aucun import résiduel.
10. Marquer `docs/augmentation-benchmark/` comme legacy (déplacer ou
    archiver, NE PAS supprimer — l'historique compte).

### D. User guide (~½ jour)

11. **`docs/training-pipeline/USER_GUIDE.md`** orienté tutorial :
    - "Tu veux entraîner un nouveau modèle, voici comment"
    - étape 1 à 13 du flow A→Z (cf vision.md) avec captures d'écran
      stylisées en ascii ou liens vers la page admin réelle
    - troubleshooting : "Si tu vois X, c'est que Y, fais Z"
    - check-list de ce qui doit marcher avant de claim une iteration
      "validée" (R@1 studio ≥ X, live R@1 ≥ Y, distance aug↔réel ≥ Z)

## Files à toucher

### Backend
- `ml/api/lab_routes.py` — 2 endpoints DELETE + dashboard endpoint
- `ml/api/dashboard_logic.py` (ou inline) — agrégations

### Front
- `admin/packages/web/src/features/lab/pages/LabDashboardPage.vue`
- `admin/packages/web/src/features/lab/composables/useLabQueries.ts` —
  hooks dashboard
- `admin/packages/web/src/app/router.ts` — route dashboard, suppression
  benchmark
- Suppression : `admin/packages/web/src/features/benchmark/`

### Docs
- `docs/training-pipeline/USER_GUIDE.md` — nouveau
- `docs/augmentation-benchmark/ARCHIVED.md` (banner) — marquer legacy

## Endpoints

```
GET    /lab/dashboard
DELETE /lab/cohorts/{cid}/iterations/{iid}/augmentations
DELETE /lab/cohorts/{cid}/iterations/{iid}/test-bundle
```

## Validation

- [ ] Dashboard charge en <1s même avec 5+ cohorts × 5+ iterations
- [ ] Purge augmentations : disque libéré, iteration reste consultable
      mais marquée "augmentations purgées" dans la UI
- [ ] `/benchmark` 404 propre, pas d'imports cassés
- [ ] User guide testé en suivant les étapes from scratch sur une nouvelle
      cohort

## Open questions

- **OQ-1** : auto-cleanup hard (sans demander) après N jours ? Reco :
  non. L'utilisateur reste maître. Banner suffit.
- **OQ-2** : metric pour "difficult coin" — recall_at_1 < 0.5 sur ≥3
  iterations distinctes ? Tweakable.
- **OQ-3** : faut-il une métrique de **stagnation** d'une cohort (5
  iterations sans amélioration > 2pp) → suggestion "essaie une nouvelle
  cohort" ? Pas trivial à coder, à laisser pour plus tard.

## Handoff

Ce sprint clôt la pipeline. Le `progress.md` final doit contenir une
entrée "Sprint 5 done — pipeline complète" avec :
- chiffres mesurés sur la première cohort réelle (R@1 studio, live, delta)
- recipes qui marchent / cassent
- prochaine étape produit (déploiement modèle prod, ou autre cohort)

Le repo est à un point stable. Bon moment pour bumper un tag git.
