# Chunk 4 — AE/AF/AWB lock via Camera2Interop

> Quand le trigger du chunk-3 émet `Fire`, on verrouille l'autofocus
> sur la zone de la pièce, on lock l'exposition et la balance des
> blancs, puis on les relâche au retour Detecting ou sur Abort. Pas
> encore de `ImageCapture` (chunk-5) ni de bascule d'état formelle
> (chunk-6).

## Pré-requis

- Chunk 1 livré (toggles AE/AF/AWB dans DebugScanConfig).
- Chunk 3 livré (`TriggerEvent.Fire` émis avec `BufferSnapshot`).

## Goal

Quand un `TriggerEvent.Fire` arrive :

1. Le `CameraLockController` lance `startFocusAndMetering` sur la
   région de la bbox de la pièce → AF triggered + AE/AWB metering
   sur la pièce.
2. Une fois la `ListenableFuture<FocusMeteringResult>` complète, on
   bascule en `setCaptureRequestOptions(AE_LOCK=true, AWB_LOCK=true)`
   pour figer expo + balance pour la suite de la séquence.
3. Le HUD signale visuellement les transitions :
   `Fired → Locking AF → AF LOCKED → AE+AWB LOCKED`.
4. Sur `Abort`, sur retour Detecting (chunk-6 plus tard), ou sur
   `Composable.dispose`, on appelle `release()` : `AE_LOCK=false,
   AWB_LOCK=false` + `cancelFocusAndMetering()` qui rend la caméra à
   son mode continu.

À ce stade, **rien d'autre n'est branché** : pas de `ImageCapture`
sur la frame post-lock (chunk-5), pas de state machine (chunk-6).
On observe juste que le focus arrête de hunter, que l'expo est
figée, et on log la durée du verrouillage.

## Scope

**Dans le chunk** :

- `CameraLockController` : wrap `Camera.cameraControl` +
  `Camera2CameraControl`, expose `lock(region)` / `release()` /
  `isLocked: StateFlow<LockState>`.
- Données : `LockState` sealed (Idle / Acquiring / Locked / Failed /
  Released) + `LockResult` (success, durée, AF converged status).
- Wiring : `CoinAnalyzer.onFireEvent(...)` appelle
  `cameraLockController.lock(bbox)` ; les toggles AE/AF/AWB de
  `DebugScanConfig` filtrent les options effectivement appliquées.
- HUD : second row indique `Locking AF → Locked` avec délai
  mesuré ; toggle visible si lock désactivé.
- Tests instrumented : sur device, valider que le focus arrête de
  hunter et que l'expo se fige (visuel + introspection
  `Camera2CameraInfo`).

**Hors chunk** :

- `ImageCapture.takePicture` sur la frame post-lock (chunk-5).
- Bascule formelle `Detecting → Locking → Capturing` (chunk-6) —
  pour l'instant, c'est un side effect du `Fire`, mais l'app reste
  conceptuellement dans la machine actuelle.
- Calibration empirique du timeout AF (chunk-7).

## Architecture

```
CoinAnalyzer.observe(Fire)
        │
        ↓
CameraLockController.lock(region = primaryBbox)
        │
        ├─ if !aeLockEnabled && !afLockEnabled && !awbLockEnabled → no-op
        │
        ├─ startFocusAndMetering(FocusMeteringAction(region))  ── ListenableFuture
        │      │
        │      ↓ (await, timeout 800ms)
        │   FocusMeteringResult{isSuccessful}
        │      │
        ├─ setCaptureRequestOptions(AE_LOCK, AWB_LOCK)  ── per toggles
        │
        └─ LockState.Locked + emit to HUD

CoinAnalyzer.observe(Abort) | ScanScreen.dispose | ScanState.idle
        │
        ↓
CameraLockController.release()
        │
        ├─ setCaptureRequestOptions(AE_LOCK=false, AWB_LOCK=false)
        ├─ cameraControl.cancelFocusAndMetering()
        └─ LockState.Idle + emit to HUD
```

