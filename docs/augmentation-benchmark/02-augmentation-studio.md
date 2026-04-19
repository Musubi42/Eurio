# PRD Bloc 2 — Augmentation Studio (admin UI)

> Cockpit d'exploration visuelle des recettes d'augmentation : une vue admin Vue/Vite qui remplace la boucle "édite `recipes.py` → CLI → PNG → œil" par "slider → bouton → grille → œil". Consomme le moteur HTTP figé par le Bloc 1.

---

## 1. Contexte & motivation

Le Bloc 1 fige un moteur d'augmentation (`ml/augmentations/`) et l'expose via FastAPI. Pour régler les recettes `green` / `orange` / `red` sur des pièces réelles, le dev dispose aujourd'hui de `ml/preview_augmentations.py` : une CLI qui sort une grille PNG à regarder dans Finder. C'est fonctionnel mais :

- **Itération lente** : chaque tweak de param nécessite édition de `recipes.py`, re-run CLI, ouverture manuelle du PNG. ~15-20 s par tweak, attention coupée à chaque fois.
- **Pas de comparaison** : pour A/B visuel entre deux recettes, il faut générer deux grilles, les ouvrir côte à côte, naviguer entre fenêtres.
- **Pas de sauvegarde structurée** : une recette tweakée et validée n'a pas d'endroit évident où vivre — soit on commit dans `recipes.py` (trop tôt), soit on la perd.
- **Pas de handoff training** : une fois une recette validée, rien ne la relie aux coins qui ont servi à la valider. Le dev doit re-stager manuellement dans `/training`.

L'Augmentation Studio résout les quatre. C'est un outil **mono-utilisateur** (user = le dev), local-only, qui vit dans `admin/packages/web/` et dégrade proprement si la ML API est off.

Il s'inscrit dans la chaîne `Bloc 1 (moteur) → Bloc 2 (cockpit) → Bloc 3 (benchmark)` : le Studio sert à **explorer** les recettes qualitativement ; le Benchmark servira ensuite à les **départager** quantitativement par R@1 / spread.

---

## 2. User stories

| # | Rôle | Veux | Pour |
|---|---|---|---|
| US1 | Dev | Sélectionner 5 pièces zone rouge sur `/coins` et cliquer un bouton `Augmenter` | Passer directement de la cartographie au cockpit sans me retaper les ids |
| US2 | Dev | Voir les 16 variantes générées pour la pièce active en grille, avec le preset `red` chargé d'office | Comprendre en 2 s à quoi ressemble la recette actuelle sur cette pièce |
| US3 | Dev | Bouger un slider (ex. `relighting.normal_strength`) puis cliquer `Regenerate` et voir la grille se rafraîchir en ~3 s | Itérer vite sur un paramètre sans quitter le cockpit |
| US4 | Dev | Activer `fix seed` et regénérer après chaque tweak | Isoler l'effet d'un paramètre en neutralisant l'aléa |
| US5 | Dev | Basculer en mode Compare et afficher 2 grilles côte à côte avec 2 recettes différentes (même coin, même seed) | Trancher visuellement un A/B avant de sauvegarder |
| US6 | Dev | Sauvegarder la recette tweakée sous un nom lisible (`red-tuned-v2`) | La retrouver plus tard et la référencer depuis le Benchmark |
| US7 | Dev | Passer à la pièce suivante du panier avec la même recette active, regénérer, valider | Tester la recette sur plusieurs spécimens de la même zone |
| US8 | Dev | Une fois mes recettes validées, cliquer `Envoyer au training` pour staguer les coins + la recette par défaut | Fluidifier le chemin `augment → train` |

---

## 3. Scope in / out

### In (v1)

