# Prompt de contexte — Session Parité : workflow et framework

## Objectif de la session

Concevoir le **workflow de maintien de parité** entre le prototype HTML (source de vérité design) et les apps mobiles (Android aujourd'hui, iOS futur). On ne travaille pas sur l'UI du parity viewer admin — on travaille sur le **framework** qui garantit que les designs se suivent.

## Ce qui existe déjà

### Infrastructure construite (session précédente)

1. **Prototype HTML** (`docs/design/prototype/`) — SPA standalone, 16+ scènes, hash router, state presets
2. **Shared fixtures** (`shared/fixtures/`) — JSON déterministes (preset-populated, preset-empty, preset-profile-demo) partagés entre proto, Android, et Maestro
3. **Admin pnpm workspace** (`admin/`) — packages/web (Vue, Vercel) + packages/parity (Playwright, Maestro flows)
4. **QA build Android** — build type séparé (`com.musubi.eurio.qa`) avec :
   - State injection via deep links (`scan_state=matched`, `scan_state=detecting`, etc.)
   - ScanStateRelay pour forcer les états du scan ViewModel
   - Mock camera pour remplacer le feed CameraX
   - Vault seed via fixtures JSON
5. **Maestro flows** (16 YAML) — chacun avec PARITY_ID, PARITY_STATE, PARITY_PROTO_ROUTE
6. **Playwright script** (`packages/parity/capture/proto.ts`) — capture screenshots du proto (en cours de debug)
7. **Parity viewer** (`/parity` dans admin) — page Vue qui affiche 2 images côte à côte (proto vs Android)

### Documents de référence existants

- `docs/design/_shared/parity-rules.md` — règles de parité proto ↔ Android (R1-R6)
- `docs/design/_shared/scene-parity.md` — table des scènes proto ↔ destinations Android
- `docs/design/_shared/components-parity.md` — table des classes CSS ↔ composables
- `CLAUDE.md` — règle R1 proto-first, R3 tables de parité

### Tokens auto-générés

`shared/tokens.css` → `scripts/generate_android_tokens.mjs` → `Color.kt`, `Shape.kt`, `Spacing.kt`
Les tokens sont synchronisés automatiquement. Ce n'est PAS un problème de parité.

## Ce qui ne fonctionne pas encore

### Captures proto (Playwright)
- Le CSS du proto dépend de `shared/tokens.css` via un `@import` relatif qui remonte hors de l'arbre `/proto/`. Fix en cours (middleware Vite pour `/shared/`).
- Le `.screen` element a un boundingBox de width=0 en headless — le clip screenshot échoue.
- Les fonts Google (Fraunces, Inter Tight) se chargent via `@import url(...)` — latence en headless.

### Captures Android (Maestro)
- **Disambiguation dialog** : quand l'app debug ET l'app QA sont installées, Android demande de choisir. Solution : désinstaller debug avant capture, ou ajouter `android:autoVerify="true"` aux intent filters QA.
- **Vues manquantes** : l'app n'a pas encore toutes les vues que le proto a (NotIdentified n'a pas de UI dédiée, certaines scènes vault sont des stubs). Les scènes proto en avance sur l'app ne peuvent pas avoir de screenshot Android.
- **State injection partielle** : le scan state injection fonctionne (Idle, Detecting, Accepted, Failure) mais NotIdentified rend ScanIdleLayer() car la UI dédiée n'existe pas encore.

### Nesting screenshots Maestro
- `--test-output-dir` crée des sous-dossiers timestampés, les PNGs ne sont pas au bon endroit pour le viewer.

## Ce sur quoi je veux réfléchir

### 1. Workflow de parité au quotidien

Quand je design une nouvelle scène ou modifie une existante :
- Quel est le processus step-by-step ?
- Comment je sais qu'une scène proto est "prête" à être implémentée en Android ?
- Comment je détecte le drift (proto avance, Android ne suit pas) ?
- Comment je gère les scènes qui existent dans le proto mais pas encore dans l'app ?

### 2. Niveaux de parité

Tous les deltas ne sont pas des bugs. Il y a :
- **Deltas systémiques** (documentés dans parity-rules.md §R6) : status bar native, gesture nav, etc.
- **Deltas intentionnels** : adaptations Android légitimes (back gesture, haptics, etc.)
- **Drift** : l'app a divergé du proto sans justification — c'est ça qu'il faut détecter

Comment formaliser ces 3 catégories dans le workflow ?

### 3. Proto comme source de vérité vivante

Le proto n'est pas un Figma statique — c'est du code vivant avec state management. Comment s'assurer que :
- Les scènes proto couvrent tous les états (empty, populated, error, loading)
- Les données de demo sont représentatives et partagées (fixtures JSON)
- Le proto est testable de manière automatisée (Playwright)

### 4. Scalabilité iOS

Quand l'app iOS arrive, le même framework doit fonctionner :
- Proto (source) → Android screenshots + iOS screenshots
- Les fixtures sont déjà en JSON (cross-platform)
- Les flows Maestro sont Android-only — quel équivalent pour iOS ? (Maestro supporte iOS)
- Comment structurer les screenshots (proto/ android/ ios/) — déjà fait

### 5. CI/CD intégration future

À terme :
- PR qui touche le proto → auto-capture proto screenshots
- PR qui touche l'app → auto-capture Android screenshots
- Comparaison visuelle automatique (pixel diff ? perceptual diff ?)
- Mais PAS maintenant — c'est du futur. Je veux juste un workflow local qui marche.

## Ma vision

Le parity viewer n'est pas juste un outil de comparaison visuelle. C'est le **système nerveux** du design system Eurio. Le proto est le cerveau (source de vérité), les apps sont les membres (implémentations), et le parity viewer est la boucle de feedback qui dit "est-ce que les membres font ce que le cerveau demande ?".

Je veux un workflow où :
1. Je design dans le proto → c'est rapide, c'est du HTML/CSS
2. Je capture le proto → screenshots déterministes
3. J'implémente dans Android → guidé par les screenshots proto
4. Je capture Android → screenshots déterministes
5. Je compare → le parity viewer me montre les deltas
6. Je documente les deltas intentionnels, je corrige le drift

Et ce workflow doit être **léger**. Pas un pipeline CI de 30 minutes. Un `go-task` qui prend 2 minutes et me donne un dashboard visuel.
