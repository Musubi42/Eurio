# Phase 1 — Cohort en 2 tiroirs (C1 sélection · C2 captures)

> Pré-requis : avoir lu `inventory.md` et `vision.md`.
> Sortie : `CohortDetailPage.vue` est restructurée en 2 tiroirs avec
> état dérivé du backend, et le bouton "Nouvelle itération" est gated
> par C2.

## Objectif

Aujourd'hui `CohortDetailPage.vue` empile sections : §1 Pièces, §2
Captures, trajectoire, iterations. C'est OK mais il manque le contrat
"étape par étape" : on ne voit pas qu'il **faut** que C2 soit complet
avant de créer une iteration utile.

Cette phase :
1. Crée un composant `DrawerSection.vue` réutilisable (header lisible
   + body collapse + état coloré).
2. Backend : un endpoint `GET /lab/cohorts/{id}/progress` qui renvoie
   l'état dérivé de C1 et C2 calculé depuis le disque + DB.
3. Front : `CohortDetailPage.vue` enveloppe les sections existantes
   dans 2 tiroirs.

**Aucune logique métier n'est touchée**, c'est purement UX +
exposition de l'état.

## États possibles d'un tiroir

```ts
type DrawerState =
  | 'empty'    // rien fait
  | 'partial'  // commencé, pas valide pour gate
  | 'ready'    // valide pour gate (= "done" du POV utilisateur)
  | 'running'  // une action async tourne (bake, training, sync)
```

(`done` n'est pas un état distinct de `ready` ici — un tiroir reste
`ready` après validation, on n'a pas besoin d'historiser.)

Convention couleur :
- empty → gris
- partial → orange
- ready → vert
- running → bleu animé

## Backend

### B1 — Endpoint `GET /lab/cohorts/{cohort_id}/progress`

**Fichier** : `ml/api/lab_routes.py`

**Position** : après `get_cohort` (ligne 290), avant `update_cohort`.

**Réponse** :

```json
{
  "c1": {
    "state": "ready",
    "total_coins": 16,
    "missing_obverse": []
  },
  "c2": {
    "state": "partial",
    "expected_per_coin": 6,
    "fully_captured": 14,
    "partial": 1,
    "missing": 1,
    "per_coin_missing": [
      {"eurio_id": "fr-1999-2eur", "missing_steps": ["tilt_plain", "tilt_perturbed"]},
      {"eurio_id": "be-2024-1eur", "missing_steps": ["bright_plain","dim_plain","bright_perturbed","dim_perturbed","tilt_plain","tilt_perturbed"]}
    ]
  }
}
```

**Calcul C1** :
- `total_coins = len(cohort.eurio_ids)`
- pour chaque `eurio_id`, résoudre `numista_id` via `coin_lookup`,
  vérifier que `ml/datasets/<nid>/obverse.{jpg,png}` existe.
- `state = 'empty'` si total_coins == 0
- `state = 'partial'` si missing_obverse non vide
- `state = 'ready'` sinon

**Calcul C2** : réutilise la logique de l'endpoint
`/cohorts/{id}/captures/status` existant (ligne 689 de `lab_routes.py`).
- `state = 'empty'` si `fully_captured == 0 && partial == 0`
- `state = 'partial'` si `missing > 0 || partial > 0`
- `state = 'ready'` si tous les coins ont les 6 captures

**Constante** : `CAPTURE_STEPS` est déjà définie dans `lab_routes.py`
(à grep). Le nombre attendu est `len(CAPTURE_STEPS)`.

**Code à écrire** : ~80 lignes incluant les helpers.

### B2 — Aucune autre modification backend

Les endpoints existants (`/coins`, `/captures/csv`, `/captures/sync`)
sont déjà OK. Le front les appelle déjà via `useLabApi.ts`.

## Frontend

### F1 — Composant `DrawerSection.vue`

**Fichier** : `admin/packages/web/src/features/lab/components/DrawerSection.vue`

**Props** :

```ts
interface Props {
  number: string         // "C1" / "I2" / "I4a"
  title: string          // "Sélection des pièces"
  state: DrawerState     // 'empty'|'partial'|'ready'|'running'
  summary: string        // "16 pièces · toutes obverse-ready"
  defaultOpen?: boolean  // open par défaut si state ∈ {empty,partial,running}
  locked?: boolean       // tiroir suivant pas encore débloqué
  lockReason?: string    // "Termine C1 d'abord"
}
```

**Slots** :
- `body` : contenu interactif

**Look** :
- Header cliquable : `[badge state] §{number} {title} · {summary}  ▶/▼`
- Body collapsé (animation height) sauf si `defaultOpen` ou si l'utilisateur a expand.
- Si `locked`, header grisé, click affiche un toast `lockReason`.

Pas de refacto cosmétique excessif — on veut une primitive simple.

### F2 — `CohortDrawerC1.vue`

**Fichier** : `.../components/CohortDrawerC1.vue`

**Props** : `cohortId, cohort, progress` (le bloc c1 du `/progress`).

