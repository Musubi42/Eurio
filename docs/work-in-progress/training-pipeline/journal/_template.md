# <iter_name> — <cohort_name>

- **Cohort** : `<cohort_id>` (`<cohort_name>`)
- **Iteration** : `<iter_id>`
- **Parent** : `<parent_iter_id>` ou _none_
- **Démarrée** : `<YYYY-MM-DDTHH:MM:SSZ>`
- **Terminée** : `<YYYY-MM-DDTHH:MM:SSZ>`
- **Verdict (UI)** : `baseline` / `better` / `worse` / `pending`
- **Verdict (humain)** : ce qu'on en pense réellement

## Hypothèse

Une phrase. Qu'est-ce qu'on cherche à valider/infirmer avec cette itération ?

## Setup

- **Training config** : `epochs=…, batch=…, m_per_class=…, mode=…`
- **Recipe d'augmentation** : `<recipe_id>` — résumé court (layers actifs, params clés)
- **Classes** : N classes total (`+M` ajoutées vs parent), kind = `eurio_id` / `design_group_id` / mix
- **Variants par classe** : N

## Résultats

### Training

- Loss : …
- R@1 (eval interne) : …
- Notes (overfit, divergence, durée) : …

### Benchmark photos réelles (`<bench_id>`)

- N photos, N pièces
- R@1 / R@3 / R@5 : … / … / …
- mean_spread : …
- Confusions notables : …

### Aug-vs-DINO (cosine real↔aug)

| eurio_id | cos |
|---|---|
| … | … |

### Live tests (`<n>` tests)

- R@1 strict : N/N (= X%)
- Erreurs notables : …

## Interprétation

Qu'est-ce que les chiffres disent vraiment. Où la métrique ment. Quelles hypothèses on peut formuler sur la cause.

## Décisions

- [ ] Décision 1 — _pourquoi_
- [ ] Décision 2 — _pourquoi_

## Suite

Quelle itération on lance ensuite (recipe, classes, config) et ce qu'on attend d'elle.
