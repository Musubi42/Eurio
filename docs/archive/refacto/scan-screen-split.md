# Refacto B — Extraction des modes dev hors de ScanScreen

> **Statut** : ✅ TERMINÉ — 6 chunks sur 6 livrés (2026-05-28).
> **Branche** : `coin-richness/p3-schema` (le refacto n'a pas fait l'objet d'une branche dédiée parce qu'il était imbriqué dans la session de debug capture).
> **Plan complet** : `/Users/musubi42/.claude/plans/dreamy-finding-treasure.md` (référence — peut ne pas être lisible hors session originelle).
>
> **Résultat** : ScanScreen 549 → 247 lignes, ScanViewModel ~1690 → 1226 lignes.
> 4 modes debug split sur `/dev/{capture,bench,photo,carousel}`, chacun avec son VM.
> Build + `testFullDebugUnitTest` verts. Bonus : `partial_shadow` → `glare_specular`
> dans le protocole ablation/bench, fix fond noir au flip carrousel (`isOpaque=false`),
> FAB + bottom bar cachés sur routes `dev/`.

---

## Pourquoi ce refacto

`ScanScreen` était devenu un sapin de Noël de booléens : `carouselMode`, `photoMode`, `captureMode`, `recordMode`, `debugMode`, `state`, `photoSnap`, `benchProtocol` cohabitaient dans le même `Box`. Conséquence visible : en capture mode, `ScanIdleLayer` (corner brackets + pill "En attente — centre la pièce dans le cadre") se rendait par-dessus `PhotoGuideOverlay` + `CaptureGuideOverlay`, le FAB scan central + le toggle "3D coin carrousel" polluaient l'écran capture. Cf. screenshot du 2026-05-28 partagé dans la session de chat.

**Objectif** : sortir Capture cohorte, Bench protocol, Carousel et Photo standalone sur des routes dédiées `/dev/<mode>`. `ScanScreen` redevient minimaliste (Idle / Detecting / Accepted / Failure + HUD debug). Le `DebugBar` (bottom-sheet DBG) devient le hub d'entrée vers les outils dev.

## Architecture cible

```
/scan                     ScanScreen propre — prod-ready
                          - état: Idle/Detecting/Accepted/Failure + HUD si BuildConfig.DEBUG
                          - DBG launcher → DebugBar bottom-sheet
                          - bottom-sheet : sliders + entrées nav vers /dev/...

/dev/photo                PhotoScreen — debug snap standalone (ArcFace inspect)  ← À FAIRE Chunk 5
/dev/capture              CaptureScreen — cohort capture (CaptureProtocol)       ← LIVRÉ Chunk 3
/dev/bench                BenchProtocolScreen — protocole bench guidé            ← À FAIRE Chunk 4
/dev/carousel             CarouselScreen — 3D viewer + tuning panel              ← À FAIRE Chunk 5
```

