# PRD Bloc 2 — Notes d'implémentation (2026-04-19)

> Résumé de la session Studio admin. À lire au démarrage de la session Bloc 3 (Benchmark) ou pour reprendre une itération UX sur le Studio.

## Ce qui a été livré

### Docs (Qs tranchées)

- [02-augmentation-studio.md](./02-augmentation-studio.md) §9 — Q1 et Q8 marquées **résolues par Bloc 1** (extension `/training/stage` + migration `training_runs.aug_recipe_id`). Q2-Q7 actées avec leurs défauts.

### Routing + structure feature

| Fichier | Changement |
|---|---|
| `admin/packages/web/src/app/router.ts` | Route lazy `/augmentation` → `AugmentationStudioPage.vue` |
| `admin/packages/web/src/features/augmentation/` | Nouveau feature module |

### Types + API

| Fichier | Rôle |
|---|---|
| `features/augmentation/types.ts` | `Recipe`, `Layer`, `LayerSchema`, `ParamSchema`, `RecipeRow`, `PreviewImage`, `PreviewResponse`, `OverlaysResponse`, `AugmentationSchemaResponse` |
| `features/augmentation/composables/useAugmentationApi.ts` | Wrappers fetch vers `/augmentation/schema`, `/overlays`, `/preview`, CRUD `/recipes`, `stageForTraining` |
| `features/augmentation/composables/useStagedCoins.ts` | Résout `?eurio_ids=` → `Coin[]` via Supabase, gère `activeIndex` |
| `features/augmentation/composables/useRecipeState.ts` | Recipe courante + baseline + `dirty` + `ensureLayersFromSchema` + `isParamDirty` |

### Page principale + subcomposants

| Fichier | Rôle |
|---|---|
| `features/augmentation/pages/AugmentationStudioPage.vue` | Page racine — layout 3 panneaux, compare mode, seed, regenerate, handoff training, lightbox, offline degradation |
| `features/augmentation/components/StagedCoinsList.vue` | Panneau gauche (thumbnail + zone badge + statut par coin) |
| `features/augmentation/components/PreviewGrid.vue` | Grille 4×4 avec shimmer loading et ouverture lightbox |
| `features/augmentation/components/RecipeConfigurator.vue` | (Non créé — fonctionnalité inlinée dans la page) |
| `features/augmentation/components/LayerSection.vue` | Section collapsible par layer avec contrôles dynamiques |
| `features/augmentation/components/ParamControl.vue` | Dispatch float/int/bool/string/list[float]/list[string] → slider/input/toggle/select/multi |
| `features/augmentation/components/SaveRecipeModal.vue` | Modale de sauvegarde (name kebab-case + zone optionnelle) |

### CoinsPage — bouton d'entrée

| Fichier | Changement |
|---|---|
| `features/coins/pages/CoinsPage.vue` | 3ᵉ bouton sticky `Augmenter` entre `Ajouter et voir` et `Ajouter au training`. Cap 20 coins (badge "20 max" si dépassé). Disabled si ML API offline |

## Contrats UX gravés

### URL shareable

Toute navigation vers le Studio passe par `/augmentation?eurio_ids=a,b,c`. Pas de store partagé. L'URL est la seule source d'état.

### Layout

- **Mode normal** : `240px + 1fr + 360px` (staged · grid · configurator)
- **Mode compare** : `240px + 1fr + 1fr` (staged · slot A grid · slot B grid + configurator empilé)

### Flux handoff training

1. User sauvegarde la recette active (Save recipe modal) → obtient un `recipeId`
2. Clic `Envoyer au training` → POST `/training/stage` avec `aug_recipe_id` par item (soit la recipe active uniforme, soit un mapping custom via `coinRecipeAssignment`)
3. Navigation `/training` — le training page résout l'aug_recipe au démarrage du run (Bloc 1)

### Offline degradation

