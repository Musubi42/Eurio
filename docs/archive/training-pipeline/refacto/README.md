# Refacto training pipeline — Cohort / Iteration / Run en tiroirs

> Statu : **DRAFT — 2026-05-01.** Aucun code écrit, ces docs sont la source
> de vérité pour les 5 phases qui suivent. Le précédent jalon est
> `docs/training-pipeline/` (vision originale + sprints 1-5 livrés). Ce
> refacto **ne casse pas** ce qui existe — il restructure l'UX et purge le
> dernier endroit où l'augmentation à la volée subsiste encore (transforms
> torchvision dans `train_embedder.py`).

## Pourquoi ce refacto existe

L'utilisateur a deux frustrations cumulées :

1. **Le flow d'itération n'est pas un flow.** La page Iteration empile
   recipe + bake + training + benchmark + aug↔réel + build APK + live tests
   sans hiérarchie : on ne voit pas où on en est, ce qui est validé, ce qui
   bloque l'étape suivante.
2. **Le training est un boîte noire.** Une fois "Lancer training" cliqué,
   la page n'affiche qu'un spinner. Pas d'epoch, pas de loss, pas de log,
   pas même la confirmation visible que le subprocess tourne sur le bon
   matos. Impossible de vérifier si l'agent qui vient de modifier le code
   ment ou pas.

À cela s'ajoute un point produit non-négociable :

3. **Training = obverse uniquement.** Le bake (`iteration_augmentations.py`)
   force déjà cette règle, mais `train_embedder.py` applique en plus une
   pile de transforms torchvision (`get_train_transforms`) **par-dessus**
   les samples bakés. Ces transforms (rotation 360, color jitter, blur,
   random erasing) sont une augmentation à la volée déguisée — c'est
   exactement ce que le user veut purger.

Et un point matos :

4. **Deux machines, deux backends.** Mac M3 (MPS) pour itérer vite, PC
   1080 Ti (CUDA) pour les vrais runs. Aujourd'hui le code auto-détecte
   correctement (`get_device("auto")`) mais ne loggue presque rien, et
   le front n'affiche jamais sur quelle machine ça tourne. L'utilisateur
   ne sait pas s'il déclenche un run lent (CPU fallback) ou rapide.

## Ce qui change vs `docs/training-pipeline/` (post-sprint 5)

| Aspect | Avant | Après |
|---|---|---|
| Cohort UX | sections empilées | **2 tiroirs** C1 sélection · C2 captures |
| Iteration UX | sections empilées | **4 tiroirs** I1 recipe · I2 bake · I3 training · I4 éval |
| Training transforms | prebaked + torchvision rot/jitter/blur | **bake uniquement** (Resize + Normalize au runtime) |
| Training monitor | spinner | epoch/loss/ETA/log tail stream live |
| Runtime info | log subprocess uniquement | bandeau global `/lab` + carte dans I3 |
| Benchmark / Aug↔réel / Build APK / Live tests | sections séparées | regroupés dans I4 (sous-tiroirs) |

## Comment lire ce dossier

| Si tu veux… | Lis… |
|---|---|
| L'état actuel précis du code à toucher | [`inventory.md`](./inventory.md) |
| Le récit complet du flow cible | [`vision.md`](./vision.md) |
| Implémenter | `phase-N-*.md` dans l'ordre |

> **Refacto orthogonal** — l'enchevêtrement lab ↔ prod (artefacts
> partagés, label space ambigu, absence de step promote) est traité
> séparément dans [`docs/lab-prod-refacto/`](../../lab-prod-refacto/).
> Ses phases peuvent être livrées indépendamment de celles ci-dessous.

## Phases

| # | Titre | Périmètre | Statut |
|---|---|---|---|
| 1 | [Cohort en 2 tiroirs](./phase-1-cohort-tiroirs.md) | Refacto `CohortDetailPage.vue` + computed `cohort_progress` backend | 🔲 |
| 2 | [Iteration en 4 tiroirs](./phase-2-iteration-tiroirs.md) | Refacto `IterationDetailPage.vue` + computed `iteration_progress` backend | 🔲 |
| 3 | [Bake = seule source d'augmentation](./phase-3-bake-only.md) | Purger les transforms torchvision résiduelles, durcir le contrat obverse-only | 🔲 |
| 4 | [Runtime backends visibles](./phase-4-runtime-backends.md) | Module `ml/training/runtime.py` + bandeau global `/lab` + carte I3 | 🔲 |
| 5 | [Training monitor live](./phase-5-training-monitor.md) | `training_progress/<iid>.json` + endpoint + composant Vue + log tail | 🔲 |

## Workflow agent

Un agent qui démarre une phase doit :

1. Lire `inventory.md` (contrat à respecter, fichiers à toucher).
2. Lire `phase-N-*.md` pour la phase qu'il implémente.
3. Lire la phase précédente (au moins le bloc "Sortie") pour comprendre
   l'état acquis.
4. À la fin de la session, **append** une entrée datée dans
   `progress.md` (à créer dans ce dossier au premier livrable) avec :
   ce qui a été livré, ce qui marche, ce qui est cassé, les écarts vs
   le doc de phase, les décisions prises.

## Hors-scope explicite

- **Pas de migration de données.** Les iterations existantes restent
  lisibles (notes, verdicts, R@1 préservés).
- **Pas de changement de schéma SQLite** sauf pour exposer du progress
  (un seul fichier JSON sur disque suffit pour le monitor — phase 5).
- **Pas de ré-organisation** de `ml/datasets/<nid>/...` (ni captures, ni
  augmentations). Le contrat disque est figé depuis sprint 1.
- **Pas de tests automatisés cross-device** (Mac M3 vs PC). On expose
  le runtime, on ne le valide pas en CI.