Chaque route /dev/* :
- mount sa propre `CameraPreview` + son propre VM
- prend le `scanCallbackRelay.delegate` via le pattern :
  ```kotlin
  DisposableEffect(viewModel) {
      val handler: (ScanResult) -> Unit = viewModel::onScanResult
      relay.delegate = handler
      onDispose {
          if (relay.delegate === handler) relay.delegate = null
      }
  }
  ```
  Le check `===` est **crucial** : pendant une transition de nav, l'ancien et le nouveau composable coexistent brièvement ; sans ce check le `onDispose` de l'ancien efface le delegate posé par le nouveau. Bug rencontré et corrigé dans la session Chunk 3.
- gère ses propres flags `CoinAnalyzer` (`photoMode`, `snapRequested`, `captureContext`, `recordMode`) avec cleanup en `DisposableEffect.onDispose`.

## Ce qui est livré (Chunks 1–3)

### Chunk 1 — Foundations (commit en suspens, à committer)

**Fichiers créés** :
- `features/dev/DevPlaceholderScreen.kt` — page TODO réutilisable avec back

**Fichiers modifiés** :
- `ui/nav/EurioDestinations.kt` — 4 nouvelles routes `DEV_PHOTO`, `DEV_CAPTURE`, `DEV_BENCH`, `DEV_CAROUSEL`
- `ui/nav/EurioNavHost.kt` — 4 nouveaux `composable(...)` (3 sont encore placeholder, seul `/dev/capture` est wired)
- `features/scan/debug/DebugBar.kt` — section "Outils dev" en tête de la bottom-sheet + enum `DevTool { PHOTO, CAPTURE, BENCH, CAROUSEL }`. Suppression de l'ancien bouton `onStartBenchProtocol`.
- `features/scan/debug/DebugBarLauncher.kt` — signature `onOpenDevTool: ((DevTool) -> Unit)?`
- `features/scan/ScanScreen.kt` — nouveau param `onOpenDevTool` forwardé au `DebugBarLauncher`

### Chunk 2 — Hoist BenchRecorder en singleton EurioApp

**Fichiers modifiés** :
- `EurioApp.kt` — `val benchRecorder: BenchRecorder by lazy { BenchRecorder(applicationContext, appScope) }` + import
- `features/scan/ScanViewModel.kt` — ctor param `applicationContext: Context?` → `benchRecorder: BenchRecorder?` injecté ; suppression du `BenchRecorder(it, viewModelScope)` inline
- `ui/nav/EurioNavHost.kt` — `ScanViewModelFactory` passe `app.benchRecorder` au lieu de `app.applicationContext`

Le BenchRecorder n'est plus tied au cycle d'un VM unique. Au Chunk 4 le BenchProtocolViewModel utilisera le même instance singleton, et le record-toggle dans DebugBar continue de fonctionner.

### Chunk 3 — Extract CaptureScreen + CaptureViewModel (+ fixes UX 2026-05-28)

**Fichiers créés** :
- `features/dev/capture/CaptureViewModel.kt` — VM dédié (300+ lignes). Logique : `enter()`/`leave()` pour cycle, `onSnap()`/`onAdvancePhoto()`/`onRedo()`/`onSkipCell()` pour actions user, `onScanResult()` pour résultats analyzer, gate `awaitingSnapResult` pour ignorer les frames in-flight du scan continu, manifest jsonl append.
- `features/dev/capture/CaptureScreen.kt` — écran complet, vue stable (camera + bannière + ring + 2 boutons). Pas de plein écran intermédiaire. Boutons changent libellés selon `snap != null` (skip cellule/SNAP ↔ refaire/suivant).
- `features/dev/capture/CaptureOverlays.kt` — `CaptureGuideOverlay` (bannière haute "PIÈCE 1/17 · STEP 1/5 · PHOTO 1/4 — ad-2014-…")
- `features/dev/capture/CaptureSnapRingOverlay.kt` — overlay qui remplace `PhotoGuideOverlay` quand un snap est pending. Même géométrie (rayon = 35 % du côté court), affiche le crop dans le disque OU un état d'échec si `cropPath == null`.
- `features/scan/components/CameraPreview.kt` — extrait de ScanScreen pour partage avec /dev/*. **Important** : `onDispose` n'appelle PLUS `provider.unbindAll()` (cf. fix ci-dessous).

**Fichiers modifiés** :
- `ui/nav/EurioNavHost.kt` — route `/dev/capture` câblée vers le vrai écran, `CaptureViewModelFactory` ajoutée, gate `BuildConfig.DEBUG` sur `onOpenDevTool` ; pattern delegate avec check `===` dans `composable(EurioDestinations.SCAN)`
- `features/scan/ScanViewModel.kt` — supprimé : `CaptureProgress`, `_captureMode`, `_captureProgress`, `captureCoinIdx/StepIdx/PhotoIdx/Count`, `captureSessionDir`, `autoSnapDismissJob`, `onCaptureToggle/Redo/Next/SnapPersisted`, `updateCaptureProgress`, `appendCaptureManifest`, branche `if (_captureMode.value)` dans `onScanResult`, capture-tagging dans `onSnap`. Passé de ~1690 lignes à ~1450.
- `features/scan/ScanScreen.kt` — supprimé : refs `captureMode`/`captureProgress`/`CaptureGuideOverlay`/`CaptureSnapResultLayer`/`onCaptureToggle*`. Passé de 549 lignes à 367.
- `features/scan/components/ScanDebugOverlay.kt` — strip simplifiée (rec / photo / snap) ; plus de bouton "capture"
- `app-android/Taskfile.yml` — filtre `android:logs` étendu : `Eurio:D CoinAnalyzer:D CoinDetector:D ScanVM:D CaptureProtocol:D BenchRecorder:D AndroidRuntime:E '*:S'`

**Fichier supprimé** :
- `features/scan/components/CaptureGuideOverlay.kt` (déplacé dans /dev/capture/CaptureOverlays.kt + adapté aux nouveaux types)

#### Bugs rencontrés + résolus pendant Chunk 3

1. **NORMALIZE FAILED fantôme au premier passage sur /dev/capture** : des frames in-flight du scan continu arrivaient au nouveau delegate avec `photoSnapCropPath=null` → faux échec. Fix : gate `awaitingSnapResult` dans CaptureViewModel — `onScanResult` ignore tout résultat avant un tap SNAP explicite.
2. **Caméra figée après aller-retour /scan ↔ /dev/capture** : `CameraPreview.onDispose` appelait `provider.unbindAll()`, ce qui tuait la session caméra du nouvel écran déjà bindée pendant la transition. Fix : retirer `unbindAll()` — CameraX libère naturellement les usecases via le `LifecycleOwner` du `NavBackStackEntry` qui passe à DESTROYED.
3. **Delegate écrasé pendant la transition** : `ScanScreen.onDispose` mettait `delegate=null`, ce qui effaçait le delegate posé par `CaptureScreen.factory` quelques ms plus tôt. Fix : pattern `DisposableEffect` + check `===` sur la référence handler avant de clear. Appliqué dans EurioNavHost (côté scan) et CaptureScreen (côté capture).
4. **Auto-advance qui blink la vue** : ancienne UX avec `CaptureSnapResultLayer` plein écran + autoDismiss 600ms (puis 2000ms) → user ne pouvait pas tap "refaire" + transition visuelle violente. Fix : **réécriture complète de l'UX** : vue stable (caméra + bannière + ring) — seul le contenu du ring change (crop affiché à la place du live) et les libellés des 2 boutons. Plus d'auto-dismiss. L'utilisateur tap "suivant" lui-même pour avancer la photo dans la même step ; auto-step à 4 photos. "skip cellule" = sauter step en l'absence de snap pending.

## Ce qu'il reste à faire

> **Note 2026-05-28** : les chunks 4, 5, 6 ci-dessous sont désormais ✅ livrés.
> Les sections gardent le plan d'origine comme trace ; les écarts effectifs sont
> notés en fin de chaque section.

### Chunk 4 — Extract BenchProtocolScreen (✅ livré)

**Objectif** : sortir le protocole bench guidé (`BenchProtocolHeader` + `BenchProtocolActions` + le state machine cell-by-cell) hors de ScanViewModel/ScanScreen vers `/dev/bench`.

**Création** :
- `features/dev/bench/BenchProtocolViewModel.kt`
  - State : `_benchProtocolState: StateFlow<BenchProtocolState?>` (peut rester non-null en permanence puisque l'écran EST le protocole, plus besoin de `null = inactive`)
  - Actions à porter depuis ScanViewModel (lignes 99-161 + 354-457 partiellement) :
    - `enter()` : init avec `BenchProtocol.cells()` ; vérifier que `CaptureProtocol.coins` n'est pas vide (sinon back avec un toast)
    - `startCurrentCell()` ← `startCurrentBenchCell` : appelle `benchRecorder.start(...)` avec config + deviceInfo + coin + condition
    - `markCurrentDone()` ← `markCurrentBenchCellDone`
    - `skipCurrent()` ← `skipCurrentBenchCell`
    - `leave()` : stop recorder si actif
  - Inject `benchRecorder: BenchRecorder` (singleton EurioApp depuis Chunk 2) + `coinAnalyzer` (pour `onFrame`) + `debugConfig` access
  - **Décision sur `forwardEventToBench`** : actuellement dans ScanViewModel (lignes 364-408), fonction pure qui map ScanEvent → BenchEvent. Utilisée par 2 consommateurs (scan record-mode dans DebugBar + bench protocol). Plan original : extraire en `ml/bench/BenchEventMapper.kt` (`object`, stateless). Décision pratique : on peut le faire ici, ou laisser dans ScanVM tant que record-mode y vit ; à reconsidérer si bench protocol a besoin d'un access dédié à ce mapping.
  - **Important** : le BenchProtocol guide est interactif (Start / Done / Skip), mais l'analyzer pendant une cellule tourne en mode normal (pas photoMode). Le recorder log des `frame_analyzed` events à chaque frame pendant qu'une cell est `IN_PROGRESS`. Donc le VM doit aussi piper les `ScanResult` au recorder (via relay).

- `features/dev/bench/BenchProtocolScreen.kt`
  - Layout : `CameraPreview` + `BenchProtocolHeader` (haut) + `BenchProtocolActions` (bas) + un HUD allégé si pertinent
  - DisposableEffect classique pour delegate + cleanup (même pattern que CaptureScreen)
  - Pas de tools strip à la `ScanDebugOverlay` — les actions sont dans BenchProtocolActions

- `BenchProtocolViewModelFactory` dans EurioNavHost

**Modifications** :
- `ui/nav/EurioNavHost.kt` — route `/dev/bench` → vraie BenchProtocolScreen (remplace placeholder)
- `features/scan/ScanViewModel.kt` — supprimer (lignes 99-161) :
  - `_benchProtocolState`, `benchProtocolState`
  - `startBenchProtocol()`, `startCurrentBenchCell()`, `markCurrentBenchCellDone()`, `skipCurrentBenchCell()`, `endBenchProtocol()`
  - `buildDeviceInfo()` peut rester en private fun, ou être extraite si BenchEventMapper la veut
  - **GARDER** : `forwardEventToBench()` reste utilisé par le record-mode toggle (le collector `debugConfig.collect { ... }` ligne ~660-700 qui fait `rec.start/stop`)
- `features/scan/ScanScreen.kt` — supprimer (lignes ~349-367) :
  - `val benchProtocol by viewModel.benchProtocolState.collectAsStateWithLifecycle()`
  - les blocks `benchProtocol?.let { ... BenchProtocolHeader(...) + BenchProtocolActions(...) ... }`
- Imports correspondants

**Tests audit** :
1. DBG → "Bench protocol" → arrive sur `/dev/bench`
2. Voir le header de cellule (coin × condition), Start fait passer la cellule en IN_PROGRESS, Done passe à DONE + cellule suivante, Skip = SKIPPED + suivante
3. JSONL bench écrit dans `eurio_debug/bench/sessions/<id>/events.jsonl` (vérifier via `adb shell run-as`)
4. Retour /scan → état propre, record-toggle dans DBG continue de fonctionner

> **Chunk 4 — écarts réels** : `BenchProtocolViewModel` ne pipe que les
> `frame_analyzed` events (via `onScanResult` quand cellule IN_PROGRESS), il
> n'orchestre pas la state machine scan. `forwardEventToBench` est resté dans
> ScanViewModel (record-mode). `debugConfigProvider` injecté = lambda sur le
> singleton `DebugScanConfigStore`.

### Chunk 5 — Extract PhotoScreen + CarouselScreen (✅ livré)

**Photo standalone** (`/dev/photo`) : très similaire à CaptureScreen mais sans le contexte capture. Re-utilise `PhotoGuideOverlay` + un layer crop preview, mais une seule cellule (pas de progress).
- Sortir `_photoMode`, `_photoSnap`, `_photoLiveCircleFound`, `onPhotoToggle`, `onSnap`, `onSnapAgain` du ScanViewModel
- Sortir aussi le block `if (_photoMode.value) { ... }` dans `onScanResult` (lignes 895-908)
- Sortir le rendering `PhotoGuideOverlay` + `PhotoSnapResultLayer` de ScanScreen (lignes ~349-365)
- `PhotoSnapResultLayer.kt` (composable existant dans `features/scan/components/`) référence `ScanViewModel.PhotoSnap` — à bouger dans `features/dev/photo/` + adapter au nouveau VM type
- Retirer le bouton "photo" de `ScanDebugOverlay.DebugToolsStrip` aussi (puisque accès via /dev/photo)

**Carousel** (`/dev/carousel`) : autonome, pas de camera.
- Sortir `_carouselMode`, `_carouselCurrent`, `carouselCoins`, `carouselIndex`, `toggleCarouselMode()` (→ `enter()`), `onCarouselPrev()/Next()`, `stepCarousel()`, `showCarouselAt()`
- Sortir le rendering `ScanCarouselNav` + `Coin3DTuningPanel` + `Coin3DViewer` + `ScanDebugModeToggle` ("3D coin carrousel" toggle qui pollue) de ScanScreen
- Réutiliser `coinRepository.findAllByFaceValue(2.0)` côté VM
- Ne pas mount CameraPreview (le carousel by-passe la camera)

**Tests audit** : DBG → "Photo" / "Carousel 3D" → flow fonctionnel ; /scan plus propre (plus de toggle "3D coin carrousel" visible).

> **Chunk 5 — écarts réels** : `PhotoSnapResultLayer` déplacé sous
> `features/dev/photo/` (plus dans `components/`) + retypé sur
> `PhotoViewModel.PhotoSnap`. `ScanDebugOverlay` réduit à record-only (params
> `photoMode`/`hasSnapResult`/`onPhotoToggle`/`onSnap`/`onReset` supprimés),
> `ScanDebugModeToggle` supprimé. `DevPlaceholderScreen` supprimé (toutes les
> routes /dev/* ont leur vrai écran). CarouselScreen ne monte PAS de
> CameraPreview.

### Chunk 6 — Cleanup final (✅ livré)

- **ScanViewModel** : devrait passer à ~800-900 lignes. Audit final pour s'assurer qu'il ne reste que :
  - Reducer + state machine scan
  - Camera lock controller + best-frame trigger
  - Archive pending → vault
  - Streak + set completion
  - Record toggle (juste set/clear flag analyzer + recordSessionDir)
  - Debug HUD pump
- **ScanScreen** : devrait passer à ~250 lignes. Structure cible :
  ```
  Scaffold
   └ Box(Ink background)
     ├ CameraPreview
     ├ when (state) { Idle, Detecting, Accepted, Failure } -> layer
     ├ ScanTopBar
     ├ if (BuildConfig.DEBUG) { ScanLockOverlay, ScanHud, DebugBarLauncher }
     └ snackbar host
  ```
- **MainActivity.kt** : le `ScanFab` central re-navigue vers SCAN même quand on est déjà sur SCAN. **Décision plan** : on cache le FAB sur les routes SCAN et `/dev/*`. Géré via `currentBackStackEntry?.destination?.route` check.
  - Aussi : la `EurioBottomBar` (Coffre / Profil) est visible sur les écrans /dev/*. À cacher aussi (les écrans dev sont en plein écran, retour via back).
- **Tests existants** : vérifier que `CaptureProtocolTest` et `ScanReducerTest` passent toujours. Aucun test ne devrait casser puisque le reducer et CaptureProtocol restent inchangés.
- **Memory** : créer `~/.claude/projects/-Users-musubi42-Documents-Musubi42-bizz-Eurio/memory/project_scan_screen_refacto.md` :
  ```yaml
  ---
  name: scan-screen-refacto
  description: ScanScreen split en routes /dev/* dédiées (capture, bench, photo, carousel), 2026-05-28
  metadata:
    type: project
  ---
  Refacto B livré 2026-05-28. ScanScreen redevenu minimaliste (Idle/Detecting/Accepted/Failure + HUD).
  Modes debug split sur routes /dev/* avec leurs VM dédiés. Pattern delegate : DisposableEffect +
  check `===` avant clear (sinon transition de nav écrase). CameraPreview ne fait PLUS `unbindAll()`
  en onDispose (CameraX gère via LifecycleOwner du NavBackStackEntry). Docs/refacto/scan-screen-split.md.
  ```
- **Memory à mettre à jour** : `feedback_chunk_audit_flow.md` (chunks toujours pertinents), créer aussi un `feedback_camera_preview_unbind.md` court rappelant le piège du `unbindAll` en onDispose.

> **Chunk 6 — écarts réels** : FAB + bottom bar cachés via
> `currentRoute?.startsWith("dev/")` dans `MainActivity` (variable `chromeHidden`
> = onboarding OU dev route), pas via une liste explicite de routes. Fix bonus
> non prévu au plan : fond noir Filament qui tournait avec le coin au flip
> carrousel → param `isOpaque: Boolean = true` ajouté à `Coin3DViewer`
> (propagé à `SceneView` + `rememberEnvironment`), `/dev/carousel` passe `false`.
> Memory créées : `project_scan_screen_refacto`, `feedback_camera_preview_unbind`.

## Points sensibles / pièges connus

1. **scanCallbackRelay single-consumer** : single delegate, pas de queue. Le pattern `DisposableEffect` + check `===` est obligatoire à chaque route /dev/* (et /scan) pour éviter les écrasements.
2. **CoinAnalyzer flags reset** : chaque /dev/* DOIT cleanup ses flags en `onDispose` (`photoMode`, `snapRequested`, `captureContext`, `onPhotoLiveDetection`). Pattern à copier depuis `CaptureViewModel.leave()`.
3. **CameraPreview** : ne PAS rajouter `provider.unbindAll()` en `onDispose` même si ça paraît plus propre — ça casse les transitions de nav (cf. bug Chunk 3).
4. **CaptureProtocol.coins peut être vide** : si aucun cohort.csv n'est pushed et l'asset par défaut est vide, le VM doit gérer (warning log + `progress=null`). Le composable peut afficher un message "push cohort.csv first" plutôt qu'un écran vide.
5. **forwardEventToBench duplication** : si bench protocol veut une copie de la fonction, l'extraire en `BenchEventMapper` plutôt que la dupliquer. Mais ce n'est pas bloquant — on peut laisser dans ScanVM pour l'instant.
6. **Tests parity Maestro** : `app-android/parity/` peut contenir des flows qui scrollent le DebugOverlay ou tap "capture". À vérifier (peu probable, la cohort capture flow est piloté côté admin/parity séparément).

## Commandes utiles

```bash
# Build + install + run
go-task android:install && go-task android:run

# Logs filtrés (le filtre inclut déjà les tags utiles depuis Chunk 3)
go-task android:logs

# Pull les fichiers debug (eval_real/, bench/sessions/, etc.)
go-task android:pull-debug

# Vérifier que la cohort est pushée
adb shell ls /storage/emulated/0/Android/data/com.musubi.eurio/files/Documents/eurio_capture/cohort.csv
```

## État git au moment du handoff

- Branche : `coin-richness/p3-schema`
- Aucun commit fait sur le refacto ; tout est en working tree non staged.
- Recommandation : faire 1 commit par chunk (1, 2, 3 déjà faisables maintenant, puis 4, 5, 6 au fur et à mesure).
- Modifications touchées (résumé) :
  - **Créés** : `features/dev/DevPlaceholderScreen.kt`, `features/dev/capture/{CaptureViewModel,CaptureScreen,CaptureOverlays,CaptureSnapRingOverlay}.kt`, `features/scan/components/CameraPreview.kt`, ce doc
  - **Modifiés** : `ui/nav/EurioDestinations.kt`, `ui/nav/EurioNavHost.kt`, `EurioApp.kt`, `features/scan/{ScanViewModel,ScanScreen}.kt`, `features/scan/debug/{DebugBar,DebugBarLauncher}.kt`, `features/scan/components/ScanDebugOverlay.kt`, `app-android/Taskfile.yml`
  - **Supprimés** : `features/scan/components/CaptureGuideOverlay.kt`

## Référence rapide — pattern delegate à appliquer aux chunks 4/5

```kotlin
// Dans composable() de EurioNavHost (ou directement dans le Screen, au choix)
DisposableEffect(viewModel) {
    val handler: (com.musubi.eurio.ml.ScanResult) -> Unit = viewModel::onScanResult
    viewModel.enter()
    relay.delegate = handler
    onDispose {
        if (relay.delegate === handler) relay.delegate = null
        viewModel.leave()
    }
}
```

## Référence rapide — pattern VM lifecycle

```kotlin
class XxxViewModel(private val coinAnalyzer: CoinAnalyzer, ...) : ViewModel() {
    @Volatile private var awaitingResult: Boolean = false  // si snap-style

    fun enter() {
        // reset state
        // set analyzer flags : photoMode, captureContext, onPhotoLiveDetection, etc.
    }

    fun leave() {
        // clear analyzer flags
        coinAnalyzer.photoMode = false
        coinAnalyzer.onPhotoLiveDetection = null
        // etc.
    }

    fun onScanResult(result: ScanResult) {
        if (!awaitingResult) return    // gate optional, selon le mode
        // ...
    }

    fun onFrame(image: ImageProxy) = coinAnalyzer.analyze(image)

    override fun onCleared() {
        super.onCleared()
        // garde-fou : process death etc.
        coinAnalyzer.photoMode = false
        coinAnalyzer.onPhotoLiveDetection = null
    }
}
```
