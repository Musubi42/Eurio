# Parité design — proto HTML ↔ app Android

> Règles de conformité visuelle et structurelle entre le prototype HTML (`docs/design/prototype/`) et l'app Android Compose (`app-android/`). Session du 2026-04-16.
>
> **Règle d'or** : le proto est la source de vérité du design. L'app Android porte le proto. Tout nouveau design doit d'abord exister dans le proto.

## Les 6 règles

### R1. Tokens = single source of truth, auto-generated

- `shared/tokens.css` est **canonique**. Aucune autre source de vérité pour les tokens de couleur, espacement, rayon, durée.
- Les fichiers Kotlin `ui/theme/Color.kt`, `Shape.kt`, `Spacing.kt` sont **auto-générés** depuis `tokens.css` par `scripts/generate_android_tokens.mjs`.
- **Ne jamais éditer ces fichiers à la main.** Chaque fichier généré commence par un header `AUTO-GENERATED — DO NOT EDIT`.
- Pour modifier un token :
  1. Éditer `shared/tokens.css`
  2. Lancer `go-task tokens:generate`
  3. Vérifier le diff Kotlin, committer les deux fichiers dans le même commit
- Les fichiers `ui/theme/Type.kt` et `ui/theme/Theme.kt` **restent hand-written** (la typographie dépend des `res/font/` Android et le `ColorScheme` M3 assigne les slots sémantiques, pas simplement copier les couleurs).

### R2. Proto-first design

**Règle stricte** : tout nouvel écran, composant, pattern visuel doit **d'abord exister dans le proto HTML** avant d'être implémenté en Compose.

- Cela inclut : nouvelles scènes, nouvelles cards, nouveaux layouts, nouveaux états (loading/error/empty), nouvelles animations significatives.
- Cela n'inclut PAS : adaptations techniques (back gesture, permission dialog système, snackbar M3 éphémère), ni les deltas R6 déjà documentés.
- **Conséquence** : on ne commence pas le dev Compose d'une phase tant que les scènes proto de cette phase ne sont pas livrées et validées.
- **Enforcement** : rappelé dans `CLAUDE.md` racine + mémoire `feedback_proto_first.md`.

Workflow standard :
```
1. Itérer un design dans le proto HTML (rapide)
2. Valider visuellement avec le user
3. Ajouter une entrée dans scene-parity.md (status: ⏳ prête)
4. Coder la version Compose en visant la parité pixel
5. Screenshot side-by-side avant merge
6. Status → 🟢 parité validée
```

### R3. Table de parité composants

Maintenue dans `components-parity.md`. Toute classe CSS du proto utilisée 2+ fois et tout Composable réutilisable doit y figurer avec :

- Nom CSS (ex : `.btn-primary`)
- Nom Compose (ex : `EurioPrimaryButton`)
- Delta Android assumé (ripple, élévation, insets, etc.)
- Status (⏳ todo / 🟡 en cours / 🟢 aligné / ⚠️ divergent)

**Règle** : ajouter une ligne dès qu'un composant est créé, pas après coup. Les deltas non documentés sont considérés comme du drift à corriger.

### R4. Table de parité scènes

Maintenue dans `scene-parity.md`. Une ligne par scène proto (`scenes/*.html`) ↔ composable Android (`features/*/Screen.kt` ou un état).

Colonnes :
- Proto scene path
- Android destination (route ou composable path)
- Phase d'implémentation (0-5)
- Status (❌ à proto'er / ⏳ en attente de dev / 🟡 en cours / 🟢 livré)
- Notes / deltas

**Règle** : une entrée `❌ à proto'er` bloque le démarrage de sa phase. Tant que le proto manque, on ne code pas l'écran.

### R5. Visual QA avant commit UI

Avant de commit un changement qui touche au rendu visuel d'un écran :

1. Screenshot de la scène proto concernée (Chrome desktop, device frame 390×844)
2. Screenshot Android correspondant (émulateur ou device physique)
3. Comparaison side-by-side (joindre les deux images au commit ou à la PR description)
4. Si différence non documentée → corriger ou documenter en R3/R4/R6
5. Si différence justifiée → la citer dans le message de commit

### R6. Deltas Android assumés (inhérents à la plateforme)

Liste fermée de différences proto↔Android qu'on ne cherche pas à éliminer :

| # | Domaine | Proto | Android | Raison |
|---|---|---|---|---|
| D1 | System bars | Fake device frame avec notch dessiné | `enableEdgeToEdge()` + insets système + `navigationBarsPadding()` | Android a vraie status bar + nav bar OS |
| D2 | Feedback tactile | `:active { transform: scale(0.97) }` | Ripple M3 + haptic feedback natif | Conventions plateforme |
| D3 | Scroll physics | `-webkit-overflow-scrolling: touch` + CSS snap | LazyColumn/LazyGrid avec physique Compose native | Conventions plateforme |
| D4 | Back navigation | Bouton back custom en top bar | `BackHandler` Compose + gesture back système | Conventions plateforme |
| D5 | Fonts | Webfonts servies par Vite dev server | `.ttf/.otf` dans `res/font/` + `FontFamily` | Offline-first, pas de réseau au démarrage |
| D6 | Nav bar notch | Fake notch via `margin-top: -22px` sur le bouton scan | Vrai `Shape` path-based dessiné dans `NotchedBarShape.kt` | Rendu plus propre côté Android |
| D7 | Bottom sheet | CSS `transform: translateY` | `ModalBottomSheet` M3 | Composant natif plus robuste |
| D8 | Toast | Div position-fixed CSS | `Snackbar` via `SnackbarHost` | Composant natif |

**Règle** : ajouter une ligne ici dès qu'un delta systémique est identifié. Les deltas D1-D8 ne sont pas à corriger.

## Générateur de tokens — contrat

Le script `scripts/generate_android_tokens.mjs` :

- Lit `shared/tokens.css`
- Parse les propriétés CSS custom du bloc `:root { }`
- Catégorise par préfixe (`indigo-*`, `gold*`, `ink*`, `surface*`, `gray-*`, semantic, `space-*`, `radius-*`)
- Applique le mapping de noms :
  - kebab-case → PascalCase (ex : `--indigo-700` → `Indigo700`)
  - **override** `surface` → `PaperSurface` (évite le shadow avec le composable `androidx.compose.material3.Surface`)
- Émet trois fichiers Kotlin :
  - `app-android/src/main/java/com/musubi/eurio/ui/theme/Color.kt`
  - `app-android/src/main/java/com/musubi/eurio/ui/theme/Shape.kt`
  - `app-android/src/main/java/com/musubi/eurio/ui/theme/Spacing.kt`
- Ignore les valeurs non-hex (rgba, var refs, cubic-bezier, tailles non-px)
- Exit 0 si succès, 1 si erreur de parse

**Invariant** : `generate_android_tokens.mjs` doit être idempotent. Deux runs consécutifs produisent des fichiers identiques.

## Docs liés

- [components-parity.md](components-parity.md) — table de parité composants
- [scene-parity.md](scene-parity.md) — table de parité scènes (inventaire actuel)
- [../prototype/_shared/DECISIONS.md](../prototype/_shared/DECISIONS.md) — décisions design antérieures
- [../../app-implem-phases/README.md](../../app-implem-phases/README.md) — plan d'implémentation phases 0-5
