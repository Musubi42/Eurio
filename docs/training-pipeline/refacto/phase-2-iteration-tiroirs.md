# Phase 2 — Iteration en 4 tiroirs (I1 · I2 · I3 · I4)

> Pré-requis : phase 1 livrée (le composant `DrawerSection.vue` existe
> et est utilisé par `CohortDetailPage`). Avoir lu `vision.md` §
> "Iteration — 4 tiroirs".
> Sortie : `IterationDetailPage.vue` est restructurée en 4 tiroirs.

## Objectif

`IterationDetailPage.vue` (814 lignes) est aujourd'hui une page-tartine.
Cette phase :

1. Backend : un endpoint `GET /lab/cohorts/{cid}/iterations/{iid}/progress`
   qui agrège l'état des 4 tiroirs.
2. Front : 4 composants tiroirs qui enveloppent la logique existante.
3. La page maître orchestre les 4 tiroirs et le polling.

**Le training monitor (les guts du tiroir I3 quand training tourne)
arrive en phase 5.** Cette phase pose la coquille de I3 mais affiche
juste un placeholder pendant le run.

## États par tiroir

| Tiroir | Empty | Partial | Ready | Running |
|---|---|---|---|---|
| I1 Recipe | `recipe_id == null` | (n/a) | recipe attachée | (n/a) |
| I2 Bake | `total_samples == 0` | `total_samples < total_expected` | tout bakké | bake en cours (ce sera surtout instantané, voir B2) |
| I3 Training | `status == 'pending'` (avant launch) | (n/a) | `status == 'completed'` | `status ∈ {training, benchmarking}` |
| I4 Eval | aucun sous-tiroir touché | au moins 1 | tous les 4 | un sous-tiroir en cours |

## Backend

### B1 — Endpoint `GET /lab/cohorts/{cid}/iterations/{iid}/progress`

**Fichier** : `ml/api/lab_routes.py`

**Position** : après `get_iteration` (ligne 473), avant `update_iteration`.

**Réponse** :

```json
{
  "i1": {
    "state": "ready",
    "recipe_id": "066c75c654c5",
    "recipe_name": "hell-yeah",
    "variant_count": 50
  },
  "i2": {
    "state": "ready",
    "total_expected": 800,
    "total_baked": 800,
    "per_coin": [
      {"eurio_id": "fr-1999-2eur", "numista_id": 12345, "baked": 50, "expected": 50, "skipped_reason": null}
    ]
  },
  "i3": {
    "state": "running",
    "status": "training",
    "training_run_id": "abc...",
    "benchmark_run_id": null,
    "started_at": "2026-04-30T...",
    "finished_at": null
  },
  "i4": {
    "state": "empty",
    "studio": {"state": "empty", "r_at_1": null},
    "aug_vs_real": {"state": "empty", "computed_at": null, "mean_cosine": null},
    "test_app": {"state": "empty", "model_ready": false},
    "live_tests": {"state": "empty", "total": 0, "recall_at_1": null}
  }
}
```

**Calcul** :

- **I1** : lire `iteration.recipe_id`. Si non null, joindre
  `recipe.name` via store (cf déjà demandé en post-sprint 5 G-005 / B-002).
- **I2** : pour chaque coin de la cohort, compter
  `len(glob ml/datasets/<nid>/augmentations/<iid>/sample_*.jpg)`.
  - `total_expected = total_coins × variant_count`
  - `state = 'ready'` ssi tous les coins ont `baked >= variant_count`
  - skipped_reason si pas de numista_id ou pas d'obverse (réutilise
    la logique de `iteration_augmentations.list_for_iteration` pour
    les paths).
- **I3** : dérivé de `iteration.status`.
  - `pending` → `state='empty'`
  - `training`/`benchmarking` → `state='running'`
  - `completed` → `state='ready'`
  - `failed` → `state='partial'` (avec `failure_reason` exposé)
- **I4** : 4 sous-blocs.
  - studio : si `iteration.benchmark_run_id` et `r_at_1` présents.
  - aug_vs_real : `state.list_aug_vs_real(iid)` non vide ?
  - test_app : reuse `cohort_test_build_info`, `model_ready` true.
  - live_tests : `state.list_live_tests(iid)` non vide.
  - `i4.state` = agrégat (`ready` si les 4 sous-tiroirs sont au moins
    `ready`, `partial` si ≥1 et <4, `empty` sinon).

**Code** : ~120 lignes. Un helper `_iteration_progress(it)` peut être
factorisé.

### B2 — Endpoint `POST /lab/cohorts/{cid}/iterations/{iid}/bake`

**But** : exposer le bake comme une action explicite du tiroir I2,
indépendamment du launch training.

