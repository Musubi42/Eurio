# Kickoff — Chunk 4 : AE / AF / AWB lock via Camera2Interop

> Brief auto-suffisant pour reprendre chunk 4 dans une session neuve.
> Doit être lisible sans charger l'historique des chunks précédents.

## Pré-lecture obligatoire

1. [`vision.md`](./vision.md) — §1 (scénario d'usage), §3 (cible end-state),
   §4 (state machine), P1 (reconnaissance/archivage découplés), P3 (trigger
   interchangeable).
2. [`decisions.md`](./decisions.md) — **D11** (AE/AF/AWB lock via
   Camera2Interop), **D18** (debug-bar BuildConfig.DEBUG only),
   **D22** (motion-during-lock = Abort, pas de boucle séparée).
3. [`chunk-4-ae-af-lock.md`](./chunk-4-ae-af-lock.md) — la spec complète.
4. Mémoires : `feedback_no_debt`, `feedback_chunk_audit_flow` (livraison
   chunk-par-chunk avec audit visuel, attendre le "go").
5. `CLAUDE.md` §R2 (tokens M3, pas de hex hardcodé).

## État du code au démarrage

**Chunks 1, 2, 3a, 3b livrés et auditté sur Pixel 9a.** Concrètement :

### Ce qui existe déjà

- **Debug-bar** (`features/scan/debug/`) : bottom-sheet avec sliders trigger
  (IoU, conf, N), toggles `aeLockEnabled` / `afLockEnabled` / `awbLockEnabled`,
  quality gates, burst size, record. FAB "DBG" bas-droite. HUD top
  semi-transparent. Gated `BuildConfig.DEBUG` strict.
- **Quality scoring** (`domain/scan/quality/` + `ml/quality/`) : `FrameScore`
  par frame, `FrameQualityScorer` (OpenCV Laplacian + exposure + completeness
  + motion), `ScoringPolicy.fromDebugConfig(...)`. HUD affiche
  `sharp / exp / comp / agg` avec pass marks ✓/✗.
- **Rolling buffer + selector** (`ml/trigger/`) : `RollingFrameBuffer` (capacité
  dynamique, `onEvict` recycle les bitmaps), `BestFrameSelector` (D8 :
  oldest-passing-all-gates ou fallback max-aggregate), `BufferedFrame`
  (avec `crop: Bitmap?`, `bbox: BboxF`, `detectionConfidence`,
  `detectionSource`, `arcfaceTop3`).
- **3 trigger strategies + factory** : `BoxStabilityTrigger`,
  `YoloConfidenceTrigger` (skip HOUGH-source), `ArcfaceConsensusTrigger`,
  `NoOpTriggerStrategy`. `TriggerStrategyFactory.create(config)`. Tests JVM
  verts (15 fichiers de tests sous `app-android/src/test/.../trigger/`).
- **HUD complet** (`features/scan/debug/ScanHud.kt`) : state row +
  "Fired: …" row (apparaît quand `triggerFireReason != null`) + secondary
  row (arcface top-3 / timings / `buf N/M`).
- **ScanViewModel câblé** : `debugConfig.collect { … }` met à jour
  `coinAnalyzer.scoringPolicy`, `coinAnalyzer.triggerStrategy`,
  `coinAnalyzer.rollingBuffer.setCapacity(burstSize)`. `onScanResult`
  wrappé en `try/finally` qui appelle `observeTrigger(result)` à un seul
  point de sortie (post-consensus). `handleFire` lance `BestFrameSelector`
  et met à jour HUD `bestFrameIndex` / `bestFrameScore` /
  `triggerFireReason` / `bestSelectionReason`. `returnToIdle` reset
  trigger + clear buffer + wipe HUD fire fields.
- **CoinAnalyzer** : possède `rollingBuffer` (capacity 5, onEvict =
  bitmap.recycle), `triggerStrategy` (volatile), `scoringPolicy`. Après
  scoring, push `BufferedFrame` (transfère ownership du bitmap normalisé).
  `ScanResult` expose `bufferSize` / `bufferCapacity` / `frameScore` /
  `normalizeMs` / `scoreMs`.

### Ce qui n'existe pas encore

- Aucun appel `cameraControl.startFocusAndMetering`.
- Aucun `CaptureRequestOptions` sur `Camera2CameraControl`.
- L'instance `Camera` retournée par `bindToLifecycle` est créée dans
  `ScanScreen.kt` mais **pas remontée** au ViewModel — il faudra
  l'exposer (voir §Architecture).
- Pas d'overlay graphique au-dessus de `CameraPreview` (le HUD textuel
  est en haut, mais rien ne dessine bbox/halo sur la preview elle-même).