Pattern identique à `ConfusionMapPage` / `TrainingPage` :
- Healthcheck initial + poll 30s sur `/health`
- Banner rouge full-width quand offline avec CTA `go-task ml:api`
- Panneaux désactivés (pas seulement cachés — l'UX doit indiquer pourquoi rien ne répond)

## État de type-check

- **26/26 tests Python Bloc 1** passent (`cd ml && .venv/bin/python -m pytest tests/ -q`)
- **vue-tsc sur `features/augmentation/*`** : 0 erreur
- Les erreurs restantes dans le build global (`features/sets/*`, `features/audit/*`) sont **pré-existantes** et sans lien avec cette session

## Décisions techniques notables

### Slot state avec `reactive + UnwrapNestedRefs`

Chaque slot (A et B) est un objet wrappé dans `reactive()` pour que les refs du composable `useRecipeState` soient unwrappées nested (runtime + type). Le type `Slot` utilise `UnwrapNestedRefs<ReturnType<typeof useRecipeState>>` pour rester synchrone avec le composable sans duplication.

Bénéfice : on écrit `slot.state.dirty` partout (bool en lecture, pas de `.value` plumbing). Template et script restent cohérents.

### Zones "green/red" via recipes custom par zone

L'API `/schema` ne renvoie qu'un `default_recipe` (orange). Pour charger un preset `green` ou `red`, le Studio cherche **la recette custom la plus récente avec `zone === 'red'`**. Si aucune n'existe → fallback sur default_recipe avec le nom de la zone marqué comme baseline (pour que Save respecte l'intention).

C'est une simplification v1 — le banc Bloc 3 pourra promouvoir automatiquement la meilleure recette par zone via benchmark uplift.

### Preset selector value format : `"zone:<name>"` ou `"custom:<id>"`

Le select HTML a besoin d'une chaîne. On namespace avec `zone:` vs `custom:` pour dispatcher correctement dans `applyPresetString`.

### Gestion design_group_id côté entrée

Le bouton `Augmenter` résout chaque class_id sélectionné sur `/coins` vers le `eurio_id` du coin visible dans la liste. Si un user sélectionne un design_group, on prend l'eurio_id du coin représentatif affiché. Pour v1, on ne navigue pas les membres du groupe côté Studio — le dev verra le coin affiché, pas toute la famille.

## Ce qui reste pour Bloc 3 (Benchmark)

Toutes les dépendances Bloc 1 sont livrées (table `augmentation_recipes`, FK `benchmark_runs.recipe_id` valide, `training_runs.aug_recipe_id` pour la chaîne de traçabilité).

Le Studio handoff passe déjà `aug_recipe_id` à `/training/stage` — donc chaque training produit depuis le Studio aura son recipe tracé sur `training_runs.aug_recipe_id` automatiquement. PRD03 peut consommer cette chaîne tel quel.

## Points d'attention & dette identifiée

- **`paramDirtyChecker`** créé à chaque render : la `closure` retournée par cette fn crée une nouvelle référence de callback à chaque render Vue, ce qui peut casser des optimisations de mémoization côté `LayerSection`. Pour v1 c'est OK (pas de grosse liste), à refacto si perf devient un problème.
- **Pas de debounce sur `Regenerate`** : double-clic génère deux runs back-to-back côté serveur. Le backend n'en souffre pas (FS + SQLite), mais v1.5 pourrait debouncer 200ms.
- **Zones green/red fallback sur default_recipe** : voir décision ci-dessus — pas idéal mais simple. Le Benchmark (Bloc 3) traite ce cas proprement en créant des recettes nommées `green-v1` / `red-v1` dès le premier training par zone.
- **Compare mode v1 : slot B toujours à droite, pas réorderable** : OK pour v1.
- **Pas de per-coin recipe assignment UI** : `coinRecipeAssignment` existe dans le state mais l'UI n'expose pas de mapping. V1.5 ajoutera un dropdown par coin dans `StagedCoinsList` si besoin.
- **Lightbox basique** : pas de zoom progressif, pas de navigation flèches entre variantes. Suffisant pour v1.
- **Save recipe modal ne propose pas de tags** : le PRD02 §4.3 mentionnait des tags ; je n'ai pas câblé la table (tags nulle part côté Bloc 1). v2 si besoin.

## Comment tester manuellement

```bash
# 1. Démarre ML API
cd ml && go-task ml:api

# 2. Démarre admin web
cd admin/packages/web && pnpm dev

# 3. Dans le navigateur :
# - Va sur /coins
# - Sélectionne 3-5 coins (une zone cohérente idéalement)
# - Clique "Augmenter" dans le footer
# - Le studio s'ouvre avec le preset orange par défaut
# - Bouge un slider (ex: relighting.ambient), clique Regenerate
# - Save la recipe sous un nom kebab-case
# - Toggle Compare, bouge un autre slider dans le slot B
# - Clic "Envoyer au training" → navigation /training avec items staged
```

## Références croisées

- [`PRD01-implementation-notes.md`](./PRD01-implementation-notes.md) — Bloc 1, backend + contrats API.
- [`02-augmentation-studio.md`](./02-augmentation-studio.md) — PRD original + décisions.
- [`03-real-photo-benchmark.md`](./03-real-photo-benchmark.md) — PRD Bloc 3, à attaquer ensuite.
