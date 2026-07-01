# Boucle d'amélioration des itérations (lab cohort-test)

> Journal de bord de la démarche « scan → diagnostic → nettoyage → ré-entraînement »
> pour faire monter le R@1 on-device des itérations lab. Démarré le 2026-06-30
> sur la branche `sources-jo-wikipedia`, à partir de l'itération de référence
> `1fcac3c952a9` (cohorte `mix-zone-17`, 16 classes).

## Pourquoi ce dossier

On veut une **boucle d'amélioration positive** : chaque itération doit produire
un diagnostic exploitable qui dit *quoi changer* avant la prochaine. Ce dossier
trace la journey de bout en bout — diagnostics datés, carte de la pipeline, et
les outils qu'on construit pour fermer la boucle.

## La boucle (cible)

```
   ┌─────────────────────────────────────────────────────────────────────┐
   │                                                                       │
   ▼                                                                       │
 1. TRAIN          bake (training_eligible=1) → ArcFace → TFLite → bundle  │
   │                                                                       │
   ▼                                                                       │
 2. BENCH          evaluate_real_photos vs device snaps held-out           │
   │               → R@1 strict/eq, confusion_matrix, top_confusions       │
   ▼                                                                       │
 3. ON-DEVICE      APK cohortTest, 16 pièces × 3 conditions                │
   │               → §5 live-tests (R@1 eq design_group)                   │
   ▼                                                                       │
 4. DIAGNOSE       quelles classes ratent ? confusion = junk / near-twin / │
   │               domaine ? (cf. 01-diagnosis-*.md)                       │
   ▼                                                                       │
 5. INSPECT        ◀── parcourir les crops PAR CLASSE, repérer les déchets │
   │               (outil manquant aujourd'hui — cf. 03-crop-triage-ux.md) │
   ▼                                                                       │
 6. CLEAN          exclure les crops déchet → training_eligible=0          │
   │               (review-reject / crops-exclude, déjà câblé, réversible) │
   ▼                                                                       │
 7. RE-BAKE  ──────┘  next iteration : le bake drop automatiquement les
                      crops exclus, re-compte la couverture par classe.
```

Étapes 1→4 **existent et marchent**. Le maillon faible est **5 (INSPECT)** : il
n'y a pas de moyen rapide de voir les crops d'une classe pour repérer les
déchets depuis le contexte lab/cohorte. C'est la première amélioration UX
(cf. `03-crop-triage-ux.md`).

## Index

| Doc | Contenu |
|---|---|
| `01-diagnosis-iter-1fcac3c9.md` | Diagnostic de l'itération de référence : d'où vient le R@1 0.79 vs studio 0.94, classe par classe, avec crops réels inspectés. |
| `02-pipeline-map.md` | Carte de la pipeline data : où entrent les crops, quel filtre décide l'inclusion training, où brancher l'exclusion. |
| `03-crop-triage-ux.md` | Spéc de l'outil « QA crops d'entraînement » par classe (le maillon INSPECT). |

## État (2026-06-30)

- ✅ **Bug de mesure corrigé** : le §5 reportait du R@1 *strict eurio_id* (faux
  0.58). Vrai R@1 eq = **0.79** (commits 708c5bc1 + e583183e). Cf.
  `[[project_live_tests_strict_recall_bug]]` et `01-diagnosis`.
- 🔬 **Diagnostic itération 1** fait : l'écart résiduel 0.79→0.94 est surtout
  des **near-twins de portrait** + domaine (eBay proof vs circulation), pas
  majoritairement du déchet. Quelques crops bas de gamme existent quand même.
- ✅ **Outil INSPECT construit** (commits 9b524e08 backend + 3f432de9 front) :
  drawer C5 « QA crops d'entraînement » sur `/lab/cohorts/:id` — accordéon par
  classe rangé par R@1, vignettes suspect-first, clic = exclure/réinclure
  (réversible, effet au re-bake). Cf. `03-crop-triage-ux.md`.
- 🔜 **Raffinements de l'outil INSPECT** (retour PO 2026-07-01, session dédiée) :
  renommage « **Jeu d'entraînement** », overlay allégé, bordure verte pour les
  inclus, **recrop en place** + **réassignation de classe** (réutiliser Review),
  clarté du badge R@1 `—`. Handoff prêt à coder :
  [`04-jeu-entrainement-handoff.md`](./04-jeu-entrainement-handoff.md).
- 🔜 **Itération 2 (modèle)** : attaquer les near-twins (hard-negatives via
  `confusion_map.py`) + augmentations basse-lumière (levier `low-light-v1` :
  relighting `ambient 0.20`/`intensity [0.35,1.0]` — recette déjà créable via le
  CRUD canonique depuis la refonte recettes). Piste parallèle.



Prochaine étape proposée

Comme convenu (« les deux, outil d'abord »), l'étape suivante est l'itération 2 côté modèle : hard-negatives sur les near-twins via confusion_map.py + augmentations basse-lumière (le pire condition, dim à 0.69). Je peux creuser et te proposer un plan d'itération 2 quand tu veux — dis-moi si tu valides d'abord l'outil en visuel.

Planifier l'itération 2, du coup là nous sommes sous Mac, il faut prendre en compte que MPS est plus long, donc si on veut vérifier avec un retrain, on fait moins d'epochs, genre 3