### Dépendances Gradle

`app-android/build.gradle.kts` n'a **pas** `kotlinx-coroutines-guava`
aujourd'hui (vérifié — uniquement `kotlinx-coroutines-android:1.9.0`).
**À ajouter pour `ListenableFuture.await()`** :
```kotlin
implementation("org.jetbrains.kotlinx:kotlinx-coroutines-guava:1.9.0")
```

CameraX 1.4.1 est déjà là (`camera-core` / `camera-camera2` /
`camera-lifecycle` / `camera-view`).

## Périmètre du chunk 4

**Dans le scope** (spec complète dans `chunk-4-ae-af-lock.md`) :

1. `CameraLockController` qui wrap `Camera.cameraControl` +
   `Camera2CameraControl`, expose `lock(LockOptions)` / `release()` /
   `state: StateFlow<LockState>`.
2. `LockState` sealed (Idle / Acquiring / Locked / Failed / Released) +
   `LockOptions` data class avec `fromDebugConfig(...)`.
3. Wiring : ViewModel passe le controller au CoinAnalyzer ; sur
   `TriggerEvent.Fire`, `coroutineScope.launch { lock(...) }` ; sur
   `Abort` ou `returnToIdle`, `release()`.
4. HUD : ajout d'un badge `lock` (état + durée AF mesurée) dans la
   "Fired" row (ou une nouvelle row dédiée).
5. **Overlay graphique** au-dessus de `CameraPreview` : bbox détectée,
   AF region élargie, halo de lock, flash abort. Gated `BuildConfig.DEBUG`.
6. Tests instrumented pour vérifier `CONTROL_AE_LOCK = true` après lock,
   `CONTROL_AF_MODE = CONTINUOUS_PICTURE` après release.

**Hors scope** :

- `ImageCapture.takePicture` (chunk 5).
- State machine formelle Detecting → Locking → Capturing (chunk 6).
- Calibration empirique du timeout AF (chunk 7).

## Découpage proposé

Le doc est ~23k caractères. Suggestion **deux sous-chunks** auditables
séparément :

### Chunk 4a — CameraLockController + lock/release headless

Tout sauf l'overlay graphique. Concrètement :

- `ml/camera/CameraLockController.kt` + `LockState.kt` + `LockOptions.kt`
- Ajout `kotlinx-coroutines-guava` au build.gradle.kts
- `ScanScreen` : remonter l'instance `Camera` via callback au ViewModel
  après `bindToLifecycle`. Appeler `release()` dans
  `DisposableEffect.onDispose`.
- `ScanViewModel.attachCamera(camera: Camera)` qui instancie le
  controller et l'injecte dans `CoinAnalyzer` (nouveau champ volatile).
- `CoinAnalyzer` : sur `Fire` reçu (logique aujourd'hui dans la VM via
  `handleFire`), lancer `cameraLockController?.lock(LockOptions.fromDebugConfig(...))`
  dans `viewModelScope`. Sur `returnToIdle`, `release()`.
- HUD : ajouter `lockState: StateFlow<LockState>` exposé par le VM ; HUD
  affiche `Locked · AF✓ 342ms · AE✓ · AWB✓` dans la Fired row.
