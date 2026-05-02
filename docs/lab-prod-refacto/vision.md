# Vision : où on veut atterrir

> Cible architecturale, pas un plan d'implémentation. Définit la
> structure cible, les contrats entre lab et prod, la sémantique du
> label space, et la sémantique de la promotion.

## Principe directeur

> **Une itération de lab ne change rien à ce que l'app prod consomme.
> Le seul moment où ça bascule, c'est la promotion explicite.**

Conséquences :

- Tout artefact produit par un training lab vit sous
  `lab/iterations/<iteration_id>/`.
- Tout artefact lu par l'app prod vit sous `prod/current/`.
- Supabase n'est écrit **que** par la promotion.
- Le bundle Android pour cohort-test peut pointer **soit** prod,
  **soit** une itération lab spécifique (selon le besoin).

## Structure cible — disque

```
ml/
├── lab/
│   └── iterations/
│       └── <iteration_id>/
│           ├── dataset/                  ← anciennement iterations/<iid>/
│           │   ├── train/<eurio_id>/sample_*.jpg  (symlinks vers le bake canonique)
│           │   ├── val/<eurio_id>/*.jpg           (eval_real_norm injecté ici)
│           │   └── class_manifest.json
│           ├── checkpoints/
│           │   ├── best_model.pth
│           │   └── training_log.json
│           ├── embeddings/
│           │   └── embeddings_v1.json
│           ├── tflite/
│           │   ├── eurio_embedder_v1.tflite
│           │   └── model_meta.json
│           ├── metrics/
│           │   └── per_class_metrics.json
│           └── reports/
│               └── benchmark_<bench_id>.json
│
└── prod/
    └── current/
        ├── checkpoints/best_model.pth
        ├── embeddings/embeddings_v1.json
        ├── tflite/
        │   ├── eurio_embedder_v1.tflite
        │   └── model_meta.json
        └── promoted_from.json     ← {iteration_id, training_run_id, promoted_at, verdict, sha256}
```

Le bake (`ml/datasets/<nid>/augmentations/<iid>/`) reste à sa place
actuelle — il est déjà bien isolé par `iid` et il est lu via symlinks
depuis `lab/iterations/<iid>/dataset/train/`. Pas besoin d'y toucher.

## Structure cible — Supabase

| Table | État cible |
|---|---|
| `coins`, `design_groups` | Inchangées. Source de vérité éditoriale. |
| `model_classes` | Écrite **uniquement** par la promotion. Reflète `prod/current/`. |
| `coin_embeddings` | Écrite **uniquement** par la promotion. Reflète `prod/current/embeddings/`. |
| `model_promotions` (nouvelle, optionnelle) | Historique des promotions : `{iteration_id, promoted_at, promoted_by, model_version, verdict, summary}`. Permet le rollback. |

## Le label space — une règle simple

**Côté lab : tout est `eurio_id`.** Toujours. Partout. Pas de COALESCE,
pas de design_group, pas d'ambiguïté.

**Côté prod : la décision design_group est appliquée à la promotion.**
Deux options à trancher en phase 3 (cf.
[`phase-3-promote.md`](./phase-3-promote.md)) :

1. **Option fusion** — au moment de la promotion, les centroïdes des
   `eurio_id` membres d'un même `design_group_id` sont moyennés en un
   seul centroïde, et la table `coin_embeddings` ne stocke que le
   centroïde fusionné. Simple et économique mais perd la possibilité
   de remonter à un eurio_id précis.
2. **Option équivalence** — la table `coin_embeddings` garde un
   centroïde par `eurio_id`, et le matcher (côté Android et côté
   bench) applique une **règle d'équivalence** au moment du verdict :
   si la prédiction tombe sur un `eurio_id` du même `design_group_id`
   que le ground truth, c'est correct. Plus précis, plus complexe à
   maintenir cohérent.

Recommandation : **option équivalence** car elle préserve la
granularité d'évaluation (savoir si on prédit AT-2002 ou AT-2008
reste informatif même si on ne le distingue pas en prod). Mais à
discuter en phase 3.

**En lab on entraîne et on évalue toujours en `eurio_id`.** La
métrique R@1 strict (eurio_id == eurio_id) est la métrique de vérité
côté lab. Une métrique R@1 design-group (eurio_id ∈ même group que
GT) peut être ajoutée en parallèle pour anticiper l'effet de
l'équivalence en prod.

## Contrats entre composants

