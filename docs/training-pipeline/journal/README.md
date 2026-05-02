# Journal des itérations lab

Trace écrite des entraînements lancés via le lab admin. La base de données (`ml/state/training.db`) reste la source de vérité pour les métriques ; ce journal capture **l'interprétation humaine** : hypothèse, lecture des chiffres, décisions, ce qu'on retente.

## Quand écrire une entrée

- À chaque itération qu'on prend la peine d'analyser (pas chaque essai jeté).
- Au moment où on **décide** quelque chose à partir des résultats (changer la recipe, geler une cohort, abandonner une piste).
- Quand un résultat est **surprenant** ou **trompeur** (métrique qui ment, classes qui se chevauchent, etc.) — c'est ce genre d'observation qui se perd si on ne l'écrit pas.

Si l'itération s'est juste passée comme prévu sans rien de notable, pas besoin d'entrée.

## Organisation

```
journal/
├── README.md
└── <cohort_short>-<cohort_name>/
    ├── <iter_name>.md
    └── ...
```

- `<cohort_short>` = 8 premiers chars de l'`id` cohort (suffisant pour grep)
- `<iter_name>` = champ `name` de l'itération (`test-2`, `aug-tilt-25`, etc.)
- Une entrée par itération. Si on fait plusieurs analyses successives sur la même itération, on append des sections datées dans le même fichier.

## Format d'une entrée

Voir [`_template.md`](./_template.md). Sections obligatoires :

1. **Header** — id cohort + iteration, dates, parent, verdict.
2. **Setup** — config training, recipe d'augmentation (résumé, pas le JSON complet).
3. **Résultats** — training metrics, bench R@1/R@3/spread, aug-vs-DINO, live tests.
4. **Interprétation** — qu'est-ce que les chiffres disent vraiment, où ils mentent.
5. **Décisions / suite** — ce qu'on change pour la prochaine itération, et pourquoi.

## Liens

- UI lab : `http://localhost:5173/lab/cohorts/<cohort_id>/iterations/<iter_id>`
- Source de vérité données : `ml/state/training.db` (tables `experiment_iterations`, `benchmark_runs`, `iteration_aug_vs_real`, `iteration_live_tests`)
- Vue d'ensemble pipeline : [`../README.md`](../README.md)
