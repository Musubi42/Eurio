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

Étapes 1→4 **existent et marchent**. Le maillon 5 (INSPECT) est maintenant
**construit ET raffiné** : le drawer « Jeu d'entraînement » sur `/lab/cohorts/:id`
laisse inspecter par classe, exclure/réinclure, **recadrer en place** et
**réassigner à la bonne classe** (cf. `04-jeu-entrainement-handoff.md`). Ce qui
reste faible, c'est le *pilotage* : rien ne dit encore à l'humain **où regarder
en priorité** (intrus, near-twins) ni **si son nettoyage a payé** (Δ R@1). Voir
la [roadmap](#suite--rendre-la-boucle-pilotable-par-un-humain).

## Index

| Doc | Contenu |
|---|---|
| `01-diagnosis-iter-1fcac3c9.md` | Diagnostic de l'itération de référence : d'où vient le R@1 0.79 vs studio 0.94, classe par classe, avec crops réels inspectés. |
| `02-pipeline-map.md` | Carte de la pipeline data : où entrent les crops, quel filtre décide l'inclusion training, où brancher l'exclusion. |
| `03-crop-triage-ux.md` | Spéc d'origine de l'outil INSPECT par classe. |
| `04-jeu-entrainement-handoff.md` | Handoff des raffinements PO (renommage, anneau, recrop, réassign) — **LIVRÉ** `26e164d`. |

## État (2026-07-02)

- ✅ **Outil INSPECT raffiné** (`26e164d`, session PO 2026-07-01/02) : renommé
  « **Jeu d'entraînement** » (fichier `CohortTrainingSet.vue`), copy de confiance,
  overlay d'exclusion allégé. **Anneau refondu (décision B)** — il encode la
  *valeur d'entraînement*, pas la netteté : vert plein = obverse confirmée / part
  au train · pointillés neutres = éligible mais face non détectée (`unknown`, à
  confirmer, PAS un défaut de crop) · ambre = `face=reverse` (côté carte commun,
  nuisible) · rouge = rejeté/non-2€. **Recrop en place** (réutilise
  `CircleCropEditor`). **Réassignation façon review** : `DinoSuggestions` +
  `FreeSelectorPanel` (clic = réassigne) + bouton « recalculer Dino ».
  - Nouveaux endpoints : `POST /lab/assets/{id}/reassign {eurio_id}` (+ 3 tests) ;
    `POST /review-queue/asset/{id}/dino-suggestions/recompute` (force le recalcul).
- 🔎 **Constat mesuré** (cohorte `mix-zone-17`, classe `at-2005`) : 41/99 crops
  éligibles sont `face='unknown'` — de bons crops que le classifieur de face n'a
  jamais étiquetés. C'est le principal bruit visuel (et un angle mort : cf.
  fuite du gate bake, `02-pipeline-map.md` §filtre).

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
- ✅ **Raffinements de l'outil INSPECT** — livrés `26e164d` (cf. §État 2026-07-02).

## Suite — rendre la boucle *pilotable* par un humain

> Objectif : que l'humain, en ouvrant le Jeu d'entraînement, sache **où regarder
> d'abord**, **corrige vite** (pas en scrutant 275 vignettes), et **voie que ses
> corrections paient**. Deux tracks : la qualité des données en entrée, et le
> retour de boucle. Ordre = leviers décroissants. À trancher/planifier avec le PO.

### Track DONNÉE — « les meilleures pièces en entrée »

- **P1 · Détection d'intrus automatique (Dino ensemble fermé).** Pour chaque crop
  éligible, comparer sa classe assignée au top-1 Dino restreint aux classes de la
  cohorte (`rankCandidates`, déjà en place). Si désaccord fort (sim cible ≫ sim
  classe), lever un badge « probable intrus » et **remonter ces crops en tête**.
  → l'humain réassigne les 3–5 qui comptent au lieu de tout balayer. Réutilise
  l'action réassign livrée. *Le plus fort levier « corriger ».*
- **P2 · Passe de détection de face sur les `unknown` (décision C).** Batch qui
  re-classe `face` (obverse/reverse) sur les crops éligibles `unknown` → vide le
  bucket « à confirmer » (pointillés) et **révèle les vrais reverse** cachés.
  → l'anneau devient enfin honnête ; prérequis propre de P3.
- **P3 · Fermer la fuite du gate bake.** Aligner le bake lab sur l'export legacy :
  `AND (face IS NULL OR face != 'reverse')` (`iteration_augmentations.py`, cf.
  `02-pipeline-map.md` §filtre). Empêche un reverse validé par erreur de polluer
  une classe. Petit, correctness. À faire **après P2** (sinon on droppe des
  `unknown` qui sont en fait des avers).
- **P4 · Santé / couverture par classe.** Colonne d'état : nb obverse confirmés vs
  `unknown` vs total, canonique Numista présent ?, réfs BCE ?, seuil min atteint ?
  → flag « sous-alimentée → sourcer » vs « prête ». Dit à l'humain où **ajouter**
  des pièces, pas seulement où en retirer (anti-starve, cf. `[[project_lab_streamline]]`).

### Track BOUCLE — « est-ce que mes corrections paient ? »

- **P5 · Δ vs itération précédente.** Par classe : R@1 et n_eligible avant/après la
  dernière itération (les données de `benchmark_runs.per_coin` existent déjà). Un
  crop nettoyé + un re-bake → l'humain **voit** le R@1 monter. Rend la boucle
  gratifiante et mesurable (aujourd'hui le badge R@1 est celui de la dernière
  itération, périmé dès qu'on nettoie).
- **P6 · Lier les confusions dans le panneau.** `confusion_matrix` / `top_confusions`
  (bench) + near-twins (`confusion_map.py`) : afficher « cette classe se confond
  avec X » et surligner les crops responsables. Guide l'œil au-delà du simple tri
  par R@1.

### Track MODÈLE (parallèle)

- **P7 · Itération 2.** Hard-negatives sur les near-twins (via `confusion_map.py`)
  + augmentations basse-lumière (levier `low-light-v1` : relighting `ambient 0.20`,
  `intensity [0.35,1.0]` — recette créable via le CRUD canonique). ⚠️ Sur **Mac
  (MPS)** l'entraînement est lent : pour une **vérification** de retrain, réduire à
  ~3 epochs ; garder les runs longs pour le PC (1080 Ti, cf.
  `[[project_cohort_training_and_lanes_2026-06-15]]`, `RUNBOOK-pc-training.md`).

**Reco d'ordre** : P1 (trouver les intrus vite) → P5 (voir que ça paie) → P2+P3
(assainir la face) → P4 (couverture) → P6 → P7. P1 et P5 donnent le plus de
« sentiment de contrôle » pour le moindre coût.
