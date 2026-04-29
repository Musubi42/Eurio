# Vision — Training pipeline unifiée

> Le récit du flow complet, de la sélection de pièces à la validation
> en conditions réelles. Source unique pour tous les sprints.

## Acte un — qu'est-ce qu'on cherche à mesurer

L'objectif final de tout l'entraînement, c'est qu'**une pièce posée sur
une table dans la rue, scannée par l'app prod, soit reconnue**. Tout le
reste — recipes, augmentations, training, benchmarks studio — n'est qu'un
proxy pour estimer la performance dans cette scène réelle.

Aujourd'hui on a deux mesures :
1. **R@1 studio** : on entraîne sur des augmentations, on évalue sur 6
   photos device par pièce prises dans des conditions contrôlées.
2. *(rien en réel)*

Le R@1 studio est utile mais circulaire : on entraîne sur une distribution
qu'on contrôle, on évalue sur une distribution proche, ça surévalue la
généralisation. La pipeline cible introduit deux mesures supplémentaires :

3. **Distance aug ↔ réelles** : à quel point ma recipe d'augmentation
   reproduit visuellement ce que le device capture vraiment.
4. **R@1 live** : pièce scannée *via l'app cohortTest* dans des conditions
   prescrites, label log local, sync admin, confusion matrix réelle.

## Acte deux — l'unité de pilotage est la cohort

Une cohort, c'est :
- une **liste de pièces** (frozen quand 1ère iteration lance)
- des **captures device canoniques** (6 photos par pièce, partagées entre
  iterations)
- N **iterations** — chaque iteration porte un essai reproductible :
  - recipe d'augmentation
  - tas d'augmentations générées (snapshot disque)
  - run de training (avec son modèle artifact)
  - benchmark studio
  - comparaison aug ↔ réelles
  - build APK de test (cohortTest)
  - live tests device
  - décisions/notes

Comparer iter1 vs iter2 → on lit ce qui a changé : recipe, donc
augmentations, donc modèle, donc résultats. C'est l'A/B reproductible.

## Acte trois — le flow A → Z

```
1. /lab/cohorts/new                        → name, description ; vide OK
2. /coins → modal "Cohort lab"             → attach des coins (status draft)
3. /lab/cohorts/<id>  §1 Pièces            → review, add, remove
4. /lab/cohorts/<id>  §2 Captures device   → CSV → adb push → capture → adb pull → sync
5. /lab/cohorts/<id>/iterations/new        → recipe choisi, training_config
6. iter §3 Recipe + augmentations preview  → galerie générée, on ajuste
7. iter §3 "Lancer training"               → freeze cohort, run training (stoppable)
8. iter §4 Studio benchmark                → R@1 sur captures device
9. iter §4 Aug ↔ réelles                   → galerie + distance DINO par pièce
10. iter §5 Build cohort-test app          → commande affichée, copier-coller
11. iter §5 Live tests on device           → 9 tests prescrits (3 coins × 3 conditions),
                                              snap par snap, top-3 affiché, log JSONL
12. iter §5 Sync logs                      → commande pull → confusion matrix réelle
13. Décision : tweak recipe                → clone iteration, retour à 5
```

À chaque section l'utilisateur **voit la donnée et décide**. Il y a toujours
un état "ce qui manque pour avancer" lisible d'un coup d'œil.

## Acte quatre — l'app cohortTest

C'est l'innovation principale. Plutôt que builder l'app prod entière à
chaque essai (lourd, embarque vault/profile/onboarding), on génère un
**APK dédié** par cohort+iteration :

- **Gradle flavor `cohortTest`** dans `app-android/build.gradle.kts`
- `applicationIdSuffix = ".cohorttest"` → cohabite avec l'app full
- UI minimaliste : ScanScreen + toggle continu/one-shot + debug mode
- Pas d'animation 3D match, pas de bottom nav, pas de vault/profile/onboarding
- Vue résultat : top-3 par **eurio_id** (pas numista_id), confiance, distance
- **Pas de Supabase** : tout en assets/raw embarqué dans l'APK :
  - `model.tflite` (modèle de l'iteration)
  - `catalog_snapshot.json` (filtré aux coins de la cohort)
  - `cohort_meta.json` (eurio_ids, prescription des tests)
  - `live_tests_manifest.json` (les 9 tests à faire)

L'app guide step-by-step : "Test 1/9 : fr-2007-2eur-standard · bright". Snap →
top-3 affiché, commit immédiat (pas de re-snap), passe au suivant.

Sortie locale : `/sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/eurio_live_tests/<iteration_id>.jsonl`.

## Acte cinq — la décision

Chaque iteration produit 4 datapoints actionnables :
1. R@1 studio (déjà aujourd'hui)
2. Distance aug ↔ réelles (DINO, par pièce)
3. R@1 live (par pièce × condition)
4. Delta studio vs live

Lire ces 4 chiffres ensemble dit à l'utilisateur **où la recipe casse** :
- R@1 studio haut + distance aug↔réel basse + R@1 live bas → la recipe est
  optimisée pour le studio mais ne reflète pas la réalité device.
- R@1 studio bas → la recipe ne couvre pas assez la variabilité, le modèle
  est sous-trained.
- Une pièce X avec distance aug↔réel rouge → la recipe a un problème
  spécifique à cette pièce (couleurs, patine, …).

Le user clone l'iteration, ajuste la recipe en fonction du diagnostic,
relance. C'est la **boucle d'amélioration guidée**.

## Hors-scope (pour ne pas dériver)

- Multi-device tests (un seul phone calibré pour le moment)
- Versioning des captures (les captures sont canoniques par pièce, cf
  cohort capture flow)
- Cross-cohort optimisation automatique (on reste dans une logique
  d'amélioration manuelle guidée par les métriques)
- Migration `<numista_id>` → `<eurio_id>` côté disque (statu quo, sprint
  séparé)
