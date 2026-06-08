# README training — découpler le training (PC) du dev (Mac)

> Note opérationnelle durable. Audit fait le 2026-06-08 (cf. memory
> `project_collaborative_review`). Objectif : **pouvoir continuer à travailler sur
> le Mac (référentiel, cohortes, review) pendant qu'un training tourne des heures
> sur le PC**, sans drift destructeur de `eurio.db`.

## Le problème

Le lease `eurio.db` (`ml/store/lease.py`, cf. `docs/refacto-ml/chunk6-vps-minio.md`)
suppose des **sessions courtes et alternées** : une machine prend le verrou
d'écriture, travaille, le relâche. Le training viole cette hypothèse — il *lit*
beaucoup au démarrage (construction du dataset) mais n'*écrit* qu'à la fin
(résultats du run), tout en immobilisant la base pendant des heures.

→ On veut que le PC tienne le moins possible le droit d'écriture, et que son
push de fin **n'écrase jamais** le travail data fait en parallèle sur le Mac.

## Pourquoi c'est sûr : les écritures sont quasi disjointes

Le training et le dev écrivent dans des ensembles de tables **disjoints**, à deux
détails de protocole près (ci-dessous).

### Tables possédées par le TRAINING (PC) — merge-back en bloc

Terminales/immuables une fois le run fini → on les copie telles quelles :

- `training_runs` + cascade : `training_run_steps`, `training_run_epochs`,
  `training_run_classes`, `training_run_logs`
- `benchmark_runs`
- `training_staging`, `training_removal_staging`
- `iteration_aug_vs_real`

### Tables possédées par le DEV (Mac) — le training n'y touche pas au merge

- `source_*` (`source_images`, `source_runs`), `discovery_*`, `discarded_listings`
- `review_queue`, `review_claude_verdicts`, `peer_review_decisions`
- `image_assets` (**métadonnées d'identification** : `eurio_id`, `resolution_status`,
  `training_eligible`, `face`, `variant_kind`, `quality_score`, tilt…)
- `experiment_cohorts`, `augmentation_recipes`, `listing_text_signals`,
  `coin_*` (référentiel)

### Le cas clé : `image_assets`

**Le training n'écrit JAMAIS dans `image_assets`** — il lit seulement le flag
`training_eligible` pour décider l'appartenance au dataset. Conséquence directe :
pendant un run, tu peux éditer le référentiel et faire de la review qui modifie
`image_assets` **librement sur le Mac**. Zéro collision.

## Les 2 points de protocole (validés 2026-06-08)

1. **`experiment_iterations.status`** — table partagée. Le dev *crée* la ligne en
   `status='pending'` ; le training fait avancer le statut
   (`training → benchmarking → completed/failed`) + écrit les champs terminaux
   (`training_run_id`, `benchmark_run_id`, `verdict`, `delta_vs_parent`,
   `diff_from_parent`). **Règle : une fois une itération créée, seul le training
   touche son `status`.** En pratique tu n'édites pas à la main l'itération que le
   PC est en train de tourner → naturel.

2. **`image_asset_dino_predictions`** — UPSERT par `asset_id`. Le pipeline source
   (Mac, si tu scrapes pendant le run) et un éventuel backfill (PC) peuvent tous
   deux écrire, mais sur des **assets différents**. Collision seulement si les deux
   touchent le *même* asset_id (improbable). À garder en tête.

## La règle d'or

> **Le PC n'envoie JAMAIS le fichier `eurio.db` entier** (`db:release` standard).
> Pousser le fichier entier écraserait le travail data fait sur le Mac en parallèle.

À la place, à la fin d'un run, le PC **applique ses tables training-owned** sur la
canonique courante :

- `INSERT` (ou `INSERT OR REPLACE`) des tables de la liste « possédées par le
  training » (runs immuables → pas de conflit) ;
- `UPDATE experiment_iterations SET <champs terminaux> WHERE iteration_id = ?`
  (jamais un REPLACE de la ligne entière — on préserve les champs créés par le dev).

Le `db:release` plein-fichier reste réservé au **seed initial** et aux sessions
réellement séquentielles sans dev concurrent.

> **Statut outillage** : ce README documente le *protocole*. L'outil de merge
> automatisé (la « roquette SQL » : export des tables training-owned du PC →
> application sur la canonique) n'est pas encore écrit — à faire dans un lot dédié
> si/quand le besoin devient récurrent. En attendant, le protocole se tient à la
> main (le PC reste sur sa copie, le merge se fait au cas par cas).

## Voir aussi

- `ml/store/lease.py` — le lease MinIO (acquire/release/steal/status).
- `docs/refacto-ml/chunk6-vps-minio.md` — provisioning MinIO du bucket lease.
- `docs/work-in-progress/collaborative-review/` — la review collaborative, qui
  sort la review de l'équation du lease (autre chantier, complémentaire).