- Tests instrumented sur Pixel 9a (au moins le smoke test "AE_LOCK = true
  après fire").

**Audit visuel 4a** : caméra qui arrête de hunter après fire (pointer une
LED dans le champ, observer que l'expo reste figée). Reprise auto au
dismiss.

### Chunk 4b — Overlay graphique ScanLockOverlay

Le composant Compose au-dessus de la preview. Élément clé : **renommer
le fichier**, car `features/scan/components/ScanDebugOverlay.kt` existe
déjà (c'est l'overlay monospace de debug en bas d'écran). Conflit de
nom certain. Proposition : `features/scan/debug/ScanLockOverlay.kt`.

- `ScanLockOverlay` Canvas qui consomme `hudState` + `lockState` +
  `Flow<AbortEvent>` pour dessiner bbox (rounded 8dp), AF region
  pointillée, halo pulsing/solid, flash rouge abort.
- Animations Compose simples (`infiniteRepeatable` pour le pulse,
  fade-out 200ms pour l'abort flash). Pas de springs.
- Couleurs : `MaterialTheme.colorScheme.{primary, tertiary, error}` —
  jamais de hex (CLAUDE.md R2).
- `ScanViewModel` expose `SharedFlow<AbortEvent>` (replay=0,
  extraBufferCapacity=1) qu'il émet sur Abort.
- Intégration dans `ScanScreen.kt` après le `CameraPreview` et avant le
  `ScanHud` (z-order : preview → overlay → HUD).

**Audit visuel 4b** : sur fire, bbox + halo apparaissent et pulsent
pendant l'acquiring puis se figent. Sur abort (bouger la pièce vite
après fire), flash rouge 200ms.

## Décisions actées dans la spec

Lire `chunk-4-ae-af-lock.md` §"Questions ouvertes" pour le détail. Synthèse :

- **MeteringPoint** : `SurfaceOrientedMeteringPointFactory(1f,1f)` (coords
  normalisées 0..1) sur le centre de la bbox.
- **Timeout AF** : 800 ms (Pixel 9a converge ~300 ms ; marge pour
  mid-range). Exposé en `LockOptions.afTimeoutMs` pour bench chunk-7.
- **`disableAutoCancel()`** : OUI sur le `FocusMeteringAction`. On
  contrôle le release explicitement ; tous les chemins de sortie
  (Abort / returnToIdle / DisposableEffect.onDispose) appellent
  `release()`.
- **`setCaptureRequestOptions(...).await()`** : OUI (~50 ms surplus).
  Garantit que la request est appliquée avant de marquer Locked.
- **Region AF élargie 12 %** autour du centre bbox
  (`LockOptions.regionExpansion = 0.12f`). Focus le relief, pas la
  rim. Tunable bench.
- **Motion pendant lock** = `TriggerEvent.Abort` → `release()` + flash
  rouge overlay → état Detecting. **Pas de boucle de surveillance
  séparée.** (D22 acté.) Pour chunk 4 il n'y a pas encore de logique
  qui émet Abort — c'est OK, on câble le release() et l'overlay flash,
  l'émetteur viendra avec chunk 6.

## Gotchas / points d'attention

1. **Nom de fichier en collision** : `features/scan/components/ScanDebugOverlay.kt`
   existe déjà (panneau monospace bottom). Le doc chunk-4 propose un
   nouveau `features/scan/debug/ScanDebugOverlay.kt` (overlay graphique
   au-dessus de preview). **Renommer le nouveau en `ScanLockOverlay.kt`**
   pour éviter la confusion.

2. **L'instance `Camera` n'est pas remontée** au ViewModel aujourd'hui.
   `ScanScreen.kt:CameraPreview` capture `provider.bindToLifecycle(...)`
   localement dans une lambda `addListener` et ne l'expose pas. Il faut
   ajouter un callback `onCameraReady: (Camera) -> Unit` ou hoister la
   gestion vers le ViewModel. **Préférer le callback** — moins invasif,
   garde la séparation Composable/VM.

3. **Thread de `coinAnalyzer.triggerStrategy.observe(...)`** : c'est
   appelé dans `ScanViewModel.observeTrigger` qui tourne sur le thread
   de l'analyzer CameraX (callback `onResult`). Donc le `launch { lock() }`
   doit utiliser `viewModelScope` explicitement, **pas** le scope
   ambiant — sinon on lance sur le mauvais thread. Pattern actuel :
   `viewModelScope.launch { ... }` dans `emitAccepted`, à reproduire.

4. **`Camera2CameraControl.from(cameraControl)`** : nécessite l'opt-in
   `@OptIn(ExperimentalCamera2Interop::class)` (CameraX 1.4 le marque
   encore Experimental).

5. **`release()` idempotent** : appelé depuis `returnToIdle()` ET
   `DisposableEffect.onDispose` — peut être appelé 2× rapidement (ex:
   user dismiss → cooldown → leave screen). Le doc dit déjà
   "idempotent par construction" mais le vérifier en test.

6. **Buffer recycle déjà géré** : pas besoin d'y toucher en chunk 4. Le
   lock ne touche pas aux frames bufferisées ; chunk 5 viendra les
   chercher pour `ImageCapture`.

7. **`firedReason` HUD persistance** : aujourd'hui `triggerFireReason`
   est wipé par `returnToIdle`. Quand chunk 4 le lit pour combiner
   avec le badge `lock`, attention au moment du clear — si on clear
   trop tôt, le HUD perd la trace du Fire avant l'audit visuel.

## Plan de bataille (séquence recommandée)

1. Lire `chunk-4-ae-af-lock.md` en entier (~20 min).
2. Décider 4a-only ou 4a+4b dans la même session selon temps dispo.
3. **Étape 1 (4a)** :
   a. Ajouter `kotlinx-coroutines-guava` au `app-android/build.gradle.kts`,
      sync gradle.
   b. Créer `ml/camera/LockState.kt`, `LockOptions.kt`,
      `CameraLockController.kt`.
   c. Modifier `CameraPreview` dans `ScanScreen.kt` pour exposer un
      callback `onCameraReady`.
   d. `ScanViewModel.attachCamera(camera)` instancie le controller,
      l'injecte dans `coinAnalyzer.cameraLockController`.
   e. Dans `ScanViewModel.handleFire`, après `_hudState.update { ... }`,
      lancer `viewModelScope.launch { cameraLockController?.lock(...) }`.
   f. Dans `returnToIdle`, lancer `release()`.
   g. HUD : exposer `lockState`, afficher dans la Fired row.
   h. Test JVM `LockOptions.fromDebugConfig` (mapping fidèle).
   i. Test instrumented `lockSucceeds_inNormalLight` sur Pixel 9a.
   j. `go-task android:install`, audit visuel.
4. **Étape 2 (4b)** :
   a. `ScanLockOverlay.kt` Canvas + animations.
   b. `SharedFlow<AbortEvent>` exposé par VM.
   c. Layer dans `ScanScreen.kt` entre preview et HUD.
   d. Audit visuel : screencast OFF / BOX_STABILITY (fire + lock visible
      via overlay).

## Acceptance criteria (extraits de la spec)

- `triggerMode = OFF` → aucun lock, comportement strictement identique.
- `BOX_STABILITY + tous lock toggles ON` après fire : focus arrête de
  hunter 2-5s, expo constante (test LED).
- Toggle `afLock = OFF, aeLock = ON` → expo se fige, AF continue à
  hunter.
- Sortir du ScanScreen pendant un lock → `release()` via
  `DisposableEffect.onDispose`, vérifiable au retour.
- HUD : badge lock visible avec durée AF mesurée (ms).
- Pas de crash en bougeant un slider IoU pendant un lock actif.

## Mémoires & règles liées

- D11 (AE/AF/AWB lock via Camera2Interop) — implémenté ici.
- D18 (debug-bar = BuildConfig.DEBUG only) — les toggles existent déjà
  dans `DebugScanConfig` depuis chunk 1.
- D22 (motion-during-lock = Abort) — l'émetteur Abort vient avec
  chunk 6 ; chunk 4 câble juste le `release()` côté receveur.
- `feedback_no_debt` — pas de fallback silencieux : timeout AF →
  `LockState.Failed` explicite.
- `feedback_chunk_audit_flow` — livraison + attendre le "go" avant
  d'enchaîner.

## Sortie attendue de la session

- 4a livré, audit visuel passé sur Pixel 9a.
- 4b livré ou explicitement renvoyé à la session suivante avec
  son propre kickoff court (~30 lignes).
- Tests JVM + instrumented verts.
- APK debug + release compilés.
- État résumé en fin de session pour le prochain kickoff (chunk 5 ou
  chunk 4b selon découpage retenu).