### Training lab

**Entrée** : un `iteration_id` valide, augmentations bakées sous
`ml/datasets/<nid>/augmentations/<iid>/`.

**Sortie** : `lab/iterations/<iid>/{checkpoints,embeddings,tflite,metrics}/`
remplis. Aucun autre fichier ailleurs touché. Aucune écriture Supabase.

**Invariant** : tous les `eurio_id` de la cohort sont représentés dans
les centroïdes (`embeddings_v1.json`). Si une classe est manquante,
c'est un fail explicite, pas un silent skip.

### Bench / live tests

**Entrée** : un `iteration_id` (lab) ou la chaîne `"prod"` pour cibler
`prod/current/`.

**Sortie** : `iteration_live_tests` / `benchmark_runs` rows en DB,
référençant l'iteration_id ou un marqueur `prod`.

### Bundle Android (cohort-test)

**Entrée** : un `iteration_id` (lab) ou `"prod"`.

**Sortie** : un bundle figé sous
`app-android/src/cohortTest/assets/cohort_bundle/` avec un fichier
`bundle_meta.json` qui dit ce qui est dedans (source = lab/iter/...
ou prod/current).

### Promotion

**Entrée** : un `iteration_id` `completed` avec verdict `better` ou
`baseline`.

**Sortie** :

1. Copie `lab/iterations/<iid>/{checkpoints,embeddings,tflite}/` →
   `prod/current/`
2. Écrit `prod/current/promoted_from.json`
3. Push `embeddings_v1.json` vers Supabase
   `coin_embeddings` + `model_classes`
4. Insère une row dans `model_promotions` (si la table existe)

**Pas d'effet** sur les autres itérations lab — elles restent
disponibles pour comparaison ou rollback.

## Sémantique des chemins lus

| Composant | Lit aujourd'hui | Lit après refacto |
|---|---|---|
| Training subprocess | `eurio-poc/train/` ou `iterations/<iid>/` (selon override) | `lab/iterations/<iid>/dataset/train/` |
| `compute_embeddings.py` | `eurio-poc/val/` | `lab/iterations/<iid>/dataset/val/` |
| `validate_per_class.py` | `eurio-poc/val/` + `embeddings_v1.json` | `lab/iterations/<iid>/dataset/val/` + `lab/iterations/<iid>/embeddings/embeddings_v1.json` |
| `build_cohort_bundle.py` | `output/embeddings_v1.json`, `output/eurio_embedder_v1.tflite` | au choix : `lab/iterations/<iid>/...` ou `prod/current/...` |
| `seed_supabase.py` | `output/embeddings_v1.json` | `prod/current/embeddings/embeddings_v1.json` (et **uniquement** appelé par promote) |
| App prod (APK store) | bundle figé au build | bundle figé construit depuis `prod/current/` |
| App cohort-test | bundle figé | bundle figé construit depuis l'itération choisie |

## Migration progressive

Le refacto est conçu pour être livré **par couche**, pas en big-bang.
Chaque phase apporte un gain autonome :

1. **Phase 1 — label space** débloque les itérations multi-classes
   tout de suite (test-1 v2 et au-delà), sans déplacer un seul artefact.
2. **Phase 2 — isolation par iteration_id** déplace les artefacts mais
   garde un symlink/redirection `eurio-poc/` ← dernière iteration pour
   ne rien casser en aval (compute_embeddings, etc.). Le mode
   "destructif par itération" est retiré.
3. **Phase 3 — promote** ajoute la sémantique `prod/current/` et
   `_seed` opt-in. Tant que phase 2 est en place, phase 3 est un ajout
   pur (pas de cassure).
4. **Phase 4 — bundle routing** étend `build_cohort_bundle` pour cibler
   au choix `lab/iterations/<iid>/` ou `prod/current/`.

À la fin, on peut retirer les redirections de phase 2 et le code
legacy `prepare_dataset.py` direct sur `eurio-poc/` si plus personne
ne l'appelle.

## Hors-scope (rappel)

Ce qui suit **ne fait pas partie** de ce refacto, même si la nouvelle
structure les rendrait plus simples :

- Versioning multi-version de prod (`prod/v1`, `prod/v2`).
- Stockage distant des artefacts (S3, etc.).
- Refonte SQLite.
- Fusion des deux refactos (celui-ci + `training-pipeline/refacto/`).
- A/B testing automatique entre deux itérations en cohort-test.
