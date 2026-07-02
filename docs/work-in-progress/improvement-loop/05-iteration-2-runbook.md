# P7 · Runbook itération 2 — hard-negatives near-twins + basse lumière

> Prépa livrée le 2026-07-02 (P1→P6 sont dans le Jeu d'entraînement, cf.
> [README](./README.md) §État). Ce runbook est le **mode d'emploi opérateur**
> pour lancer l'itération 2 de `mix-zone-17` — les runs longs se font sur le
> **PC (1080 Ti)**, le Mac ne sert qu'à une vérification ~3 epochs
> (cf. `RUNBOOK-pc-training.md`, `[[project_cohort_training_and_lanes_2026-06-15]]`).

## 0. Pré-requis — nettoyer AVANT de ré-entraîner

L'itération 2 n'a de sens que sur un jeu propre :

1. **Scanner** : Jeu d'entraînement → « Scanner intrus + faces (Dino) ».
   (Déjà fait le 2026-07-02 : 25 intrus levés, 88 faces résolues.)
2. **Réassigner / exclure** les intrus badge ⚠ (les 2 plus fortes marges sont
   des erreurs de label confirmées : une fi-2017 étiquetée
   `es-2016-segovia`, un portrait étiqueté `fi-2016-von-wright`).
3. Re-scanner au besoin (le scan est idempotent, ~2 min pour 515 crops).

## 1. Recette `low-light-v1` (CRUD canonique)

Levier « domaine » : les photos device ratées du bench sont surtout en
lumière basse — on augmente avec un relighting sombre (`ambient 0.20`,
`intensity [0.35, 1.0]`). Config **validée** contre
`shared.augmentation_recipe.validate_recipe` (2026-07-02).

⚠ Les recettes sont des métadonnées **canoniques** (writer unique = eurio-api
VPS, cf. `ml/serving/recipe_routes.py`) — à créer via l'API canonique (ou le
studio → Recettes), PAS en écrivant la réplique locale :

```bash
curl -X POST https://eurio-api.musubi.dev/recipes \
  -H "Authorization: Bearer $EURIO_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "low-light-v1",
    "zone": null,
    "config": {
      "count": 100,
      "layers": [
        {"type": "perspective", "probability": 0.7, "max_tilt_degrees": 20},
        {"type": "relighting", "probability": 0.9, "ambient": 0.20,
         "max_elevation_deg": 60, "intensity_range": [0.35, 1.0],
         "normal_strength": 1.3},
        {"type": "overlays", "probability": 0.7,
         "categories": ["patina", "dust"], "opacity_range": [0.1, 0.3],
         "max_layers": 2}
      ]
    }
  }'
# puis, côté compute : go-task ml:db:pull-replica (la recette arrive avec)
```

Repères : la baseline historique relighting est `ambient 0.35`,
`intensity [0.6, 1.1]` (recettes test-1..3) — `low-light-v1` assombrit
franchement sans toucher aux autres couches.

## 2. Hard-negatives near-twins — par la DONNÉE, pas par la loss

Le train utilise déjà un miner de paires dures **in-batch**
(`train_embedder.py` : `miner(embeddings, labels)`) : les hard-negatives ne se
configurent pas, ils émergent **si les classes qui se confondent sont dans le
même run**. Donc :

1. Lire les confusions : chips « ↔ se confond avec X » du Jeu d'entraînement
   (dès qu'un bench completed existe) + `training/eval/confusion_map.py`
   (near-twins catalogue-wide, zones vert/orange/rouge).
2. **Étendre la cohorte** (ou en cloner une `mix-zone-17-hardneg`) avec les
   near-twins des classes faibles — ex. les portraits qui aspirent
   `fi-2016-von-wright` (donatello, etc.). Une classe ajoutée = le miner
   fabrique les paires dures tout seul.
3. Chaque classe ajoutée doit passer la santé du panneau (pas de
   « sous-alimentée ») — sinon on importe du starve.

## 3. Lancer l'itération 2

Depuis `/lab/cohorts/b0299ca0252b` (studio local, ML `:8042` up) :

1. Nouvelle itération, parent = `74ba5d2e140e`, recette **low-light-v1**,
   hypothèse : « nettoyage intrus + low-light ⇒ R@1 device ↑ sur dim_* ».
2. **Mac (MPS) = vérification seulement** : `epochs ≈ 3` dans le
   training_config pour valider la plomberie (bake → train → bench tournent).
   ⚠ Ne PAS lancer un run long sur Mac (lent, et `--reload` du serveur tue
   les subprocess — piège connu).
3. **Run long sur le PC 1080 Ti** : cf. `RUNBOOK-pc-training.md` (lane
   habituelle : sync réplique → train → push artefacts).
4. Bench + APK cohortTest (§5 live-tests) puis relire le Jeu d'entraînement :
   les chips **Δ ±pts** (P5) comparent automatiquement à l'itération 1 dès que
   le bench de l'itération 2 est `completed`.

## Ce qui mesurera le succès

- R@1 eq §5 (device) : baseline 0.79 (itération `1fcac3c9`/`74ba5d2e`).
- Conditions `dim_*` du bench (per_condition) : c'est la cible de low-light-v1.
- Les Δ par classe du panneau : les classes nettoyées (intrus réassignés)
  doivent monter ; une classe qui baisse après nettoyage = données retirées à
  tort ou near-twin manquant au run.