- Route admin `/augmentation` (feature module `admin/packages/web/src/features/augmentation/`).
- Bouton `Augmenter` ajouté au footer sticky existant de `CoinsPage.vue` (à côté de `Ajouter au training` et `Ajouter et voir →`).
- Staging multi-coins **via query params** : `/augmentation?eurio_ids=a,b,c`. Pas de store partagé, URL shareable.
- Layout 3 panneaux (coins stagés · grille preview · configurateur recipe).
- Preset selector alimenté par `ZONE_RECIPES` + recipes custom remontées depuis SQLite.
- Configurateur **dynamique** : lit `GET /augmentation/schema` pour générer les sliders/inputs — aucune duplication du schéma côté Vue.
- **Regenerate button-triggered** (pas d'auto-regen au tweak — chaque run coûte 2-5 s).
- Toggle **Fix seed** pour reproductibilité.
- **Save recipe** conditionnel (bouton grisé tant qu'aucun tweak détecté ; actif dès que la recipe courante diverge du preset chargé).
- **Compare mode v1** : deux grilles côte à côte, deux recettes différentes, même coin, même seed.
- **Handoff training** : bouton `Envoyer au training` qui POST vers `/training/stage` avec les coins + class_ids + la recette assignée.
- **Dégradation ML API offline** : page affiche un placeholder clair (pas de génération possible, pas de recettes lisibles — cohérent avec le fait que les recipes vivent en SQLite local).

### Out (v2+)

- Édition des textures overlays (upload, suppression) — read-only en v1, consommé depuis `GET /augmentation/overlays` pour info.
- Export d'une recipe DB en code Python commité dans `recipes.py` — v1.5 (dépend du Bloc 1).
- Historique des versions d'une recipe + rollback — v2.
- Partage de recipes entre utilisateurs — non pertinent (mono-utilisateur).
- Compare à 3+ recettes simultanées — v2 si besoin ; v1 se limite au binaire.
- Auto-tuning / suggestions de params via Benchmark — Bloc 3.

---

## 4. Spec UX

### 4.1 Layout 3 panneaux

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Augmentation Studio                                             [ML: online] │
│  5 pièces stagées · recette active : red-tuned-v2 (modifiée)                  │
│  ─────────                                                                    │
│                                                                               │
│  ┌──────────────┐  ┌───────────────────────────────────┐  ┌────────────────┐ │
│  │  STAGED      │  │  PREVIEW GRID (4×4)               │  │  RECIPE        │ │
│  │              │  │                                   │  │                │ │
│  │ ▸ FR-2€-2007 │  │  ┌────┬────┬────┬────┐           │  │  Preset ▾      │ │
│  │ ▸ DE-2€-2005 │  │  │    │    │    │    │           │  │  ─red─modifié─ │ │
│  │ ▪ ES-2€-2009 │  │  ├────┼────┼────┼────┤           │  │                │ │
│  │ ▸ IT-2€-2011 │  │  │    │    │    │    │           │  │  ▾ perspective │ │
│  │ ▸ NL-2€-2013 │  │  ├────┼────┼────┼────┤           │  │    tilt  [25°] │ │
│  │              │  │  │    │    │    │    │           │  │    prob  [0.7] │ │
│  │ Active : ES  │  │  ├────┼────┼────┼────┤           │  │                │ │
│  │              │  │  │    │    │    │    │           │  │  ▾ relighting  │ │
│  │              │  │  └────┴────┴────┴────┘           │  │    strength ═  │ │
│  │              │  │                                   │  │    ambient  ═  │ │
│  │              │  │  [☐ fix seed: 42]  [⟳ Regen]     │  │                │ │
│  │              │  │  [⇄ Compare mode]                │  │  ▸ overlays    │ │
│  └──────────────┘  └───────────────────────────────────┘  │                │ │
│                                                           │  [💾 Save…]    │ │
│  [← Retour /coins]                     [→ Envoyer au training]              │ │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Panneau gauche — Staged coins** (largeur ~240 px) :
- Liste verticale des coins reçus via `?eurio_ids=`, thumbnail 40 px + eurio_id tronqué + badge zone (V/O/R, style `zoneStyle()`).
- Le coin actif est highlighted (`indigo-700` accent vertical à gauche).
- Clic sur un coin → change coin actif, relance automatiquement un `Regenerate` avec la recipe courante.
- Badge de statut par coin : `•` non regénéré, `✓` recette assignée, `⚠` échec dernier run.

**Panneau central — Preview grid** (flex-grow) :
- Grille 4×4 de 16 PNG, aspect ratio 1:1, coin arrondi `--radius-md`, fond `--surface-1`.
- Loading : shimmer par case (pas un seul spinner global — on voit les cases remplir au fur et à mesure).
- Hover case → tooltip `index · seed utilisé`.
- Clic case → ouvre une lightbox en grand (zoom qualité).
- Barre de contrôles dessous : toggle `Fix seed` + input numérique seed (grisé si toggle off) + bouton `⟳ Regenerate` (active = indigo-700, disabled = grisé) + bouton `⇄ Compare mode`.

**Panneau droit — Recipe configurator** (largeur ~360 px) :
- Preset dropdown en haut : `green` / `orange` / `red` / `[recipes custom…]`. Sélectionner un preset écrase la recipe courante après confirmation si modifications non sauvegardées.
- Liste verticale de sections collapsibles, une par layer de la recipe (`perspective`, `relighting`, `overlays`, …).
- Chaque section affiche les params du layer, rendus selon le `type` déclaré dans `/augmentation/schema` :
  - `number` avec min/max → slider + input numérique.
  - `boolean` → toggle switch.
  - `string` avec `options[]` → select.
  - `list[string]` avec `options[]` → multi-checkbox (ex. `overlay_kinds` pour overlays).
- En bas : badge `config modifiée, regen pour voir` quand la recipe diverge du preset ET qu'on n'a pas encore regéréné avec la version courante.
- Bouton `💾 Save recipe…` activé dès que divergence ; inactif sinon.

**Barre basse (sticky, full-width)** :
- À gauche : lien retour `← Retour /coins`.
- À droite : bouton `→ Envoyer au training` actif seulement quand chaque coin stagé a une recipe assignée (même recipe pour tous OK, ou recipe différente par coin).

### 4.2 États de la page

| État | Déclencheur | Rendu |
|---|---|---|
| **Empty** | `?eurio_ids=` absent ou vide | Hero "Aucune pièce stagée" avec CTA `Aller à /coins et sélectionner des pièces` |
| **Loading initial** | Fetch schema ou premier preview en cours | Panneau gauche populé, grille centrale en shimmer 16 cases, panneau droit grisé |
| **Regen en cours** | POST `/augmentation/preview` en vol | Grille shimmer cases, bouton `Regenerate` en spinner, reste interactif |
| **Error** | Preview KO (400/500) | Banner rouge au-dessus de la grille avec message + bouton `Réessayer`, recipe conservée |
| **Offline ML API** | Healthcheck KO | Banner rouge full-width + panneaux grisés, lien `go-task ml:api` dans `ml/` avec bouton `Réessayer` (cf. `TrainingPage.vue`) |
| **Coin manquant** | Un `eurio_id` de l'URL ne résout pas | Toast warning, coin marqué `⚠ introuvable` dans la liste, on continue avec les autres |

### 4.3 Interactions clés

| Action | Comportement |
|---|---|
| Charger un preset | Écrase la recipe courante (confirmation si modifs non sauvegardées). Reset du flag "modifié". |
| Tweak un param | Marque la recipe courante `dirty`, affiche le badge `config modifiée`, active `Save recipe`. |
| Regenerate | POST `/augmentation/preview` avec la recipe courante + eurio_id du coin actif + seed (si fixé). Grille passe en shimmer, cases se remplissent au fur et à mesure que les images deviennent disponibles sur `GET /augmentation/preview/images/{run_id}/{index}`. |
| Fix seed toggle ON | Input seed visible (default = 42). Seed envoyé au backend → variantes déterministes ; tweak isolé visible pixel-par-pixel. |
| Fix seed toggle OFF | Backend tire un seed random par run → variance max, comportement équivalent à la vraie augmentation d'entraînement. |
| Save recipe | Ouvre une modale : champ `name` (validation : kebab-case non déjà pris), champ `tags[]` optionnel, bouton `Enregistrer`. POST `/augmentation/recipes`. Après success : preset dropdown se rafraîchit, nouvelle recipe devient active. |
| Compare mode ON | Split écran : deux grilles 4×4 côte à côte, deux configurateurs empilés ou en onglets. Recipe B = clone modifiable de A au moment du toggle. Same coin, same seed forcé. Regen déclenche les deux en parallèle. |
| Changer coin actif | Recipe courante conservée, regen automatique sur le nouveau coin. |
| Envoyer au training | POST `/training/stage` (endpoint existant) avec `{items: [{class_id, class_kind}…]}` + champ `aug_recipe_id` par item (le champ doit être accepté par `/training/stage` — cf. §8 questions ouvertes). Navigation vers `/training`. |

### 4.4 Design tokens utilisés

- Brand primary : `var(--indigo-700)` (boutons actifs, highlight coin actif, badge dirty).
- Accent éditorial : hairline `var(--gold)` sous le header (cohérence `ConfusionMapPage`).
- Zones : `var(--success)` / `var(--warning)` / `var(--danger)` sur les badges zone, via `zoneStyle()` déjà exporté.
- Grille preview : fond case `var(--surface-1)`, border `var(--surface-3)`, radius `--radius-md`.
- Shimmer loading : même pattern que `animate-pulse` sur `bg-[var(--surface-1)]` (cf. cartes stats `ConfusionMapPage`).
- Typographie : titre `font-display italic` indigo-700 ; labels uppercase eyebrow `tracking-eyebrow` ink-400 (cohérence existante).
- Shadow cartes : `var(--shadow-sm)` / `var(--shadow-card)`.

---

## 5. Spec technique

### 5.1 Route & paramètres URL

- Route : `/augmentation`.
- Query params :
  - `eurio_ids=a,b,c` (required — sinon état empty).
  - `recipe=<id>` (optionnel — pré-charge une recette sauvegardée par id).
  - `compare=<id>` (optionnel — ouvre directement en compare mode avec cette recipe en slot B).
- L'URL est la source de vérité du staging. Pas de store Pinia pour ça. Navigation `/coins` → `/augmentation` pousse les ids en query.

### 5.2 Arborescence feature module

```
admin/packages/web/src/features/augmentation/
├── pages/
│   └── AugmentationStudioPage.vue          # composant racine de la route
├── components/
│   ├── StagedCoinsList.vue                 # panneau gauche
│   ├── PreviewGrid.vue                     # panneau central (grille 16 cases)
│   ├── RecipeConfigurator.vue              # panneau droit
│   ├── LayerSection.vue                    # une section collapsible par layer
│   ├── ParamControl.vue                    # dispatch number/boolean/select/multi
│   ├── SaveRecipeModal.vue                 # modal "nommer + tagger"
│   └── CompareToggle.vue                   # togg compare + gestion split
├── composables/
│   ├── useAugmentationApi.ts               # wrappers fetch vers ML API
│   ├── useAugmentationSchema.ts            # fetch + cache du /schema
│   ├── useRecipeState.ts                   # recipe courante + dirty flag + preset baseline
│   └── useStagedCoins.ts                   # résolution des eurio_ids query → Coin[]
└── types.ts                                # Recipe, LayerSchema, ParamSchema, etc.
```

### 5.3 Endpoints ML API consommés

Tous définis dans le Bloc 1. Aucun nouvel endpoint créé ici — si besoin, remonter en §8 questions ouvertes.

| Méthode | Endpoint | Usage |
|---|---|---|
| GET | `/health` | Healthcheck ML API pour dégradation offline |
| GET | `/augmentation/schema` | Au mount : récupère layers disponibles + params + bounds pour générer le configurateur |
| GET | `/augmentation/overlays` | À la demande (section overlays) : liste les textures disponibles en read-only |
| POST | `/augmentation/preview` | À chaque `Regenerate` : body `{recipe, eurio_id, count, seed?}` → renvoie `{run_id, indices: [0..N-1]}` |
| GET | `/augmentation/preview/images/{run_id}/{index}` | `<img :src>` dans la grille |
| GET | `/augmentation/recipes` | Au mount : peuple le preset dropdown avec les recipes custom |
| POST | `/augmentation/recipes` | Save recipe modal |
| PUT | `/augmentation/recipes/{id}` | v1.5 si édition d'une recipe existante (out v1) |
| DELETE | `/augmentation/recipes/{id}` | v1.5 (out v1) |
| POST | `/training/stage` | Handoff training (endpoint existant, cf. `CoinsPage.vue`) |

### 5.4 Gestion du state

Pas de Pinia. Composables Vue suffisent :

- **`useStagedCoins`** — lit `route.query.eurio_ids`, résout via Supabase en `Coin[]`, expose `activeIndex` + `setActive()`. Réactif aux changements d'URL.
- **`useAugmentationSchema`** — fetch `/augmentation/schema` au mount, cache en mémoire (module-level ref). Le schéma ne change pas pendant la session.
- **`useRecipeState`** — tient `current: Recipe`, `baseline: Recipe` (preset ou recipe chargée), `dirty: computed(JSON.stringify(current) !== JSON.stringify(baseline))`. Expose `loadPreset()`, `updateParam()`, `resetToBaseline()`.
- **`useAugmentationApi`** — wrappers typés autour de fetch. Gère erreurs + retry explicite.

Le state Compare utilise deux instances de `useRecipeState` (slot A et B). Quand `compare=false` devient `compare=true`, slot B = clone profond de A.

### 5.5 Modifications de `CoinsPage.vue`

**Additif uniquement**, pas de refacto du comportement existant.

Dans le footer sticky (bloc `<Transition name="slide-up">` quand `selectedCount > 0`), ajouter un **3ᵉ bouton** entre `Ajouter et voir →` et `Ajouter au training` :

- Label : `Augmenter`
- Icône : `Sparkles` (lucide) ou équivalent
- Comportement : ne stage **pas** côté training, navigue vers `/augmentation?eurio_ids=<class_ids joined by ','>`
- Style : secondaire (fond `var(--surface-1)`, text ink, pas indigo) pour ne pas rivaliser visuellement avec le CTA training
- Visible seulement si ML API online (même condition que les autres actions, sinon pas de backend pour générer)

Le set de coins envoyés = `Array.from(selectedClasses.value)` (les `class_id`, qui sont `design_group_id` ou `eurio_id` selon le coin — cf. `coinClassId()`). Le Studio fait donc le travail de résoudre `class_id → image source` côté backend, comme le ferait le training.

### 5.6 Dégradation ML API offline

- Healthcheck initial au mount + poll 30 s (pattern `ConfusionMapPage`).
- Si offline :
  - Panneaux grisés avec overlay 50 % opacité.
  - Banner central : `ML API non jointe. Lance go-task ml:api dans ml/ pour activer le Studio.`
  - Bouton `Réessayer` qui force un healthcheck.
  - Les recipes sauvegardées **ne sont pas consultables** en offline (elles vivent en SQLite local côté `ml/`, pas en Supabase). Le preset dropdown affiche seulement `[green, orange, red]` (hardcodés localement comme fallback, valeurs approximatives — le schéma réel vient de `/schema`, donc même les presets sont inutilisables pour regen). On assume : offline = consultation impossible, c'est OK.

### 5.7 Gestion seed & reproductibilité

- Toggle `Fix seed` + input number. Default ON = 42, l'utilisateur peut incrémenter manuellement pour voir N variantes du "même run" sans perdre le déterminisme global.
- Seed envoyé dans le POST preview si toggle ON ; omis sinon.
- En Compare mode, seed forcé identique sur les deux slots (c'est le point du A/B : neutraliser l'aléa).

---

## 6. Spec visuelle

### 6.1 Palette zones (rappel)

| Zone | Solid | Soft | Usage |
|---|---|---|---|
| Green | `var(--success)` #2FA971 | `var(--success-soft)` | Badge coin staged zone verte |
| Orange | `var(--warning)` #D88A2D | `var(--warning-soft)` | Badge coin staged zone orange |
| Red | `var(--danger)` #D14343 | `var(--danger-soft)` | Badge coin staged zone rouge |

Résolution via `zoneStyle()` de `@/features/confusion/composables/useConfusionZone` (déjà exporté).

### 6.2 Preview grid

- Grille CSS 4 colonnes × 4 rangées, gap `var(--space-2)`.
- Case : aspect-square, `background: var(--surface-1)`, `border-radius: var(--radius-md)`, `overflow: hidden`.
- Image : `object-fit: contain`, padding `var(--space-1)`.
- Hover : translate Y -2 px, ombre `var(--shadow-md)`, transition `var(--duration-base) var(--ease-out)`.
- Shimmer (loading case par case) : même `animate-pulse` que `ConfusionMapPage` stats loading, background `var(--surface-1)`.
- Cliquable → ouvre lightbox plein écran (image zoomée, fond `rgba(0,0,0,0.8)`, close sur clic ou Escape).

### 6.3 Recipe configurator

- Section par layer :
  - Header cliquable (chevron + nom du layer en `font-display` taille `var(--text-base)` + badge probabilité en mono).
  - Corps collapsible (animation height `var(--duration-fast)`).
- Contrôles :
  - Slider (`<input type="range">`) + input numérique à droite (synchronisés), steps déduits de `schema.step` ou 0.01 par défaut.
  - Toggle switch custom pour booléens (cohérence `/training` qui n'en a pas mais à créer — petit composant 40×24 px avec bille).
  - Select natif pour `string` + options.
  - Liste de checkboxes pour `list[string]` + options.
- Un label `— modifié` apparaît à côté du param quand valeur ≠ baseline preset.
- Tooltip hover sur le label du param → affiche la `description` fournie par le schéma.

### 6.4 Compare mode

- Split 50/50 vertical.
- Header de chaque colonne : nom recipe + bouton "recharger preset" + petit diff badge (N params modifiés par rapport à l'autre slot).
- Configurateurs empilés dessous en accordion (ou onglets si trop long).
- Seed en commun affiché au-dessus des deux grilles en font-mono.

---

## 7. Métriques de succès

Observées localement (pas de collecte automatique — le dev est l'utilisateur et mesure à la main ou dans un carnet) :

| Métrique | Cible |
|---|---|
| Temps par tweak (`slider → Regenerate → grille visible`) | ≤ 5 s en moyenne (2-3 s génération + 1 s render) |
| Temps du workflow "staging 5 coins → recette validée sur chacun → handoff training" | ≤ 10 min pour un dev déjà familier |
| Nb de recettes custom sauvegardées durant l'exploration Phase 2 | ≥ 6 (2 par zone × 3 zones, attendues empiriquement) |
| Nb d'aller-retours vers `recipes.py` après passage au Studio | = 0 (tout passe par la DB SQLite) |
| Utilisation du mode Compare | ≥ 1 fois par session d'exploration d'une zone |

Qualitatif : la sensation de "je peux pousser un slider et voir immédiatement", qui n'existe pas avec la CLI.

---

## 8. Dépendances

### Bloc 1 requis pour démarrer

Le Studio ne peut pas sortir de son wireframe tant que les endpoints suivants ne répondent pas avec le contrat figé du PRD Bloc 1 :

- `GET /augmentation/schema` — bloquant total (génère le configurateur).
- `POST /augmentation/preview` + `GET /augmentation/preview/images/{run_id}/{index}` — bloquant total (pas de grille sans).
- `GET/POST /augmentation/recipes` — bloquant pour Save ; sans, la page peut démarrer en mode lecture seule (presets hardcodés du schéma) mais perd 50 % de sa valeur.

### Workspace / routing

- Ajout d'une entrée route dans `admin/packages/web/src/app/router.ts` : `/augmentation` → lazy `AugmentationStudioPage`.
- Ajout d'une entrée dans `nav.ts` ? **À trancher** — par défaut non (c'est un cul-de-sac partant de `/coins`, pas une destination autonome dans la nav principale). Voir §9.

### Librairies

Aucune nouvelle dépendance npm requise. Stack disponible :
- `lucide-vue-next` (icônes — `Sparkles`, `RefreshCw`, `Copy`, `Split`, `Save`).
- `@vueuse/core` (debounce, `useEventListener` pour Escape lightbox).
- `supabase-js` déjà configuré pour résoudre les `Coin` depuis les `eurio_ids`.

---

## 9. Questions ouvertes

| # | Question | Blocage | Proposition par défaut |
|---|---|---|---|
| Q1 | `/training/stage` accepte-t-il un champ `aug_recipe_id` par item ? | Bloque le handoff training | Remonter au Bloc 1 : étendre le body de `/training/stage` avec `aug_recipe_id?: string \| null` par item, ignoré pour l'instant côté orchestrateur training si non supporté |
| Q2 | Une entrée `/augmentation` dans la nav principale ? | Non bloquant | Non en v1 — on entre exclusivement par `/coins` → `Augmenter`. Reconsidérer si d'autres entry points apparaissent |
| Q3 | Support d'un coin sans image source (ex. design_group_id dont aucun membre n'a encore été enrichi) | Cas rare mais réel | Backend Bloc 1 renvoie 404 sur `/preview` avec un code clair ; le Studio affiche "pas d'image source, pièce exclue" dans la liste staged et la skip |
| Q4 | Compare mode : recipe B doit-elle aussi être sauvegardable indépendamment de A ? | UX subtle | Oui — même bouton Save par slot, indépendants |
| Q5 | Lightbox plein écran ou drawer latéral pour zoom case ? | UX | Lightbox plein écran (cf. `ConfusionMapPage` ne zoome pas ; c'est une nouvelle pattern à introduire) |
| Q6 | Persistance de la dernière recipe utilisée entre sessions ? | UX | Non en v1. L'URL porte l'état (`?recipe=<id>`), le dev peut bookmarker. Éviter localStorage pour garder l'URL comme seule source. |
| Q7 | Que se passe-t-il si le dev sélectionne 40 coins et clique `Augmenter` ? | Scaling UX | Cap à 20 coins côté bouton (disable + tooltip "maximum 20"). 40 coins × 16 variantes = 640 générations, le cockpit devient inutilisable. Au-delà → passer directement au training. |
| Q8 | Envoi au training : les recipes utilisées sont-elles persistées côté run training (traçabilité) ? | Traçabilité ML | Oui, idéalement le `training_run` enregistre `aug_recipe_id` par class. Dépend de Q1 + migration `training_runs` côté Bloc 1 ou Bloc 3. |

---

## 10. Voir aussi

- [`docs/augmentation-benchmark/01-backend-pipeline.md`](./01-backend-pipeline.md) — PRD Bloc 1, contrat HTTP + introspection.
- [`docs/research/ml-scalability-phases/phase-2-augmentation.md`](../research/ml-scalability-phases/phase-2-augmentation.md) — spec d'origine Phase 2.
- [`ml/augmentations/`](../../ml/augmentations/) — code du moteur (consommé par ce Studio via HTTP uniquement, jamais importé côté Vue évidemment).
- [`admin/packages/web/src/features/coins/pages/CoinsPage.vue`](../../admin/packages/web/src/features/coins/pages/CoinsPage.vue) — point d'entrée (bouton `Augmenter` à ajouter).
- [`admin/packages/web/src/features/confusion/pages/ConfusionMapPage.vue`](../../admin/packages/web/src/features/confusion/pages/ConfusionMapPage.vue) — référence design (header, hairline gold, cartes stats, shimmer loading).
- [`admin/packages/web/src/features/training/pages/TrainingPage.vue`](../../admin/packages/web/src/features/training/pages/TrainingPage.vue) — référence pattern ML API interaction (healthcheck, dégradation offline, drawer).
- [`shared/tokens.css`](../../shared/tokens.css) — tokens référencés.
- [`docs/design/_shared/parity-rules.md`](../design/_shared/parity-rules.md) — R1 proto-first **non applicable** ici : `/augmentation` est un outil admin (workspace `admin/`), pas une scène de l'app Android. La règle proto s'applique à l'UX user ; ce cockpit sert exclusivement le dev.
