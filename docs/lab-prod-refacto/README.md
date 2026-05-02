# Refacto lab ↔ prod

> Statut : **analyse + plan, aucun code livré.** Document écrit
> 2026-05-02 après deux symptômes consécutifs sur la cohort
> `mix-zone-7-cls` :
>
> - **test-2** (`e3c4df8678eb`) — R@1 bench 85.7% / R@1 live strict 57%.
>   Carryover d'embeddings polluants entre itérations.
> - **test-1 v2** (`8ac508b062da`, cohort `mix-zone-7-cls-v2`) —
>   `prepare_dataset.py` ne prépare que 4 classes sur 7 à cause d'un
>   conflit eurio_id ↔ design_group dans le resolver.
>
> Les deux symptômes pointent la même cause systémique : **le lab et la
> prod partagent leur état**, et **le label space n'est pas explicite**.

## Pourquoi ce refacto existe

Le pipeline d'entraînement actuel a été construit en assumant un seul
"modèle vivant" qui s'étoffe runs après runs. Le système d'itérations
de lab a été ajouté par-dessus, mais il écrit dans les **mêmes
artefacts** (`eurio-poc/`, `checkpoints/best_model.pth`,
`output/embeddings_v1.json`, tables Supabase) que ceux que l'app prod
consomme. Conséquences :

1. Une itération de lab peut polluer/casser ce que l'app prod voit.
2. Comparer ou rollback entre itérations est impossible (chaque run
   écrase la précédente).
3. Le moindre conflit conceptuel entre les deux mondes (label space
   eurio_id côté iteration vs design_group côté legacy resolver)
   produit des bugs silencieux qui contaminent les métriques.

L'objectif n'est pas de tout réécrire — il est de poser deux univers
clairement séparés, et **un seul moment** où l'un alimente l'autre :
la promotion.

## Cible en une phrase

**Lab** = un univers d'expérimentation où chaque `iteration_id` est
isolé (dataset, checkpoint, embeddings, tflite, métriques, reports).
**Prod** = un état stable, alimenté uniquement par une étape de
**promotion** explicite, qui est aussi le seul moment où Supabase est
écrit.

Et un **label space unique côté lab** : `eurio_id`. Le mapping vers
`design_group_id` est une décision **prod**, gérée au moment de la
promotion, pas pendant l'entraînement.

## Comment lire ce dossier

| Si tu veux… | Lis… |
|---|---|
| Comprendre l'état actuel et les symptômes observés | [`analysis.md`](./analysis.md) |
| Voir la cible (structure cible, contrats, sémantique) | [`vision.md`](./vision.md) |
| Implémenter la phase 1 (label space) | [`phase-1-label-space.md`](./phase-1-label-space.md) |
| Implémenter la phase 2 (isolation artefacts) | [`phase-2-isolation-artefacts.md`](./phase-2-isolation-artefacts.md) |
| Implémenter la phase 3 (step promote) | [`phase-3-promote.md`](./phase-3-promote.md) |
| Implémenter la phase 4 (bundle routing) | [`phase-4-bundle-routing.md`](./phase-4-bundle-routing.md) |
| Suivre l'avancement | [`progress.md`](./progress.md) |

## Phases

| # | Titre | Périmètre court | Bloque les itérations ? | Statut |
|---|---|---|---|---|
| 1 | [Label space eurio_id partout](./phase-1-label-space.md) | Flag `--class-kind` dans `prepare_dataset.py`, Resolver eurio-mode | **Oui** — sans ça, test-1 v2 ne peut pas tourner | 🔲 |
| 2 | [Artefacts isolés par iteration_id](./phase-2-isolation-artefacts.md) | `lab/iterations/<iid>/{checkpoints,embeddings,tflite,metrics}/` | Non, mais débloque la comparaison inter-itérations | 🔲 |
| 3 | [Step promote explicite](./phase-3-promote.md) | CLI/UI `promote`, `_seed` opt-in promote-only | Non, dépend de phase 2 | 🔲 |
| 4 | [Bundle routing](./phase-4-bundle-routing.md) | APK prod ← `prod/current/`, cohort-test ← itération choisie | Non, dépend de phase 2 | 🔲 |

**Phase 1 est urgente** parce qu'elle débloque test-1 v2 et toutes les
itérations futures. Les phases 2-4 améliorent l'isolation et la
traçabilité mais ne bloquent pas l'expérimentation immédiate (le mode
"destructif par itération" déjà câblé dans `iteration_runner.py` permet
de tenir tant que l'isolation n'est pas en place).

## Hors-scope explicite

- **Versioning multi-version de prod** (`prod/v1`, `prod/v2`, etc.)
  utile mais découplé. Une seule version prod active suffit pour
  démarrer.
- **Migration des itérations passées** — leurs métriques restent
  lisibles dans la DB, on ne ré-exporte pas leurs artefacts vers la
  nouvelle structure.
- **Refonte du schéma SQLite** — les tables (`experiment_iterations`,
  `training_runs`, `benchmark_runs`, `iteration_*`) sont déjà bien
  indexées par `iteration_id` / `run_id`. Seules quelques colonnes
  pourraient s'ajouter (statut promote, source du bundle), pas de
  refonte.
- **Versioning du modèle Android côté app prod** — l'app prod tire un
  bundle figé au build, ce point ne change pas.

## Lien avec le refacto `training-pipeline/refacto/`

Le refacto déjà documenté dans `docs/training-pipeline/refacto/` (5
phases planifiées) traite **l'UX du lab** : tiroirs cohort/iteration,
runtime visible, training monitor live, purge des transforms
torchvision résiduelles. Il est **orthogonal** à celui-ci. Aucune
phase n'en dépend, mais les deux peuvent s'enchaîner librement.

Si un agent doit choisir lequel attaquer en premier : la phase 1
ci-dessous (label space) est plus urgente que n'importe quelle phase
de l'autre refacto, car elle débloque la production de données fiables
en lab.

## Workflow agent

Un agent qui démarre une phase doit :

1. Lire [`analysis.md`](./analysis.md) en entier (état actuel précis,
   fichiers sensibles).
2. Lire [`vision.md`](./vision.md) (la cible — utile même pour une
   phase qui n'attaque qu'un bout).
3. Lire la phase qu'il implémente.
4. À la fin de la session, **append** une entrée datée dans
   [`progress.md`](./progress.md).
