# IterationDetailPage — Design & vision

> Capture des discussions et de la vision utilisateur pour la page
> `/lab/cohorts/:cohortId/iterations/:iterationId`.
>
> **Contexte** : session 2026-04-30 — premier vrai run end-to-end avec la
> cohort `fe933e8571a1` (16 pièces) et l'itération `8270574cd55e` (test-1).
>
> Cette doc est la référence de design à lire avant de toucher l'UX de
> la page. Elle capture l'état actuel, les gaps observés, et la vision cible.

---

## État actuel de la page (2026-04-30)

### Ce qui existe

La page vit dans
`admin/packages/web/src/features/lab/pages/IterationDetailPage.vue`
et est structurée ainsi :

```
Header
  - Titre "nom-itération" + badge statut + VerdictBadge
  - Démarré / Fini / Parent
  - Bouton Stop (si training/benchmarking)
  - Bouton Supprimer (si pas en cours)

Banner "In-progress" (si training|benchmarking)
  — un spinner + texte "Training en cours… La page se rafraîchit auto."

Banner "Failed" (si failed)

§0 Pipeline (v-if="isPending" → disparaît dès que training démarre)
  - Dropdown recette + bouton configurateur inline (toggle)
  - Slider variant count
  - Panel configurateur RecipeConfigurator (collapsible)
  - Status bar : "Config modifiée" | "N aug bakées" | "Aucune aug"
  - Boutons : Sauver config | Régénérer (bake) | Lancer training

Métriques grid 2×2 (R@1, R@3, R@5, spread)
  — valeurs "—" quand pas encore benchmarké

Section Inputs (readonly)
  — recette, variant_count, training config, training run, Δ vs parent

Section "Delta par zone" (si données)
Section "Delta par pièce" (si données)
Section "Par axe de variabilité" (si benchmark détaillé)

AugmentationsGallery (grille thumbnails, toujours présente)
  — galerie des samples bakés, zoom overlay, bouton Purger

AugVsRealSection (§4)
BuildTestAppSection (§5)
LiveTestsSection (§5 suite)

Notes + verdict override sidebar
```

### Ce qui ne va pas — gaps observés

#### G-001 — Training invisible

Problème : quand on clique « Lancer training », la page passe en
"Training en cours" avec juste un spinner. Aucune information sur :
- L'epoch courante (ex : Epoch 12/40)
- La loss en cours
- Le temps écoulé / l'ETA
- Les logs du subprocess

L'utilisateur est dans le noir pendant potentiellement 10-20 minutes.
Il ne sait pas si le training avance, coince ou plante.

Impact : frustration + risque de cliquer Stop par erreur en croyant
que rien ne se passe.

#### G-002 — §0 disparaît dès le launch

Problème : le `v-if="isPending"` sur §0 fait disparaître toute la
config pipeline dès que le training commence. L'utilisateur ne peut
plus voir quelle recette a été utilisée, ni combien d'augmentations ont
été bakées, sans aller dans la section Inputs (cachée plus bas).

Impact : la section Inputs existe mais est peu lisible comparée au §0
interactif.

#### G-003 — Pas d'auto-reload au moment exact du launch

Problème : le poll `setInterval` ne tourne que si `status ===
'training'|'benchmarking'`. Or juste après le click "Lancer training",
on appelle `reload()` manuellement une fois — mais si ce reload arrive
avant que le runner ait changé le status en DB, la page reste en
`pending` (§0 visible) et ne pollerà pas automatiquement.

Impact : l'utilisateur voit §0 encore quelques secondes, recliquerait
"Lancer training" par reflexe.

#### G-004 — Pas de log de training accessible

Problème : les logs du subprocess Python (`train_embedder.py`) sont
écrits dans un `.log` sur disque mais aucun endpoint ne les expose
et aucune UI ne les affiche.

Impact : en cas d'erreur (ex : OOM, dataset introuvable), l'utilisateur
voit juste `iteration.status = "failed"` avec l'error message extrait
du subprocess — mais pas la stack trace complète.

