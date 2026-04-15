# CLAUDE.md — Eurio repo-level guidance

> Instructions durables pour Claude Code dans ce dépôt. Lis ce fichier avant de toucher le code ou les docs.

## Mission produit

Eurio est une app Android de collection de pièces euro. L'acte central de l'app est le **scan** : l'utilisateur ouvre l'app, pointe sa caméra sur une pièce, et l'app l'identifie + lui propose de l'ajouter à son coffre. Tout le reste de l'UX tourne autour de cet acte — comme TikTok tourne autour de la création de contenu.

Voir `docs/app-implem-phases/README.md` pour le plan détaillé en 6 phases (0 à 5), et `docs/app-implem-phases/phase-*.md` pour chaque phase individuellement.

## Monorepo

```
Eurio/
├── app-android/                  # App Kotlin/Compose (Material 3)
├── admin/                        # Console web Vue/Vite pour gérer coins + sets
├── ml/                           # Scripts Python : entraînement, sync Supabase, export snapshot
├── supabase/                     # Migrations SQL + types générés
├── shared/                       # Sources partagées (tokens.css canonique)
├── scripts/                      # Générateurs et utilitaires cross-module (Node)
├── docs/
│   ├── app-implem-phases/        # Plan des 6 phases d'implémentation Android
│   ├── design/                   # Design docs
│   │   ├── _shared/              # parity-rules, components-parity, scene-parity, data-contracts, etc.
│   │   └── prototype/            # Prototype HTML/CSS/JS (source de vérité du design)
│   └── research/                 # Recherche et décisions techniques
└── Taskfile.yml                  # Point d'entrée des commandes (go-task)
```

## Règles non-négociables

### R0. Pas de dette technique
Jamais de shortcut qui crée de la dette. Construire proprement depuis le POC. Si une solution propre n'est pas claire, on discute avant d'implémenter, pas après.

### R1. Proto-first design (STRICT)

**Tout nouveau design doit d'abord exister dans le prototype HTML** (`docs/design/prototype/`) avant d'être implémenté en Compose Android.

- Cela inclut : nouvelles scènes, nouveaux composants visuels, nouveaux layouts, nouveaux états (empty/loading/error).
- Cela n'inclut pas : adaptations techniques Android (back gesture, permission dialog), ni les deltas systémiques documentés dans `docs/design/_shared/parity-rules.md` §R6.
- Si Claude se retrouve à inventer un rendu visuel côté Android sans équivalent proto, il **doit s'arrêter et demander** à ajouter d'abord la scène proto.

Spec complète : `docs/design/_shared/parity-rules.md`.

### R2. Tokens auto-générés, jamais édités à la main

`shared/tokens.css` est la source canonique des couleurs, espacements, rayons, durées.

Les fichiers Kotlin suivants sont **auto-générés** et commencent par un header `AUTO-GENERATED — DO NOT EDIT` :

- `app-android/src/main/java/com/musubi/eurio/ui/theme/Color.kt`
- `app-android/src/main/java/com/musubi/eurio/ui/theme/Shape.kt`
- `app-android/src/main/java/com/musubi/eurio/ui/theme/Spacing.kt`

Pour modifier un token :
1. Éditer `shared/tokens.css`
2. Lancer `go-task tokens:generate`
3. Committer les deux fichiers dans le même commit

**Jamais d'édition manuelle de Color.kt / Shape.kt / Spacing.kt.** Les fichiers Type.kt et Theme.kt restent hand-written (dépendent de ressources Android et de slots M3 sémantiques).

### R3. Parité proto ↔ Android trackée en tables

Avant de créer un écran ou un composant, vérifier :

- `docs/design/_shared/scene-parity.md` — table des scènes proto ↔ destinations Android
- `docs/design/_shared/components-parity.md` — table des classes CSS ↔ composables

Une entrée `❌ à proto'er` **bloque** le démarrage du code Android correspondant. Une entrée sans delta documenté est considérée comme du drift à corriger.

## Conventions de travail

### Commandes

Toutes les commandes de build, install, sync passent par **`go-task`** (jamais `task` ni invocation directe).

Commandes fréquentes :

```bash
go-task android:build            # Assemble debug APK
go-task android:install          # Build + push APK sur device
go-task android:run              # install + start
go-task android:logs             # tail logcat filtré Eurio
go-task android:snapshot         # Regen catalog_snapshot.json depuis Supabase
go-task android:snapshot-dry     # Preview snapshot sans écrire
go-task tokens:generate          # Regen Color/Shape/Spacing depuis tokens.css
go-task tokens:check             # Vérifier que la génération est à jour (CI)
```

### Supabase

- Accès via clé API (Postgrest) pour l'admin et l'export snapshot
- L'app Android est **offline-first** avec un snapshot catalogue packagé dans l'APK (`app-android/src/main/assets/catalog_snapshot.json`)
- Pas d'auth utilisateur pour v1 (le vault est 100% local côté Room)
- Schéma de vérité : `supabase/types/database.ts` (généré)

### Stack technique Android

- Kotlin + Jetpack Compose + Material 3
- Navigation Compose (2.8.x)
- Room 2.6.1 (KSP, pas Kapt)
- Supabase-kt (postgrest-kt)
- Coil (chargement images)
- CameraX + LiteRT (ML on-device)
- OpenCV 4.10 (Hough circle detection)
- Koin (DI, pas encore câblé, à activer si besoin)
- minSdk 26, target 36

### ML pipeline

Voir `docs/research/detection-pipeline-unified.md`. Pipeline actuelle : YOLO11-nano + OpenCV Hough en parallèle → merge IoU → rerank ArcFace spread-based → consensus buffer 5/3 sticky.

## Documents à lire avant d'attaquer un changement

| Tu touches à… | Lis d'abord… |
|---|---|
| Nav shell / FAB / bottom bar | `docs/app-implem-phases/research-02-nav-patterns.md` |
| UX décisions produit | `docs/app-implem-phases/README.md` (14 décisions) |
| Pipeline ML scan | `docs/research/detection-pipeline-unified.md` |
| Sets (DSL, criteria, types) | `docs/design/_shared/sets-architecture.md` |
| Schéma local Room | `docs/design/_shared/data-contracts.md` |
| Stratégie offline/sync | `docs/design/_shared/offline-first.md` |
| Parité proto ↔ Android | `docs/design/_shared/parity-rules.md` |
| Phase spécifique | `docs/app-implem-phases/phase-N-*.md` |

## Interdictions

- ❌ Éditer `Color.kt`, `Shape.kt`, `Spacing.kt` à la main
- ❌ Coder un écran Android sans scène proto correspondante
- ❌ Hardcoder des couleurs dans du Compose (toujours passer par `MaterialTheme.colorScheme.*` ou les vals générées)
- ❌ Créer des `TODO:` dans le code (la dette est explicite via docs ou tasks, pas enfouie dans le code)
- ❌ Utiliser `git add -A` ou `git add .` (staging explicite par fichier pour éviter les fuites de secrets)
- ❌ Éditer `.envrc` ou `.env` (secrets, protégés par shhh)
- ❌ Utiliser `task` au lieu de `go-task` dans les commandes ou les docs