Le `CameraLockController` est instancié dans le Composable
`CameraPreview` (où `Camera` est obtenu via
`processCameraProvider.bindToLifecycle`), passé via le `ScanViewModel`
au `CoinAnalyzer`. Pas de singleton process-wide — un par session
caméra.

## Fichiers à créer

| Fichier | Rôle |
|---|---|
| `ml/camera/CameraLockController.kt` | Wrap CameraControl + Camera2CameraControl, gère lock/release et état |
| `ml/camera/LockState.kt` | Sealed class des états + LockResult data class |
| `ml/camera/LockOptions.kt` | data class qui dit quoi locker (AE/AF/AWB toggles + tunables bench) |
| `features/scan/debug/ScanDebugOverlay.kt` | Layer Compose dessinant bbox/AF region/halo/flash selon phase (BuildConfig.DEBUG only) |
| `features/scan/debug/AbortEvent.kt` | data class de l'event consommé par l'overlay pour le flash |
| `app-android/src/androidTest/.../CameraLockControllerInstrumentedTest.kt` | Tests device : vérifier que le focus se fige |

## Fichiers à modifier

| Fichier | Modification |
|---|---|
| `features/scan/ScanScreen.kt` | Instancier le `CameraLockController` après `bindToLifecycle`, passer au ViewModel ; appeler `release()` dans `DisposableEffect.onDispose` |
| `features/scan/ScanViewModel.kt` | Exposer le `CameraLockController` au `CoinAnalyzer` ; observer `LockState` pour le HUD |
| `ml/CoinAnalyzer.kt` | Sur `TriggerEvent.Fire`, appeler `cameraLockController.lock(bbox, options)` ; sur `Abort`, `release()` |
| `features/scan/debug/ScanHud.kt` | Ajouter un badge `lock` (état + durée) dans la second row |
| `app/build.gradle.kts` | Ajouter `kotlinx-coroutines-guava` si pas déjà présent (pour `.await()` sur ListenableFuture) |

## Schémas Kotlin

### `LockState`

```kotlin
sealed class LockState {
    object Idle : LockState()
    object Acquiring : LockState()          // startFocusAndMetering en cours
    data class Locked(
        val acquiredAtNs: Long,
        val durationMs: Long,
        val afConverged: Boolean,           // true si AF.isSuccessful
        val aeLocked: Boolean,
        val awbLocked: Boolean,
    ) : LockState()
    data class Failed(
        val reason: String,
        val durationMs: Long,
    ) : LockState()
    object Released : LockState()           // transient → revient à Idle
}
```

### `LockOptions`

```kotlin
data class LockOptions(
    val aeLock: Boolean,
    val afLock: Boolean,
    val awbLock: Boolean,
    val afTimeoutMs: Long = 800L,           // tunable bench, défaut 800ms (cf. D22)
    val regionExpansion: Float = 0.12f,     // élargissement bbox→AF region, défaut 12%
    val region: MeteringRect,               // bbox de la pièce en coords frame (avant expansion)
)

data class MeteringRect(
    val left: Float, val top: Float, val right: Float, val bottom: Float,
)

fun LockOptions.Companion.fromDebugConfig(
    config: DebugScanConfig,
    region: MeteringRect,
): LockOptions = LockOptions(
    aeLock = config.aeLockEnabled,
    afLock = config.afLockEnabled,
    awbLock = config.awbLockEnabled,
    region = region,
)
```

### `CameraLockController` — squelette