#### G-005 — Recette non visible post-training

Problème : dans la section Inputs (§ recap), `iteration.recipe_id`
est affiché comme un UUID brut, pas comme un nom lisible. Si la recipe
a un nom clair ("hell-yeah"), on ne le voit pas sans aller sur la page
recettes.

---

## Vision cible

### Principe directeur

La page doit permettre d'aller **bout-en-bout sans quitter le contexte**
de l'itération :

```
recipe → bake → training (visible) → benchmark → aug↔réel → build → live tests
```

À chaque étape, l'utilisateur **voit où il en est** et **sait quoi
faire ensuite**. Pas de black box.

### Vue d'ensemble par statut

```
┌─────────────────────────────────────────────────────────┐
│ STATUS = pending                                        │
│ §0  [visible, interactif]                              │
│      - Recette + configurateur inline                  │
│      - Bake (Régénérer / Générer)                      │
│      - Lancer training                                 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ STATUS = training                                       │
│ §0  [collapsed read-only — recette + aug bakées visibles]│
│ §T  [nouveau — Training monitor]                        │
│      - Progress bar epoch N/total                      │
│      - Loss courante + loss best                       │
│      - Temps écoulé / ETA                              │
│      - Log tail (dernières 20 lignes)                  │
│      - Bouton "Stop" visible ici aussi                 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ STATUS = benchmarking                                   │
│ §0  [collapsed read-only]                              │
│ §T  [Training terminé — durée, modèle, version]        │
│ §B  [Benchmark en cours — spinner + info]              │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ STATUS = completed                                      │
│ §0  [collapsed read-only]                              │
│ §T  [Training summary — durée, epochs, best loss]      │
│ Métriques R@1/R@3/R@5/spread                           │
│ AugmentationsGallery                                   │
│ AugVsRealSection                                       │
│ BuildTestAppSection                                    │
│ LiveTestsSection                                       │
└─────────────────────────────────────────────────────────┘
```

---

## Design détaillé des sections à créer/modifier

### §0 — Pipeline (refacto)

**Comportement actuel** : `v-if="isPending"` → disparaît au launch.

**Comportement cible** :
- Toujours visible, mais mutable seulement si `pending`
- Quand `training|benchmarking|completed` : collapsé par défaut,
  expand au click, en lecture seule