**Statu quo** : `regenerate-augmentations` existe (ligne 920) mais
fait à la fois clear+rebake. Le user veut un bouton "Bake" qui :
- échec si I1 pas `ready`
- skip silencieux si tout est déjà bakké (idempotent)
- rebake les coins partiels uniquement
- retourne le rapport per-coin

**Réponse** :

```json
{
  "ok": true,
  "total_baked": 800,
  "reports": [
    {"eurio_id": "fr-1999-2eur", "written": 50, "sources_used": 1}
  ]
}
```

Pas de stream — le bake est rapide (quelques secondes pour 50 samples
× 16 coins). Si on doit le rendre async plus tard, on dérivera vers
SSE. v1 = synchrone, response après bake.

**Implémentation** : appelle `iteration_augmentations.generate_for_iteration`
(qui est déjà idempotent : si le nb de samples sur disque ≥ target,
skip le coin).

`regenerate-augmentations` reste pour le cas "force rebuild" (I1 a
changé de recipe → on wipe et on rebake).

### B3 — Recipe name dans la réponse iteration

**Fichier** : `ml/api/lab_routes.py` `get_iteration` (ligne 473) et
`_iteration_with_run_metrics` (ligne 214).

Joindre `recipe.name` quand `recipe_id` non null. Champ `recipe_name`
ajouté au payload existant.

## Frontend

### F1 — Composants tiroirs

#### `IterationDrawerI1.vue`

**Body** : embarque le `<RecipeConfigurator>` existant + le sélecteur
de pièce de preview. C'est ce qui est aujourd'hui dans §0 de
`IterationDetailPage`.

**Mutable** : seulement si `iteration.status === 'pending'`. Sinon
read-only (recipe_name + variant_count affichés, configurateur
masqué).

**Header summary** :
- empty : "Aucune recipe sélectionnée"
- ready (pending) : `{recipe_name} · {variant_count} samples / pièce`
- ready (post) : `{recipe_name} · figée`

#### `IterationDrawerI2.vue`

**Body** :
- bouton "Générer les augmentations" (calls
  `POST .../iterations/<iid>/bake`)
- pendant le bake : spinner + "baking…" (la réponse arrive synchrone)
- après : `<AugmentationsGallery>` existant
- bouton "Régénérer" (force, calls
  `POST .../augmentations/regenerate`)

**Locked** : si I1 non `ready`.

**Header summary** :
- empty : "Aucune augmentation bakée"
- partial : "{baked}/{total_expected} samples — {N} coins manquants"
- ready : "{total_expected} samples (16 × 50) · obverse uniquement"

Le "obverse uniquement" est literal — c'est un rappel visuel constant
de la règle (cf phase 3).

#### `IterationDrawerI3.vue` (coquille uniquement)

**Body conditionnel** :
- `pending` : carte runtime + bouton "Lancer training" (la carte
  runtime arrive en phase 4, en attendant on affiche un placeholder
  "Runtime: TODO phase 4")
- `training`/`benchmarking` : placeholder "Training en cours…
  monitor live arrive en phase 5" + bouton Stop existant
- `completed` : recap (durée, epochs, best loss, R@1) — extrait de
  `iteration.training_summary` qui est déjà rempli par le runner
- `failed` : message d'erreur + bouton "Retry"
  (= `POST .../launch-training`)

**Locked** : si I2 non `ready`.

**Header summary** :
- empty/pending : "Pas encore lancé"
- running : "Training en cours · epoch ?/?"  (le ?/? sera filled en
  phase 5)
- ready : "Training terminé · R@1 = {x}"
- partial (failed) : "Training échoué · {error}"

#### `IterationDrawerI4.vue` (méta)

**Body** : 4 sous-tiroirs `<DrawerSection>` imbriqués qui chacun
embarquent le composant existant :
- I4a Studio : recap métriques (R@1/R@3/R@5/spread) + section "Delta"
  + `<PerConditionTable>` si data
- I4b Aug↔Real : `<AugVsRealSection>`
- I4c Build APK : `<BuildTestAppSection>`
- I4d Live tests : `<LiveTestsSection>`

**Locked** : si I3 non `ready`.

**Header summary** :
- empty : "Pas encore évaluée"
- partial : "{n}/4 sous-tiroirs commencés"
- ready : "Studio R@1={x} · Cosine={y} · Live={z}"

### F2 — `IterationDetailPage.vue` refacto

**Stratégie** : rewrite complet (la page actuelle est trop empilée
pour être patch-refactor proprement).

**Squelette** :

```vue
<template>
  <div class="page">
    <Header /> <!-- inchangé : titre, badge, dates, Stop, Supprimer -->
    <BannerInProgress v-if="isRunning" />
    <BannerFailed v-if="isFailed" />

    <IterationDrawerI1 :iteration :progress="progress.i1" />
    <IterationDrawerI2 :iteration :progress="progress.i2" :locked="!progress.i1.ready" />
    <IterationDrawerI3 :iteration :progress="progress.i3" :locked="!progress.i2.ready" />
    <IterationDrawerI4 :iteration :progress="progress.i4" :locked="!progress.i3.ready" />

    <NotesSidebar /> <!-- inchangé -->
  </div>
</template>
```