**Body** : reprend ce qui est déjà dans `CohortDetailPage.vue` §1
Pièces (liste des coins, bouton remove). Si `progress.c1.state ===
'partial'`, afficher un encart orange listant les coins sans obverse,
avec un lien vers `/coins/<eurio_id>` pour qu'on puisse aller
réuploader.

**Header summary** :
- `empty` : "Aucune pièce — attache depuis /coins"
- `partial` : "{N} pièces · {K} sans obverse"
- `ready` : "{N} pièces · toutes obverse-ready"

### F3 — `CohortDrawerC2.vue`

**Fichier** : `.../components/CohortDrawerC2.vue`

**Body** : embarque `<CaptureSection :cohortId="cohortId">` qui existe
déjà (`components/CaptureSection.vue`). On ne refait pas la logique
CSV/push/pull/sync — juste on l'enrobe.

**Locked** : si `progress.c1.state !== 'ready'`, le tiroir est `locked`
avec lockReason `"Sélectionne d'abord toutes les pièces avec obverse."`

**Header summary** :
- `empty` : "Aucune capture"
- `partial` : "{fully}/{total} pièces complètes"
- `ready` : "{N} pièces × 6 captures · prêtes pour iteration"

### F4 — `CohortDetailPage.vue` refacto

**Fichier** : `pages/CohortDetailPage.vue`

**Changements** :
- Charger `useCohortProgressQuery(cohortId)` avec `refetchInterval:
  5000` (sync captures peut bouger).
- Remplacer §1 et §2 actuelles par `<CohortDrawerC1>` et
  `<CohortDrawerC2>`.
- Le bouton "Nouvelle itération" devient grisé si
  `progress.c2.state !== 'ready'`, avec tooltip
  `"Capture toutes les pièces avant de créer une iteration."`
- Le reste de la page (trajectoire, iterations existantes) **reste
  inchangé**, en dessous des tiroirs.

### F5 — Composables

**Fichier** : `composables/useLabApi.ts`

```ts
export async function fetchCohortProgress(cohortId: string): Promise<CohortProgress> {
  return getJson(`/lab/cohorts/${cohortId}/progress`)
}
```

**Fichier** : `composables/useLabQueries.ts`

```ts
export function useCohortProgressQuery(cohortId: Ref<string>) {
  return useQuery({
    queryKey: computed(() => [...LAB_KEYS.cohorts, cohortId.value, 'progress']),
    queryFn: () => fetchCohortProgress(cohortId.value),
    refetchInterval: 5000,
    staleTime: 2000,
  })
}
```

Invalidate sur :
- `attachCoin`/`detachCoin` (déjà invalide cohort)
- `syncCaptures` (existe)

### F6 — Types

**Fichier** : `types.ts`

```ts
export type DrawerState = 'empty' | 'partial' | 'ready' | 'running'

export interface CohortProgressC1 {
  state: DrawerState
  total_coins: number
  missing_obverse: string[]   // eurio_ids
}

export interface CohortProgressC2 {
  state: DrawerState
  expected_per_coin: number
  fully_captured: number
  partial: number
  missing: number
  per_coin_missing: Array<{ eurio_id: string; missing_steps: string[] }>
}

export interface CohortProgress {
  c1: CohortProgressC1
  c2: CohortProgressC2
}
```

## Critère de succès

1. `curl http://127.0.0.1:8042/lab/cohorts/<name>/progress` retourne
   un payload `{c1, c2}` cohérent (vérifié sur la cohort `green-v1`
   et la cohort `fe933e8571a1`).
2. `CohortDetailPage` affiche les 2 tiroirs avec les bons summaries.
3. Sur une cohort où une pièce manque d'obverse, C1 est `partial` et
   liste l'eurio_id concerné.
4. Le bouton "Nouvelle itération" est désactivé sur une cohort où C2
   n'est pas `ready`, avec tooltip explicite.
5. `pnpm tsc --noEmit` clean dans `lab/`.
6. `pnpm exec vite build` clean.
7. Aucun changement de schéma DB. Aucun fichier supprimé.

## Pièges connus

- **`coin_lookup.numista_id_for(eurio_id)` peut renvoyer `None`** pour
  les coins sans mapping Numista. Dans C1, on les classe en
  `missing_obverse` (un coin sans numista_id n'a pas de dossier sur
  disque, donc pas d'obverse trouvable). Logger un warning serveur,
  pas une erreur.
- **`expected_per_coin = len(CAPTURE_STEPS)`** — la constante existe
  déjà côté serveur, ne pas hardcoder 6 dans le front.
- **Les iterations existantes** restent affichées dans la liste sous
  les tiroirs. Une iteration créée avant ce refacto reste fonctionnelle.

## Hors-scope

- Pas de modification de `/coins`, `CohortAttachModal`, ou la modal
  d'attache.
- Pas de modification de la trajectoire ni de l'affichage des
  iterations existantes (c'est la phase 2).
- Pas d'ajout de tests automatisés Vue (la stack n'a pas de test
  runner front). Smoke test manuel via le navigateur.
- Pas d'animation fancy — un simple expand/collapse CSS suffit.