```kotlin
class CameraLockController(
    private val camera: Camera,
) {
    private val cameraControl = camera.cameraControl
    private val camera2Control = Camera2CameraControl.from(cameraControl)

    private val _state = MutableStateFlow<LockState>(LockState.Idle)
    val state: StateFlow<LockState> = _state.asStateFlow()

    private var currentLockJob: Job? = null

    suspend fun lock(options: LockOptions) {
        currentLockJob?.cancel()
        currentLockJob = currentCoroutineContext().job

        if (!options.aeLock && !options.afLock && !options.awbLock) {
            // Tous les toggles off → no-op, on reste en Idle.
            return
        }

        val startedNs = SystemClock.elapsedRealtimeNanos()
        _state.value = LockState.Acquiring

        val afConverged = if (options.afLock) {
            val action = FocusMeteringAction.Builder(
                SurfaceOrientedMeteringPointFactory(1f, 1f)
                    .createPoint(
                        (options.region.left + options.region.right) / 2f,
                        (options.region.top + options.region.bottom) / 2f,
                    ),
                FocusMeteringAction.FLAG_AF,
            )
                .disableAutoCancel()             // on contrôle nous-mêmes le release
                .build()

            try {
                withTimeout(options.afTimeoutMs) {
                    val future = cameraControl.startFocusAndMetering(action)
                    future.await().isSuccessful
                }
            } catch (e: TimeoutCancellationException) {
                false
            } catch (e: Exception) {
                _state.value = LockState.Failed(
                    reason = "AF startFocusAndMetering threw: ${e.message}",
                    durationMs = (SystemClock.elapsedRealtimeNanos() - startedNs) / 1_000_000,
                )
                return
            }
        } else true

        if (options.aeLock || options.awbLock) {
            val captureOptions = CaptureRequestOptions.Builder().apply {
                if (options.aeLock)  setCaptureRequestOption(CaptureRequest.CONTROL_AE_LOCK,  true)
                if (options.awbLock) setCaptureRequestOption(CaptureRequest.CONTROL_AWB_LOCK, true)
            }.build()
            camera2Control.setCaptureRequestOptions(captureOptions).await()
        }

        val durationMs = (SystemClock.elapsedRealtimeNanos() - startedNs) / 1_000_000
        _state.value = LockState.Locked(
            acquiredAtNs = SystemClock.elapsedRealtimeNanos(),
            durationMs = durationMs,
            afConverged = afConverged,
            aeLocked = options.aeLock,
            awbLocked = options.awbLock,
        )
    }

    suspend fun release() {
        currentLockJob?.cancel()
        currentLockJob = null

        try {
            // Off AE/AWB locks regardless of current state.
            camera2Control.setCaptureRequestOptions(
                CaptureRequestOptions.Builder()
                    .setCaptureRequestOption(CaptureRequest.CONTROL_AE_LOCK,  false)
                    .setCaptureRequestOption(CaptureRequest.CONTROL_AWB_LOCK, false)
                    .build()
            ).await()
            cameraControl.cancelFocusAndMetering().await()
        } catch (e: Exception) {
            // Best-effort release. Log mais on ne propage pas.
        }

        _state.value = LockState.Released
        // Transient: revient à Idle après tick UI.
        _state.value = LockState.Idle
    }
}
```

**Notes d'implémentation** :

- `FocusMeteringAction.disableAutoCancel()` est crucial : sans ça,
  CameraX programme un auto-cancel après quelques secondes et le lock
  saute tout seul.
- `cameraControl.startFocusAndMetering(action).await()` requiert
  `kotlinx-coroutines-guava` (déjà recommandé par CameraX docs).