**Polling** : `useIterationProgressQuery(iid)` avec
`refetchInterval: 2000` quand `status ∈ {training, benchmarking}`,
sinon `5000`. Quand le polling détecte un changement de status,
invalider la query principale `iteration` pour récupérer les
métriques rafraîchies.

### F3 — Composables

**Fichier** : `useLabApi.ts`

```ts
export async function fetchIterationProgress(cohortId: string, iid: string): Promise<IterationProgress>
export async function bakeIterationAugmentations(cohortId: string, iid: string): Promise<BakeResult>
```

**Fichier** : `useLabQueries.ts`

```ts
export function useIterationProgressQuery(cohortId, iterationId, status) {
  return useQuery({
    queryKey: [...LAB_KEYS.iterations, iterationId.value, 'progress'],
    queryFn: () => fetchIterationProgress(cohortId.value, iterationId.value),
    refetchInterval: () => {
      const s = status.value
      if (s === 'training' || s === 'benchmarking') return 2000
      return 5000
    },
  })
}

export function useBakeMutation(cohortId, iterationId) { ... }
```

Invalidate `iteration` + `progress` + `augmentations` après bake.

### F4 — Types

```ts
export interface IterationProgressI1 { state: DrawerState; recipe_id: string|null; recipe_name: string|null; variant_count: number }
export interface IterationProgressI2 { state: DrawerState; total_expected: number; total_baked: number; per_coin: Array<{eurio_id, numista_id, baked, expected, skipped_reason}> }
export interface IterationProgressI3 { state: DrawerState; status: string; training_run_id: string|null; benchmark_run_id: string|null; started_at: string|null; finished_at: string|null; failure_reason: string|null }
export interface IterationProgressI4 { state: DrawerState; studio: ...; aug_vs_real: ...; test_app: ...; live_tests: ... }
export interface IterationProgress { i1, i2, i3, i4 }
```

## Critère de succès

1. `curl .../iterations/<iid>/progress` retourne `{i1, i2, i3, i4}`
   cohérent sur :
   - une iteration `pending` sans recipe → I1 empty
   - une iteration `pending` avec recipe + bake partial → I1 ready, I2 partial
   - une iteration `completed` → I1, I2, I3 ready, I4 ≥ partial
   - une iteration `failed` → I3 partial avec failure_reason
2. `IterationDetailPage` affiche les 4 tiroirs visuellement avec les
   bons gates (un tiroir en aval reste lockable visuellement quand
   le précédent n'est pas ready).
3. Toggle bake : click "Générer", spinner, retour, galerie pleine.
4. Pendant un training (déclenché manuellement) :
   - I3 affiche "Training en cours…" (placeholder)
   - le bouton Stop fonctionne
   - quand le training se termine, I3 passe à ready, I4 devient
     interactif sans reload manuel
5. `pnpm tsc --noEmit` clean. `pnpm vite build` clean.

## Pièges connus

- **Re-rendering polling** : la query progress se re-run toutes les 2s
  pendant un training. Bien gérer la diff dans Vue : si le payload
  est identique, ne pas re-render les sous-composants. Utiliser
  `keepPreviousData: true` côté TanStack pour éviter les flickers.
- **Le bouton "Lancer training" ne déclenche pas un bake**. Le bake
  doit avoir été fait via I2. Le runner enforce déjà ce contrat
  (cf `_launch_training` qui appelle `generate_for_iteration`, mais
  c'est un re-bake idempotent — pas un fail-if-empty). Aligner :
  `launch_training` doit fail si I2 n'est pas ready (ajouter une
  pré-vérif sur le total_baked attendu, dans `lab_routes.py:450`).
- **Recipe change après bake** : `update_iteration` (ligne 481) wipe
  déjà les augmentations sur disque quand recipe_id ou variant_count
  changent. Vérifier que I2 retombe en `empty` automatiquement après
  ça (le polling progress le verra).
- **I4c (build APK) dépend de l'export TFLite** qui peut foirer
  silencieusement (cf sprint 4 OQ-decisions). Si `model_ready=false`
  alors que `iteration.status='completed'`, I4c affiche `partial`
  avec un message "TFLite manquant — relance `python -m
  training.export_tflite`". Statu quo Sprint 4, juste exposé
  proprement dans le tiroir.

## Hors-scope

- **Le contenu live du training** (epoch/loss/log tail) — c'est la
  phase 5.
- **La carte runtime dans I3** — c'est la phase 4.
- **L'A/B comparaison entre iterations** — pas dans ce refacto.
- **Modification du composant `RecipeConfigurator`** — il reste tel
  quel, juste embarqué dans I1.
