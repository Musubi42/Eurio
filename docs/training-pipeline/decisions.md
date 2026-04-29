# Decisions log

> Toutes les décisions architecturales prises lors du brainstorm
> 2026-04-29 et après. Format : ADR-lite, append-only.
>
> Si tu remets en question une décision pendant un sprint, **n'écrase pas**
> l'entrée — ajoute un suivi en bas avec un nouvel ID, référence l'ancien.

---

## D-001 — Cohort = unité de pilotage

**Date** : 2026-04-29
**Statut** : actée

`/benchmark` disparaît du menu admin et est intégré dans cohort. Toute la
pipeline (capture → recipe → training → benchmark → live tests) vit dans
`/lab/cohorts/<id>` autour des iterations.

`/lab/dashboard` peut éventuellement réémerger comme vue cross-cohort
read-only en sprint 5.

---

## D-002 — Recipe scope = par iteration

**Date** : 2026-04-29
**Statut** : actée

La recipe est portée par l'iteration (statu quo). Une cohort peut tester
plusieurs recipes via plusieurs iterations. C'est la base de l'A/B
reproductible.

---

## D-003 — Captures device imposées sur la cohort

**Date** : 2026-04-29
**Statut** : actée

On ne peut pas lancer une iteration sans captures device pour les pièces
de la cohort. Évite le legacy benchmark workflow (photos studio pures) qui
n'a plus de sens dans la pipeline unifiée.

---

## D-004 — Augmentations stockées sur disque

**Date** : 2026-04-29
**Statut** : actée

Path : `ml/datasets/<numista_id>/augmentations/<iteration_id>/sample_*.jpg`.
On stocke **toutes** les augmentations utilisées pour le training (pas
juste un échantillon).

**Pourquoi** :
- Reproductibilité totale : on peut reconsommer le snapshot pour réentraîner
  exactement la même chose, pas juste re-générer avec la même recipe.
- Visualisation : la galerie §3 lit directement le disque, pas de
  régénération.
- Debugging : on voit ce que le modèle a vu en training, exactement.

**Coût accepté** : ~50-100 MB par iteration sur une cohort de 17 pièces.
Garbage-collect en sprint 5 (purge des iterations failed/old).

**Seed** : la recipe doit fixer son seed pour que `regenerate` produise
l'identique. Ajouter un champ `seed: int` à la recipe si absent.

---

## D-005 — Live test = one-shot uniquement

**Date** : 2026-04-29
**Statut** : actée

Le mode "live test" dans l'app cohortTest réutilise le mode snap one-shot
existant. Pas de capture continue. Conditions plus contrôlées, suffisant
pour démarrer.

L'app **affiche** le top-3 immédiatement après le snap mais le test est
**commit instantanément** (pas de re-snap pour ce test). Évite le biais de
confirmation tout en restant pédagogique.

---

## D-006 — Distance aug↔réelles avec DINO

**Date** : 2026-04-29
**Statut** : actée

La métrique de comparaison aug↔réelles utilise **DINO** (modèle externe
stable) plutôt que l'ArcFace de l'iteration en cours.

**Pourquoi** : ArcFace a vu les augmentations en training, donc il les voit
forcément proches → métrique circulaire. DINO est neutre, mesure la
similarité visuelle indépendante du training.

L'inférence DINO est déjà utilisée par confusion-map → infra existante.

---

## D-007 — APK cohortTest filtré au cohort

**Date** : 2026-04-29
**Statut** : actée

Le `catalog_snapshot.json` embarqué dans l'APK cohortTest contient **uniquement
les coins de la cohort**, pas le full référentiel.

Si le modèle prédit une classe hors-cohort (faux positif), l'app affiche
le raw eurio_id (fallback). Pas de label humain.

**Pourquoi** : APK plus léger, démarrage plus rapide, plus simple à raisonner
sur les résultats live.

---

## D-008 — Conditions de test prescrites = hardcoded 3 conditions

**Date** : 2026-04-29
**Statut** : actée

Les conditions de live test sont **hardcoded** : `bright`, `dim`, `tilt`.
Pas configurable au niveau cohort/iteration au début.

**Pourquoi** : métrique stable cross-iterations, simple à coder, pas de
décision UX à prendre pour le moment. Reconfigurable en sprint 5+ si besoin.

3 coins × 3 conditions = 9 tests par iteration. Acceptable.

---

## D-009 — Stop training = graceful avec timeout

**Date** : 2026-04-29
**Statut** : actée

`POST /lab/cohorts/<id>/iterations/<iid>/stop` envoie SIGTERM au subprocess
de training. Le script `train_embedder.py` doit catcher SIGTERM, finir
l'epoch courante, écrire un checkpoint `*.partial`, exit propre.

Si pas terminé dans **30s**, SIGKILL forcé. L'iteration finit en
`status='failed'` avec `error="Stopped by user (graceful)"` ou `"(forced)"`.

---

## D-010 — Gradle flavor pour cohortTest

**Date** : 2026-04-29
**Statut** : actée

L'app cohortTest est un **product flavor Gradle** (pas un nouveau module),
avec `applicationIdSuffix = ".cohorttest"`. Cohabite avec l'app full sur
le device.

Source set : `app-android/src/cohortTest/` override `MainActivity` et le
manifest pour exclure vault/profile/onboarding/etc.

---

## D-011 — Build commands surfaced dans le front

**Date** : 2026-04-29
**Statut** : actée

L'iteration affiche **la commande exacte** à copier-coller pour build et
installer l'APK cohortTest, et plus tard pour pull les logs live :

```
go-task -t app-android/Taskfile.yml cohort-test:install \
  COHORT=<name> ITERATION=<iid>
```

L'utilisateur ne devrait jamais avoir à composer la commande à la main.

---

## D-012 — Progress.md append-only, sprints peuvent être édités

**Date** : 2026-04-29
**Statut** : actée

`progress.md` est append-only — on annote en bas, on ne réécrit pas
l'historique. Les fichiers `sprint-N-*.md` peuvent être édités si on
identifie un meilleur plan, mais le diff doit être noté dans
`progress.md` avec la justification.

---

## Slots futurs (à remplir au fil des sprints)

- D-013 — *(à acter quand le format de la recipe DSL sera figé)*
- D-014 — *(GC strategy pour augmentations old/failed)*
- D-015 — *(format précis du JSONL live tests, schema versioning)*