- `currentLockJob` permet de cancel un `lock()` en cours si un nouveau
  arrive (rare mais possible si l'utilisateur change vite de mode).
- `release()` est **idempotent** : appeler 2× ne casse rien, juste
  des `setCaptureRequestOptions(false)` redondants.
- En cas de device qui ne supporte pas `CONTROL_AE_LOCK` (très ancien
  Android < 21, hors scope minSdk 26), le setter est silencieusement
  ignoré par Camera2. Pas de crash.

## Wiring dans `CoinAnalyzer`

```kotlin
class CoinAnalyzer(
    // ... existing
    private val cameraLockController: CameraLockController,
    private val coroutineScope: CoroutineScope,
) {
    fun analyzeFrame(imageProxy: ImageProxy) {
        // ... existing pipeline (detect → score → arcface → buffer → trigger)

        when (val event = triggerStrategyFlow.value.observe(context)) {
            is TriggerEvent.Fire -> {
                val result = bestFrameSelector.select(event.bufferSnapshot)
                val best = (result as? SelectionResult.Best) ?: return

                // NEW: lock caméra sur la bbox de la frame retenue.
                val region = best.frame.detection.bbox.toMeteringRect(bitmap.size())
                coroutineScope.launch {
                    cameraLockController.lock(
                        LockOptions.fromDebugConfig(debugConfig.value, region)
                    )
                }

                hudState.update {
                    it.copy(
                        bestFrameIndex = best.indexInSnapshot,
                        bestFrameScore = best.frame.score,
                        machineState = "Fired → Locking",
                    )
                }
                triggerStrategyFlow.value.reset()
            }
            TriggerEvent.Abort -> {
                coroutineScope.launch { cameraLockController.release() }
                triggerStrategyFlow.value.reset()
            }
            null -> Unit
        }
    }
}
```

Le `coroutineScope` passé doit être lié au `viewModelScope` (donc
auto-cancel quand le scan screen se ferme).

## Wiring dans `ScanScreen` / `ScanViewModel`

`ScanScreen.kt`, dans le bloc CameraX :

```kotlin
val cameraLockController = remember { mutableStateOf<CameraLockController?>(null) }

LaunchedEffect(Unit) {
    val provider = ProcessCameraProvider.getInstance(context).await()
    val camera = provider.bindToLifecycle(
        lifecycleOwner,
        cameraSelector,
        previewUseCase,
        imageAnalysisUseCase,
        // (chunk-5 ajoutera imageCaptureUseCase ici)
    )
    cameraLockController.value = CameraLockController(camera)
    scanViewModel.attachCameraLockController(cameraLockController.value!!)
}

DisposableEffect(Unit) {
    onDispose {
        coroutineScope.launch {
            cameraLockController.value?.release()
        }
    }
}
```

`ScanViewModel.attachCameraLockController(controller)` injecte
le controller dans le `CoinAnalyzer` déjà instancié, et expose son
`StateFlow<LockState>` pour le HUD :

```kotlin
val lockState: StateFlow<LockState> =
    _cameraLockController
        .flatMapLatest { it?.state ?: flowOf(LockState.Idle) }
        .stateIn(viewModelScope, SharingStarted.Eagerly, LockState.Idle)
```

## ScanDebugOverlay — visualisation graphique des phases

Nouveau composant Compose `features/scan/debug/ScanDebugOverlay.kt`,
gated `BuildConfig.DEBUG`, layered par-dessus `CameraPreview` (sous
le HUD textuel). C'est la couche qui rend **spatialement** visible
ce qui se passe — complémentaire au HUD textuel qui donne les chiffres.

### Éléments dessinés

| Élément | Conditions | Apparence |
|---|---|---|
| **bbox détectée** | dès qu'une frame a une `primaryDetection` | Rectangle avec rayon de coin 8dp, stroke 2dp |
| **AF region élargie** | pendant `LockState.Acquiring` | Rectangle pointillé 1dp, stroke `tertiary` |
| **halo de lock** | `Acquiring` (pulse) ou `Locked` (fixe) | Cercle centré sur bbox, rayon = `bbox.radius * 1.2` |
| **flash abort** | sur `TriggerEvent.Abort` | Pulse rouge 200ms autour de la dernière bbox |
| **label timing** | `Locked` avec `durationMs` | Texte petit en haut-droit de la bbox |

### Code couleur selon phase

| Phase | bbox stroke | halo |
|---|---|---|
| Idle / pas de bbox | (rien) | (rien) |
| Detecting | `tertiary` 2dp solid | (rien) |
| Fired → Acquiring | `primary` 2dp solid, animated pulse | `primary` outline pulsing |
| Locked | `primary` 3dp solid + fill `primary @ 8%` | `primary` outline solid |
| Failed | `error` 2dp solid | (rien) |
| Aborted | flash `error` 200ms → fade | (rien) |

Tous les codes couleur passent par `MaterialTheme.colorScheme.*`
(CLAUDE.md R2, aucun hex hardcodé).

### Mock visuel

```
        ┌─────────────────────────────────┐
        │ ╔═══════════════════════╗ 312ms │  ← label timing
        │ ║·····················  ║       │
        │ ║·    ┌─────────┐    ··║        │  ← AF region pointillée
        │ ║·    │         │    ··║        │
        │ ║·    │  COIN   │    ··║        │  ← bbox primary 3dp solid
        │ ║·    │   ⬤    │     ··║        │  ← halo lock solid
        │ ║·    └─────────┘    ··║        │
        │ ║·····················  ║       │
        │ ╚═══════════════════════╝       │
        └─────────────────────────────────┘
                  [Locked phase]
```

### Animations

- **Pulse Acquiring** : alpha de la bbox stroke et du halo oscille
  entre 0.5 et 1.0, période 600 ms (`infiniteRepeatable` Compose).
- **Flash abort** : alpha rouge 1.0 → 0.0 en 200 ms, ease-out.
- **Transition Locked → Idle** (sur release) : bbox fade out 150 ms.

Pas de springs ni de physics — animations courtes et lisibles. On
veut comprendre, pas faire joli.

### Synchronisation avec le pipeline

Le composant consomme :

- `hudState.machineState` (chunk-3) pour la couleur
- `hudState.lastFrameScore` + `lastDetection` pour la position bbox
- `lockState` (chunk-4) pour l'overlay AF + halo + timing
- Un `SharedFlow<AbortEvent>` (à exposer depuis ViewModel) pour
  déclencher le flash abort indépendamment des states (le flash a
  besoin d'un event, pas d'un state)

```kotlin
@Composable
fun ScanDebugOverlay(
    state: ScanHudState,
    lockState: LockState,
    abortEvents: Flow<AbortEvent>,
    modifier: Modifier = Modifier,
) {
    if (!BuildConfig.DEBUG) return
    // Canvas dessine bbox / AF region / halo / flash selon state + animations
}
```

## HUD — update affichage

Second row HUD enrichie :

```
┌─────────────────────────────────────────────────────────────────────┐
│ Detecting · sharp 142✓ · exp 0.48✓ · comp 1.00✓ · agg 0.84          │
├─────────────────────────────────────────────────────────────────────┤
│ Fired → Locking · AF acquiring · AE off · AWB on                    │
└─────────────────────────────────────────────────────────────────────┘
```

À la résolution du lock :

```
│ Locked · AF✓ 342ms · AE✓ · AWB✓ · best#3 agg 0.91                   │
```

Sur fail :

```
│ Lock failed · AF✗ timeout 800ms · best#3 agg 0.91                   │
```

Sur release :

```
│ Detecting · …                                                       │
```

## Acceptance criteria

**Fonctionnel** :
- [ ] `triggerMode = OFF` → aucun lock, comportement identique.
- [ ] `triggerMode = BOX_STABILITY + aeLock/afLock/awbLock = ON` :
      après fire, le focus arrête de hunter pendant 2-5s, l'expo
      reste constante (visuellement, observer un bord lumineux à
      proximité — il ne réagit plus).
- [ ] Toggles individuels respectés : `afLock = OFF, aeLock = ON` →
      l'expo se fige mais l'AF continue à hunter.
- [ ] Sur `release()` : focus reprend la chasse continue
      immédiatement.
- [ ] HUD : badge de lock visible avec durée AF mesurée.
- [ ] Aucun crash quand on bouge le slider IoU pendant un lock actif
      (le job de lock courant peut se faire annuler proprement).

**Lifecycle** :
- [ ] Sortir de ScanScreen pendant un lock → `release()` appelé via
      `DisposableEffect.onDispose`, vérifiable en relogeant le scan
      et voyant que le focus est libre.
- [ ] Backgroup app / retour : pas de leak, lock relâché
      automatiquement par Camera2.

**Timing** :
- [ ] AF lock acquired typique sur Pixel 9a : 200-500 ms en lumière
      normale.
- [ ] Timeout 800 ms respecté : en condition extrême (low light), on
      passe en `LockState.Failed` sans bloquer le pipeline.
- [ ] `setCaptureRequestOptions` AE/AWB → effet visible à la frame
      suivante (< 100 ms).

**Tests** :
- [ ] Test instrumented `lockSucceeds_inNormalLight` : capture
      Camera2CameraInfo avant/après, vérifie `CONTROL_AE_LOCK = true`.
- [ ] Test instrumented `releaseRestoresAutoFocus` : après release,
      observer `CONTROL_AF_MODE = CONTINUOUS_PICTURE`.
- [ ] Test unitaire `LockOptions.fromDebugConfig` : map fidèle des
      toggles.
- [ ] Test unitaire (avec fake camera) : 3 séquences (success,
      timeout, exception).

## Questions ouvertes à trancher pendant l'implem

1. **MeteringPointFactory : `SurfaceOriented` ou `Display` ?**
   `SurfaceOriented` (coords normalisées 0..1 dans le buffer
   analyzer) est plus stable car découplé du display. Mon vote :
   `SurfaceOriented`. À valider si l'orientation device tilt-portrait
   produit bien la même région.
2. **Timeout AF = 800 ms ?** Empirique. Pixel 9a converge en ~300 ms
   typique ; mid-range Samsung peut prendre 600+ ms. 800 ms laisse
   du jeu. À benchmarker sur cohort device au chunk-7.
3. **Comportement si l'utilisateur bouge la pièce pendant le lock ?**
   **TRANCHÉ via D22** : option A confirmée. Le trigger émet
   `TriggerEvent.Abort` → `CameraLockController.release()` → overlay
   flash rouge → état Detecting. Pas de boucle de surveillance motion
   séparée.
4. **`disableAutoCancel()` vs auto-cancel 5s par défaut ?** J'ai
   désactivé pour garder le contrôle explicite. Alternative : laisser
   l'auto-cancel comme garde-fou supplémentaire (5s, c'est probablement
   plus long qu'un lock+capture). Mon vote : on garde
   `disableAutoCancel`, mais on s'assure que tous les chemins de
   sortie appellent `release()`.
5. **`Camera2CameraControl.setCaptureRequestOptions().await()` vs
   fire-and-forget ?** `await()` garantit que la request est
   appliquée avant de marquer Locked. Coût ~50 ms supplémentaires.
   Mon vote : `await()` pour la propreté du state machine ; si bench
   montre que c'est trop, on passe en fire-and-forget avec un small
   delay arbitraire.
6. **Région AF = bbox stricte ou bbox élargie ?**
   **ACTÉ** : élargie 10-15% autour du centre bbox par défaut
   (focus sur le relief intérieur, pas la rim). Valeur exacte à
   tuner via le bench chunk-7 — `LockOptions` expose une marge
   configurable `regionExpansion: Float = 0.12f`.

## Mémoires & règles liées

- D11 (AE/AF/AWB lock via Camera2Interop pendant Locking) — implémenté
  ici. Le release au passage Accepted sera câblé proprement par
  chunk-6 (state machine).
- D18 (debug-bar BuildConfig.DEBUG only) — les toggles AE/AF/AWB sont
  exposés en debug, en release ils auront un défaut hard-codé
  (probablement les 3 à `true`, à confirmer après bench).
- `feedback_no_debt` — pas de fallback silencieux : un timeout AF
  produit `LockState.Failed` explicite, pas un null balayé.
- `feedback_chunk_audit_flow` — audit attendu : screencast device qui
  montre le focus qui se fige après fire, l'expo constante (placer
  une LED dans le champ et constater qu'elle ne sur-expose plus la
  pièce), et la reprise auto-focus après release.