- Affiche : nom recette (pas juste l'UUID), variant count, nb aug bakées

**Props collapsed** :
```
§0 PIPELINE    [recipe: hell-yeah · 800 aug bakées · 50 var/classe]  ▶
```

**Props expanded (non-pending)** :
```
§0 PIPELINE
  Recette     hell-yeah (recipe uuid)
  Aug bakées  800 samples (16 pièces × 50)
  Seed        629638355
```

---

### §T — Training monitor (nouveau)

Section visible uniquement quand `status === 'training'`.

Nécessite un **nouvel endpoint backend** :

```
GET /lab/runner/current-task
→ {
    iteration_id: str,
    phase: "bake" | "training" | "export" | "benchmark",
    epoch_current: int | null,
    epoch_total: int | null,
    loss_current: float | null,
    loss_best: float | null,
    elapsed_seconds: int,
    started_at: str,
    log_tail: [str]   // dernières N lignes du subprocess
  }
```

L'`IterationRunner` devrait écrire cette state dans une structure
partagée (in-memory ou fichier `.json` sous `ml/state/runner_state.json`)
mise à jour epoch par epoch.

Actuellement le runner track `_active_proc` et `_active_iteration_id`
mais ne persiste pas les métriques en cours.

**Alternative plus simple** : parser le fichier log du subprocess sur
le `GET /runner/current-task`. La `train_embedder.py` écrit déjà sur
stdout `Epoch [N/total] loss: X.XXXX` — suffit de regex ça.

**UI de la section** :

```
┌───────────────────────────────────────────────────────────────┐
│ §T TRAINING                              [🔴 Stopper]        │
│                                                              │
│ Epoch 12 / 40  ████████████░░░░░░░░░░░░░░  30%             │
│ Loss : 0.8421  Best : 0.8102                                │
│ Temps : 4 min 23 s  · ETA : ~10 min                        │
│                                                              │
│ Logs ──────────────────────────────────────────────         │
│ [14:32:01] Epoch [11/40] loss: 0.8512 acc: 0.7823          │
│ [14:32:14] Epoch [12/40] loss: 0.8421 acc: 0.7891          │
│ ...                                              [↓ expand] │
└───────────────────────────────────────────────────────────────┘
```

**Polling** : le composant poll `/runner/current-task` toutes les 2s
tant que l'iteration est `training`. TanStack Query avec
`refetchInterval: 2000`.

---

### §T — Training summary (post-training)

Visible quand `status ∈ {benchmarking, completed, failed}`.

Données à afficher (déjà en partie dans `iteration.training_summary`) :

```
Training terminé
  Durée      14 min 12 s
  Epochs     40
  Best loss  0.7823
  Version    v3 (training_run_id)
```

Ces données viennent de `iteration.training_summary` que le runner
remplit déjà. Juste besoin de les surfacer à côté du §0 collapsed
plutôt que dans la section Inputs cachée.

---

### Réorganisation générale de la page

**Ordre cible** (de haut en bas) :

```
1. Header (titre, statut, dates, actions)
2. Banner In-progress / Failed (si applicable)
3. §0 Pipeline — toujours visible (mutable si pending, readonly sinon)
4. §T Training monitor — si training
   OR Training summary — si post-training
5. Métriques grid R@1/R@3/R@5/spread (si benchmark data)
6. Delta par zone / par pièce / par axe (si data)
7. AugmentationsGallery
8. AugVsRealSection
9. BuildTestAppSection
10. LiveTestsSection
11. Notes / verdict sidebar (reste une sidebar)
```

---

## Changements backend requis

### B-001 — Exposer les métriques de training en cours

**Fichier** : `ml/serving/iteration_runner.py` + `ml/serving/server.py`

Ajouter dans `IterationRunner` une structure `_current_task_state: dict`
mise à jour par `_chain_steps` :
- Au début du training : `{phase: "training", epoch: 0, loss: null, started_at: ...}`
- Après chaque epoch (en parsant le log du subprocess stdout) : epoch + loss mis à jour
- Au benchmark : `{phase: "benchmark", ...}`

Endpoint : `GET /lab/runner/current-task` → retourne `_current_task_state`
ou `{"busy": false}` si rien en cours.

**Alternative lazy** : endpoint `GET /lab/runner/logs?iteration_id=<iid>&tail=20`
qui lit le dernier `.log` de ce training sans toucher au runner.

### B-002 — Recipe name dans la réponse iteration

**Fichier** : `ml/serving/lab_routes.py`

Actuellement `iteration.recipe_id` est un UUID. Joindre `recipe.name`
dans la réponse de `GET /lab/cohorts/{cid}/iterations/{iid}` pour
éviter un 2e round-trip front.

```json
{
  "recipe_id": "066c75c654c5",
  "recipe_name": "hell-yeah"   // ← nouveau
}
```

---

## Changements frontend requis

### F-001 — §0 collapsé en lecture seule post-pending

**Fichier** : `IterationDetailPage.vue`

Retirer le `v-if="isPending"` sur §0. Remplacer par :
- `isPending` → mode édition complet (actuel)
- `!isPending` → panel collapsed affichant recette (par nom) + aug bakées

### F-002 — Nouveau composant TrainingMonitorSection.vue

**Fichier** : `admin/packages/web/src/features/lab/components/TrainingMonitorSection.vue`

Composant déclaratif :
- Props : `cohortId`, `iterationId`, `status`, `trainingStartedAt`
- Interne : `useRunnerCurrentTaskQuery(iterationId)` (TanStack, interval 2s)
- Affiche : epoch progress bar, loss, ETA, log tail
- Visible uniquement si `status === 'training'`

### F-003 — Composant TrainingSummaryChip.vue (ou section inline)

Affiche les données de training terminé (`training_summary`) à côté
de §0 collapsed, visible dès que `status ∈ {benchmarking, completed}`.

### F-004 — Recipe name dans §0 collapsed et dans Inputs

Utiliser `iteration.recipe_name` (cf B-002) pour afficher le nom humain
plutôt que l'UUID.

---

## Open questions

**OQ-1 — Source des métriques epoch** :

Option A : parser stdout du subprocess dans `IterationRunner` → écrire
dans `_current_task_state` à chaque ligne. Plus robuste mais couplé
au format de sortie de `train_embedder.py`.

Option B : `train_embedder.py` écrit un fichier JSON
`ml/state/training_progress/<iid>.json` après chaque epoch. L'endpoint
lit ce fichier. Moins couplé, plus résilient si le runner redémarre.

Reco : **Option B**. Le fichier est atomique (écriture JSON → rename),
ne nécessite pas de modifier le runner, et le front lit juste un fichier.

**OQ-2 — Granularité du polling** :

2s est raisonnable (une epoch = 30-120s), mais ça fait des requêtes
fréquentes. Alternatives : long-polling (GET bloquant 30s) ou SSE
(EventSource). Pour la v1, 2s HTTP court suffit. Si le serveur est
sous charge, passer à 5s.

**OQ-3 — Afficher les logs ou juste les métriques** :

Les logs complets (`train_embedder.py` stdout) sont longs et techniques.
Pour la v1, afficher uniquement :
- epoch courant / total
- loss courant + best
- temps écoulé / ETA

Les logs bruts = toggle "Voir les logs" → un textarea scrollable.
Valeur de debug haute, valeur daily-use basse. Le toggle garde l'UI propre.

**OQ-4 — §0 collapsed : toujours collapsed ou restorer l'état expand** :

Reco : collapsed par défaut post-training. L'utilisateur n'a pas besoin
de re-voir la config sauf pour copier l'itération. Le collapse économise
de la verticalité sur la page qui va grossir avec les sections T/B.

---

## Prochaine session — liste d'actions concrètes

Ordre recommandé (par valeur / effort) :

1. **B-002** : ajouter `recipe_name` dans la réponse iteration (5 min)
2. **F-001** : §0 collapsed read-only post-pending (1h)
3. **B-001 (option B)** : écriture `training_progress/<iid>.json` dans
   `train_embedder.py` après chaque epoch (30 min)
4. **Endpoint GET /lab/runner/training-progress/<iid>** qui sert ce fichier
   (15 min)
5. **F-002** : `TrainingMonitorSection.vue` (1.5h)
6. Intégrer §T dans `IterationDetailPage.vue` (30 min)

Total estimé : **~4h** pour avoir le training monitor opérationnel.

---

## Historique de la page — ce qui a évolué en session 2026-04-30

- **Ajout RecipeConfigurator inline** (§0) : le configurateur de recette
  est maintenant embarqué dans la page itération, plus besoin d'aller
  sur `/augmentation` pour créer/modifier une recette.
- **Suppression du bouton "Régénérer" dans la galerie** : il y avait deux
  boutons Régénérer, l'un dans §0 (correct) et l'un dans la galerie
  (redondant). Galerie gardée en lecture seule avec juste le bouton Purger.
- **Cache-busting des images** : `?v=${augQuery.dataUpdatedAt.value}` sur
  les URLs des thumbnails pour forcer un refetch après une régénération.
- **Fix ExternalLink** : import lucide manquant dans la section Inputs.
- **Configurateur reste ouvert après save** : `onRecipeSaved` ne ferme
  plus le configurateur ; la prévisualisation reste visible. Auto-regenerate
  préview après la sauvegarde de recette.
- **Strict bake enforcement** : `launch_training` vérifie que TOUTES les
  pièces sont entièrement bakées (≥ variant_count samples) avant de lancer.
