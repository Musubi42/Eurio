package com.musubi.eurio.features.scan

import android.util.Log
import androidx.camera.core.Camera
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.data.vault.CaptureMetadata
import com.musubi.eurio.data.vault.PendingArchiveBuffer
import com.musubi.eurio.data.vault.VaultCaptureRepository
import com.musubi.eurio.domain.scan.ArcfaceMatch
import com.musubi.eurio.domain.scan.ScanEvent
import com.musubi.eurio.domain.scan.ScanReducer
import com.musubi.eurio.domain.scan.SideEffect
import com.musubi.eurio.domain.scan.SourceMode
import com.musubi.eurio.domain.scan.TimeoutScheduler
import com.musubi.eurio.domain.scan.ScanState as DomainScanState
import com.musubi.eurio.ml.bench.BenchEvent
import com.musubi.eurio.ml.bench.BenchRecorder
import com.musubi.eurio.ml.bench.ArcfacePayload
import com.musubi.eurio.ml.bench.toPayload
import com.musubi.eurio.ml.camera.CameraLockController
import com.musubi.eurio.ml.camera.LockOptions
import com.musubi.eurio.ml.camera.LockState
import com.musubi.eurio.ml.camera.MeteringRect
import com.musubi.eurio.ml.camera.fromDebugConfig
import com.musubi.eurio.ml.camera.toSnapshot
import com.musubi.eurio.ml.image.JpegPipeline
import java.util.UUID
import java.util.concurrent.Executors
import com.musubi.eurio.BuildConfig
import com.musubi.eurio.data.repository.CoinRepository
import com.musubi.eurio.data.repository.SetRepository
import com.musubi.eurio.data.repository.StreakRepository
import com.musubi.eurio.data.repository.VaultRepository
import com.musubi.eurio.domain.scan.quality.ScoringPolicy
import com.musubi.eurio.features.scan.components.DebugViewData
import com.musubi.eurio.features.scan.debug.AbortEvent
import com.musubi.eurio.features.scan.debug.DebugScanConfig
import com.musubi.eurio.features.scan.debug.DebugScanConfigStore
import com.musubi.eurio.features.scan.debug.ScanHudState
import com.musubi.eurio.features.scan.debug.TimingBreakdown
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.ScanResult
import com.musubi.eurio.ml.trigger.BboxF
import com.musubi.eurio.ml.trigger.BestFrameSelector
import com.musubi.eurio.ml.trigger.FrameContext
import com.musubi.eurio.ml.trigger.SelectionReason
import com.musubi.eurio.ml.trigger.SelectionResult
import com.musubi.eurio.ml.trigger.TriggerEvent
import com.musubi.eurio.ml.trigger.TriggerStrategyFactory
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ViewModel coordinating the Scan feature.
 *
 * UX decision (feedback_scan_ux.md): the scan is CONTINUOUS like a QR code
 * scanner. It never shows a "not found" popup. If detection stalls, the UI
 * silently returns to Idle and keeps the viewfinder live.
 */
class ScanViewModel(
    private val coinRepository: CoinRepository,
    private val vaultRepository: VaultRepository,
    private val streakRepository: StreakRepository,
    private val coinAnalyzer: CoinAnalyzer,
    private val setRepository: SetRepository? = null,
    private val onAppEvent: ((com.musubi.eurio.domain.AppEvent) -> Unit)? = null,
    private val vaultCaptureRepository: VaultCaptureRepository? = null,
    private val pendingArchiveBuffer: PendingArchiveBuffer = PendingArchiveBuffer(),
    /**
     * App-scoped singleton (cf. EurioApp). Null en tests et dans la factory
     * parity/QA — la wiring bench short-circuit quand null.
     */
    private val benchRecorder: BenchRecorder? = null,
) : ViewModel() {

    companion object {
        private const val TAG = "ScanVM"
        const val DISMISS_COOLDOWN_MS = 3_000L
        const val ALREADY_OWNED_TOAST_MS = 2_000L
        const val DEBUG_TAP_COUNT = 7
        const val DEBUG_TAP_WINDOW_MS = 2_000L
        private const val IDLE_RETURN_THRESHOLD = 4
    }

    private val _state = MutableStateFlow<ScanUiState>(ScanUiState.Idle)
    val state: StateFlow<ScanUiState> = _state.asStateFlow()

    fun forceState(state: ScanUiState) {
        if (!BuildConfig.IS_QA) return
        Log.d(TAG, "[QA] Forcing scan state: $state")
        _state.value = state
    }

    private val _debugMode = MutableStateFlow(false)
    val debugMode: StateFlow<Boolean> = _debugMode.asStateFlow()

    // ── Best-frame capture observability (chunk-1) ───────────────────────────
    // In debug builds, mirrors the shared in-memory store. In release the
    // store reference is wrapped in a BuildConfig.DEBUG guard so the pipeline
    // reads frozen defaults — see [debugConfig].
    val debugConfig: StateFlow<DebugScanConfig> =
        if (BuildConfig.DEBUG) {
            DebugScanConfigStore.config
        } else {
            MutableStateFlow(DebugScanConfig()).asStateFlow()
        }

    // HUD state is exposed regardless of build type so future chunks (2-6)
    // can update it unconditionally; only the debug build composes the HUD
    // that observes it.
    private val _hudState = MutableStateFlow(ScanHudState())
    val hudState: StateFlow<ScanHudState> = _hudState.asStateFlow()

    // ── Best-frame capture chunk-4 — AE/AF/AWB lock controller ────────────
    // The controller is instantiated from the CameraPreview composable once
    // `bindToLifecycle` returns and is handed back here via [attachCamera].
    // Released + nulled on [detachCamera] (DisposableEffect.onDispose) so a
    // re-mount creates a fresh controller bound to the new Camera instance.
    private val _cameraLockController = MutableStateFlow<CameraLockController?>(null)

    @OptIn(ExperimentalCoroutinesApi::class)
    val lockState: StateFlow<LockState> =
        _cameraLockController
            .flatMapLatest { it?.state ?: flowOf(LockState.Idle) }
            .stateIn(viewModelScope, SharingStarted.Eagerly, LockState.Idle)

    // ── Best-frame capture chunk-4b — abort event stream ──────────────────
    // Transient flash signal consumed by [ScanLockOverlay]. Replay=0 because
    // the flash should only fire when the abort actually happens, not when
    // the overlay re-subscribes. extraBufferCapacity=1 absorbs a burst if
    // the analyzer aborts twice in the same composition frame.
    private val _abortEvents = MutableSharedFlow<AbortEvent>(
        replay = 0,
        extraBufferCapacity = 1,
    )
    val abortEvents: SharedFlow<AbortEvent> = _abortEvents.asSharedFlow()

    // ── Best-frame capture chunk-5d — snackbar D17 promote primary ────────
    private val _snackbarEvents = MutableSharedFlow<ScanSnackbarEvent>(
        replay = 0,
        extraBufferCapacity = 1,
    )
    val snackbarEvents: SharedFlow<ScanSnackbarEvent> = _snackbarEvents.asSharedFlow()

    private val _debugData = MutableStateFlow(DebugViewData())
    val debugData: StateFlow<DebugViewData> = _debugData.asStateFlow()

    // Continuous record mode (debug bar). Captures full pipeline state per frame
    // into a session directory under the analyzer's debugRootDir.
    private val _recordMode = MutableStateFlow(false)
    val recordMode: StateFlow<Boolean> = _recordMode.asStateFlow()

    private val _recordedFrameCount = MutableStateFlow(0)
    val recordedFrameCount: StateFlow<Int> = _recordedFrameCount.asStateFlow()

    // Photo mode / capture cohort / carousel déplacés vers features/dev/* (refacto 2026-05-28).

    val streakCount: StateFlow<Int> = streakRepository.currentStreak

    private val consensus = ConsensusBuffer()

    // ── Chunk-6.2a — shadow state machine ─────────────────────────────────
    // The new domain reducer runs in parallel with the legacy [_state] flow.
    // For 6.2a it is **observation-only**: side effects are *not* applied
    // to the camera / capture / archive paths (those are still driven by
    // the legacy callsites). The only side effects honoured here are the
    // passive timeouts — they let the shadow machine transition out of
    // `Locking` / `Capturing` / `Identifying` so the HUD reflects reality
    // even when an event is missing. The legacy flow is unaffected because
    // it doesn't observe [_scanMachineState].
    //
    // Wiring debt: every site that should emit a domain event has a
    // `_scanEvents.tryEmit(...)` call inline. Once 6.2b makes the reducer
    // the source of truth, those tryEmits become the only place those
    // events fire — duplicated emit risk goes away with the legacy logic.
    private val _scanEvents = MutableSharedFlow<ScanEvent>(
        replay = 0,
        extraBufferCapacity = 32,
    )

    private val _scanMachineState = MutableStateFlow<DomainScanState>(DomainScanState.Idle)
    val scanMachineState: StateFlow<DomainScanState> = _scanMachineState.asStateFlow()

    private val timeoutScheduler = TimeoutScheduler(viewModelScope) { event ->
        _scanEvents.tryEmit(event)
    }

    private fun emitScanEvent(event: ScanEvent) {
        _scanEvents.tryEmit(event)
    }

    // ── Chunk-7a — bench wiring helpers ───────────────────────────────────

    private fun buildDeviceInfo(): BenchEvent.DeviceInfo = BenchEvent.DeviceInfo(
        t = 0.0,  // rewritten by recorder.start()
        model = android.os.Build.MODEL,
        api = android.os.Build.VERSION.SDK_INT,
        manufacturer = android.os.Build.MANUFACTURER,
        sensor = null,
    )

    private fun forwardEventToBench(event: ScanEvent) {
        val rec = benchRecorder?.takeIf { it.isActive } ?: return
        val t = rec.nowSeconds()
        val mapped: BenchEvent? = when (event) {
            is ScanEvent.TriggerFire -> BenchEvent.TriggerFire(
                t = t,
                strategy = debugConfig.value.triggerMode.name,
                reason = event.reason,
            )
            ScanEvent.TriggerAbort -> BenchEvent.TriggerAbort(t = t, reason = "trigger_strategy_abort")
            is ScanEvent.LockAcquired -> BenchEvent.LockStateEvent(
                t = t,
                state = "Locked",
                afConverged = event.result.afConverged,
                aeLocked = event.result.aeLocked,
                awbLocked = event.result.awbLocked,
                durationMs = event.result.durationMs,
            )
            is ScanEvent.LockFailed -> BenchEvent.LockStateEvent(
                t = t,
                state = "Failed",
                reason = event.reason,
            )
            is ScanEvent.CaptureCompleted -> BenchEvent.CaptureCompleted(
                t = t,
                captureId = event.captureId,
                sourceMode = event.sourceMode.wire,
            )
            is ScanEvent.CaptureError -> BenchEvent.CaptureError(t = t, cause = event.cause)
            is ScanEvent.ConsensusReached -> BenchEvent.ConsensusReached(
                t = t,
                eurioId = event.eurioId,
                topK = event.topK.map { ArcfacePayload(it.className, it.similarity) },
            )
            is ScanEvent.ArchiveCompleted -> BenchEvent.ArchiveCompleted(t = t, captureId = event.captureId)
            is ScanEvent.ArchiveDiscarded -> BenchEvent.ArchiveDiscarded(t = t, reason = event.reason)
            ScanEvent.UserDismiss -> BenchEvent.UserAction(t = t, action = "dismiss")
            ScanEvent.UserConfirmAdd -> BenchEvent.UserAction(t = t, action = "confirm_add")
            ScanEvent.UserBack -> BenchEvent.UserAction(t = t, action = "back")
            // Pipeline-internal events that the state-transition log
            // already covers — no extra row needed.
            else -> null
        }
        if (mapped != null) rec.log(mapped)
    }

    private fun buildFrameAnalyzedEvent(
        result: ScanResult,
        t: Double,
    ): BenchEvent.FrameAnalyzed {
        val det = result.bestDetection
        val detection = det?.let {
            com.musubi.eurio.ml.bench.DetectionPayload(
                method = it.source.name,
                bbox = listOf(it.bbox.left, it.bbox.top, it.bbox.right, it.bbox.bottom),
                yoloConf = it.confidence,
            )
        }
        val s = result.frameScore
        val score = s?.let {
            com.musubi.eurio.ml.bench.ScorePayload(
                sharpness = it.sharpness,
                sharpnessRaw = it.sharpnessRaw,
                exposure = it.exposure,
                meanLuminance = it.meanLuminance,
                clippingRatio = it.clippingRatio,
                completeness = it.completeness,
                motion = it.motion,
                aggregate = it.aggregate,
                passes = com.musubi.eurio.ml.bench.PassesPayload(
                    sharpness = it.passes.sharpness,
                    exposure = it.passes.exposure,
                    completeness = it.passes.completeness,
                    motion = it.passes.motion,
                    all = it.passes.all,
                ),
            )
        }
        return BenchEvent.FrameAnalyzed(
            t = t,
            frameTsMs = result.timestamp,
            detection = detection,
            score = score,
            arcfaceTop3 = result.matches.take(3).map {
                ArcfacePayload(className = it.className, cos = it.similarity)
            },
            timingsMs = com.musubi.eurio.ml.bench.TimingsPayload(
                detect = result.yoloTotalMs,
                normalize = result.normalizeMs,
                arcface = result.rerankMs,
                score = result.scoreMs,
            ),
        )
    }

    // ── Chunk-6.2b — side-effect context stash ────────────────────────────
    // The reducer's `SideEffect.StartLock` / `StartCapture` carry intent
    // only — the camera-side context (region, lock options, locked
    // snapshot for metadata) lives on the ViewModel. We stash it here at
    // the legacy callsite (TriggerFire emit / Locked edge) so the
    // side-effect handler can pick it up.
    @Volatile private var pendingLockOptions: LockOptions? = null
    @Volatile private var lastLockedSnapshot: LockState.Locked? = null

    private fun applySideEffect(effect: SideEffect) {
        when (effect) {
            SideEffect.StartLock -> {
                val controller = _cameraLockController.value
                val options = pendingLockOptions
                pendingLockOptions = null
                if (controller != null && options != null) {
                    viewModelScope.launch { controller.lock(options) }
                } else {
                    Log.w(TAG, "StartLock skipped: controller=$controller options=$options")
                }
            }
            SideEffect.StartCapture -> {
                val locked = lastLockedSnapshot
                if (locked != null) {
                    startCapture(locked)
                } else {
                    Log.w(TAG, "StartCapture skipped: no locked snapshot stashed")
                }
            }
            SideEffect.ReleaseLock -> {
                _cameraLockController.value?.let { c ->
                    viewModelScope.launch { c.release() }
                }
            }
            SideEffect.DiscardPendingArchive -> {
                pendingCaptureId = null
                viewModelScope.launch { pendingArchiveBuffer.clear() }
            }
            SideEffect.ResetTrigger -> {
                coinAnalyzer.triggerStrategy.reset()
                coinAnalyzer.rollingBuffer.clear()
            }
            SideEffect.ScheduleNoDetectionWatcher -> Unit  // counter already running in onScanResult
            SideEffect.ScheduleAlreadyOwnedCheck ->
                timeoutScheduler.scheduleAlreadyOwnedAutoReturn()
            SideEffect.StartAbortFlashTimer ->
                timeoutScheduler.scheduleAbortFlashElapsed()
            is SideEffect.StartTimeout ->
                timeoutScheduler.start(_scanMachineState.value, effect.durationMs)
            SideEffect.CancelTimeout -> timeoutScheduler.cancel()
            is SideEffect.ConfirmPossession -> {
                // Skip the vault write when the user confirmed an
                // already-owned card (re-scan acknowledged, no double
                // upsert / streak bump). `alreadyOwned` lives on the UI
                // projection — the domain reducer doesn't model
                // possession, so the legacy `_state` is consulted as the
                // source of truth here.
                val legacy = _state.value as? ScanUiState.Accepted
                if (legacy?.alreadyOwned == true) return
                viewModelScope.launch {
                    vaultRepository.confirmPossession(effect.eurioId, effect.captureId)
                    streakRepository.onScanAccepted()
                    checkSetCompletions(effect.eurioId)
                }
            }
        }
    }

    private fun startCapture(locked: LockState.Locked) {
        val capture = imageCapture
        if (capture == null) {
            startCaptureYuvFallback(locked)
            return
        }
        val captureId = UUID.randomUUID().toString()
        pendingCaptureId = captureId
        val rotationDegrees = capture.targetRotation * 90
        val frameScoreSnapshot = _hudState.value.bestFrameScore
            ?: _hudState.value.lastFrameScore
            ?: com.musubi.eurio.domain.scan.quality.FrameScore.Failed
        val timingsSnapshot = _hudState.value.timings
        val arcfaceSnapshot = _hudState.value.arcfaceTop3
        val triggerMode = debugConfig.value.triggerMode.name
        val triggerFireReason = _hudState.value.triggerFireReason
        val detectionBboxSnapshot = lastFrameDetectionBbox
        val detectionConfidenceSnapshot = lastFrameDetectionConfidence
        val detectionSourceSnapshot = lastFrameDetectionSource

        capture.takePicture(
            captureExecutor,
            object : ImageCapture.OnImageCapturedCallback() {
                override fun onCaptureSuccess(image: ImageProxy) {
                    try {
                        val info = image.imageInfo
                        val jpeg = JpegPipeline.process(
                            image,
                            rotationDegrees = info.rotationDegrees,
                            longSideMax = JpegPipeline.DEFAULT_LONG_SIDE,
                            quality = JpegPipeline.DEFAULT_QUALITY,
                        )
                        val metadata = CaptureMetadata(
                            frameScore = frameScoreSnapshot,
                            detectionBbox = detectionBboxSnapshot,
                            detectionConfidence = detectionConfidenceSnapshot,
                            detectionSource = detectionSourceSnapshot,
                            triggerMode = triggerMode,
                            triggerFireReason = triggerFireReason,
                            lockResult = locked.toSnapshot(),
                            arcfaceTop3 = arcfaceSnapshot,
                            sourceMode = SourceMode.IMAGE_CAPTURE_FULL,
                            timings = timingsSnapshot,
                        )
                        viewModelScope.launch {
                            pendingArchiveBuffer.set(captureId, jpeg, frameScoreSnapshot, metadata)
                            Log.d(TAG, "JPEG $captureId staged (${jpeg.size}B), rot=$rotationDegrees")
                            emitScanEvent(
                                ScanEvent.CaptureCompleted(
                                    captureId = captureId,
                                    sourceMode = SourceMode.IMAGE_CAPTURE_FULL,
                                )
                            )
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "JPEG pipeline failed for $captureId", e)
                        emitScanEvent(ScanEvent.CaptureError(e.message ?: e.javaClass.simpleName))
                    } finally {
                        image.close()
                    }
                }

                override fun onError(exception: ImageCaptureException) {
                    Log.e(TAG, "takePicture failed for $captureId", exception)
                    emitScanEvent(ScanEvent.CaptureError(exception.message ?: "image_capture_error"))
                }
            },
        )
    }

    private fun startCaptureYuvFallback(locked: LockState.Locked) {
        val sourceRef = coinAnalyzer.lastAnalyzedFullResBitmap
        val bitmap = sourceRef?.get()
        if (bitmap == null || bitmap.isRecycled) {
            Log.d(TAG, "lock acquired but YUV fallback has no live bitmap reference")
            return
        }
        val captureId = UUID.randomUUID().toString()
        pendingCaptureId = captureId
        val frameScoreSnapshot = _hudState.value.bestFrameScore
            ?: _hudState.value.lastFrameScore
            ?: com.musubi.eurio.domain.scan.quality.FrameScore.Failed
        val timingsSnapshot = _hudState.value.timings
        val arcfaceSnapshot = _hudState.value.arcfaceTop3
        val triggerMode = debugConfig.value.triggerMode.name
        val triggerFireReason = _hudState.value.triggerFireReason

        viewModelScope.launch(kotlinx.coroutines.Dispatchers.Default) {
            try {
                val jpeg = JpegPipeline.fromBitmap(
                    bitmap,
                    rotationDegrees = 0,
                    longSideMax = JpegPipeline.DEFAULT_LONG_SIDE,
                    quality = JpegPipeline.DEFAULT_QUALITY,
                )
                val metadata = CaptureMetadata(
                    frameScore = frameScoreSnapshot,
                    detectionBbox = lastFrameDetectionBbox,
                    detectionConfidence = lastFrameDetectionConfidence,
                    detectionSource = lastFrameDetectionSource,
                    triggerMode = triggerMode,
                    triggerFireReason = triggerFireReason,
                    lockResult = locked.toSnapshot(),
                    arcfaceTop3 = arcfaceSnapshot,
                    sourceMode = SourceMode.YUV_PREVIEW_FALLBACK,
                    timings = timingsSnapshot,
                )
                pendingArchiveBuffer.set(captureId, jpeg, frameScoreSnapshot, metadata)
                Log.d(TAG, "YUV fallback JPEG $captureId staged (${jpeg.size}B)")
                emitScanEvent(
                    ScanEvent.CaptureCompleted(
                        captureId = captureId,
                        sourceMode = SourceMode.YUV_PREVIEW_FALLBACK,
                    )
                )
            } catch (e: Exception) {
                Log.e(TAG, "YUV fallback failed for $captureId", e)
                emitScanEvent(ScanEvent.CaptureError(e.message ?: e.javaClass.simpleName))
            }
        }
    }

    init {
        // Push the initial policy + keep it in sync with debug-bar sliders.
        // In release this flow emits a single defaults snapshot (chunk-1),
        // so the analyzer reads frozen ScoringPolicy defaults.
        coinAnalyzer.scoringPolicy = ScoringPolicy.fromDebugConfig(debugConfig.value)
        coinAnalyzer.triggerStrategy = TriggerStrategyFactory.create(debugConfig.value)
        coinAnalyzer.rollingBuffer.setCapacity(debugConfig.value.burstSize.coerceIn(1, 20))

        viewModelScope.launch {
            var lastConfig: DebugScanConfig? = null
            var lastRecordEnabled = false
            debugConfig.collect { config ->
                coinAnalyzer.scoringPolicy = ScoringPolicy.fromDebugConfig(config)
                // Fresh trigger instance on every config change (cf. P3): new
                // strategy class on mode switch, otherwise the same class
                // with parameters re-baked. Either way state resets cleanly.
                coinAnalyzer.triggerStrategy = TriggerStrategyFactory.create(config)
                coinAnalyzer.rollingBuffer.setCapacity(config.burstSize.coerceIn(1, 20))

                // Chunk-7a — bench recorder lifecycle + config snapshot.
                // Toggling `recordEnabled` starts/stops a session; any other
                // edit during an active session re-emits a `config_snapshot`
                // so the replay is reproducible against the exact knobs in
                // effect at each moment.
                val rec = benchRecorder
                if (rec != null) {
                    when {
                        config.recordEnabled && !lastRecordEnabled -> rec.start(
                            config = config,
                            deviceInfo = buildDeviceInfo(),
                        )
                        !config.recordEnabled && lastRecordEnabled -> rec.stop()
                        config.recordEnabled && lastConfig != null && lastConfig != config -> {
                            rec.log(
                                BenchEvent.ConfigSnapshot(
                                    t = rec.nowSeconds(),
                                    config = config.toPayload(),
                                )
                            )
                        }
                    }
                }
                lastRecordEnabled = config.recordEnabled
                lastConfig = config
            }
        }

        // Mirror lockState into the HUD payload so the FiredRow can read it
        // off the same ScanHudState snapshot (avoids two collectors in HUD).
        // Chunk-6.2b — the actual capture trigger is now driven by the
        // reducer's `StartCapture` side effect (fired from
        // `LockAcquired → Capturing`), not from this collector. We still
        // stash `[lastLockedSnapshot]` here on the Idle/Acquiring → Locked
        // edge so the side-effect handler has the lock context it needs.
        viewModelScope.launch {
            var lastPhase: LockState? = null
            lockState.collect { ls ->
                _hudState.update { it.copy(lockState = ls) }
                if (ls is LockState.Locked && lastPhase !is LockState.Locked) {
                    lastLockedSnapshot = ls
                }
                lastPhase = ls
            }
        }

        viewModelScope.launch {
            _state.collect { st ->
                val label = when (st) {
                    is ScanUiState.Idle -> "Idle"
                    is ScanUiState.Detecting -> "Detecting"
                    is ScanUiState.Accepted -> "Accepted"
                    is ScanUiState.NotIdentified -> "NotIdentified"
                    is ScanUiState.Failure -> "Failure"
                }
                _hudState.update { it.copy(machineState = label) }
            }
        }

        // Chunk-6.2a — derive shadow ScanEvents from the lock controller
        // and feed them into the reducer. We emit on edges so the same
        // `LockState.Locked` doesn't fire LockAcquired twice.
        viewModelScope.launch {
            var prev: LockState = LockState.Idle
            lockState.collect { ls ->
                if (ls is LockState.Locked && prev !is LockState.Locked) {
                    ls.toSnapshot()?.let { emitScanEvent(ScanEvent.LockAcquired(it)) }
                } else if (ls is LockState.Failed && prev !is LockState.Failed) {
                    emitScanEvent(ScanEvent.LockFailed(ls.reason))
                }
                prev = ls
            }
        }

        // Chunk-6.2b — reducer pump. Reducer is now the source of truth
        // for actuation: every transition's side effects drive the camera,
        // capture, archive and vault writes. The legacy `_state` is still
        // updated by the existing call sites (Idle/Detecting/Accepted) ;
        // the migration to drive `_state` from `_scanMachineState` is
        // 6.2c.
        viewModelScope.launch {
            _scanEvents.collect { event ->
                val current = _scanMachineState.value
                val result = ScanReducer.reduce(current, event, System.nanoTime())
                if (result.nextState !== current) {
                    Log.d(
                        TAG,
                        "${current::class.simpleName} --$event--> " +
                            "${result.nextState::class.simpleName} fx=${result.sideEffects}",
                    )
                    _scanMachineState.value = result.nextState
                    benchRecorder?.takeIf { it.isActive }?.let { rec ->
                        rec.log(
                            BenchEvent.StateTransition(
                                t = rec.nowSeconds(),
                                from = current::class.simpleName ?: "?",
                                to = result.nextState::class.simpleName ?: "?",
                                viaEvent = event::class.simpleName ?: "?",
                            )
                        )
                    }
                }
                forwardEventToBench(event)
                result.sideEffects.forEach { applySideEffect(it) }
            }
        }

        // Chunk-6.2a — mirror the shadow state label into the HUD so the
        // dev overlay can visually compare it to the legacy `machineState`.
        viewModelScope.launch {
            _scanMachineState.collect { st ->
                _hudState.update { it.copy(shadowState = st::class.simpleName ?: "?") }
            }
        }
    }

    /**
     * Selects the best frame after a trigger fires. Shared across calls — it
     * has no state of its own, just the D8 logic.
     */
    private val bestFrameSelector = BestFrameSelector()

    private var cooldownClass: String? = null
    private var cooldownUntilMs: Long = 0L
    private var consecutiveNoDetection: Int = 0
    private var debugTapCount: Int = 0
    private var lastDebugTapMs: Long = 0L
    private var autoReturnJob: Job? = null
    private var lastFps = 0f
    private var lastFrameMs = 0L

    // ─────────────────────────────────────────────────────────────────────
    // Camera frame pipeline
    // ─────────────────────────────────────────────────────────────────────

    fun onFrame(image: ImageProxy) {
        coinAnalyzer.analyze(image)
    }

    // ── Best-frame capture chunk-5c — ImageCapture wiring ────────────────
    // Held weakly here so the controller and the snapshot path share the
    // same Camera lifecycle. Null when the 3-usecase bind failed and we
    // fell back to 2-usecase (YUV path documented in chunk-5d).
    @Volatile
    private var imageCapture: ImageCapture? = null

    // Dedicated executor for ImageCapture callbacks — keeps the file
    // decode/rotation/resize off the main thread without competing with
    // the analyzer's own executor.
    private val captureExecutor = Executors.newSingleThreadExecutor()

    /**
     * Tracks the captureId of the JPEG currently parked in
     * [pendingArchiveBuffer] for the active scan run. Cleared on
     * `returnToIdle` so a stale id can't leak into the next run.
     */
    @Volatile
    private var pendingCaptureId: String? = null

    /**
     * Receive the `Camera` produced by `bindToLifecycle` (chunk-4). Wraps it
     * in a [CameraLockController] so the best-frame trigger can request
     * AE/AF/AWB lock. The optional [imageCapture] (chunk-5c) feeds
     * `takePicture` once a lock acquires. Safe to call multiple times — a
     * fresh controller replaces any previous one; the prior controller's
     * locks are abandoned because the underlying CameraX session was
     * rebound.
     */
    fun attachCamera(camera: Camera, imageCapture: ImageCapture? = null) {
        _cameraLockController.value = CameraLockController(camera)
        this.imageCapture = imageCapture
        Log.d(
            TAG,
            "camera attached, lock controller ready (imageCapture=${imageCapture != null})",
        )
    }

    /**
     * Release any active lock and drop the controller reference. Called from
     * `CameraPreview`'s DisposableEffect.onDispose when the scan screen
     * leaves composition.
     */
    fun detachCamera() {
        val controller = _cameraLockController.value
        if (controller != null) {
            viewModelScope.launch { controller.release() }
            _cameraLockController.value = null
        }
        imageCapture = null
        viewModelScope.launch { pendingArchiveBuffer.clear() }
        pendingCaptureId = null
        emitScanEvent(ScanEvent.ScreenPaused)
        Log.d(TAG, "camera detached, lock controller released")
    }

    fun onScanResult(result: ScanResult) {
        val topClass = result.matches.firstOrNull()?.className
        val topSimilarity = result.matches.firstOrNull()?.similarity ?: 0f
        val now = System.currentTimeMillis()

        // FPS tracking for debug
        if (lastFrameMs > 0) {
            val delta = now - lastFrameMs
            if (delta > 0) lastFps = 1000f / delta
        }
        lastFrameMs = now

        Log.d(TAG, "result: detected=${result.detected} matches=${result.matches.size} " +
                "top=${topClass?.take(20)} sim=${String.format("%.3f", topSimilarity)}")

        // Populate debug data for the overlay
        updateDebugData(result)

        // Best-frame capture (chunk-2): publish the scored frame + arcface
        // top-3 + per-stage timings into the HUD flow. machineState is mirrored
        // separately from the _state collector above.
        _hudState.update { current ->
            current.copy(
                lastFrameScore = result.frameScore,
                arcfaceTop3 = result.matches.take(3).map {
                    ArcfaceMatch(className = it.className, similarity = it.similarity)
                },
                timings = TimingBreakdown(
                    detectMs = result.yoloTotalMs,
                    normalizeMs = result.normalizeMs,
                    arcfaceMs = result.rerankMs,
                    scoreMs = result.scoreMs,
                ),
                bufferSize = result.bufferSize,
                bufferCapacity = result.bufferCapacity,
            )
        }

        // Chunk-7a — bench frame_analyzed event. Skipped on undetected
        // frames in Idle to keep the JSONL focused on signal.
        benchRecorder?.takeIf { it.isActive && (result.detected || result.frameScore != null) }?.let { rec ->
            rec.log(buildFrameAnalyzedEvent(result, rec.nowSeconds()))
        }

        if (_recordMode.value) {
            _recordedFrameCount.value = coinAnalyzer.recordedFrameCount
        }

        val current = _state.value
        if (current is ScanUiState.Accepted) return

        try {
            // Track consecutive frames without detection → return to Idle silently
            if (!result.detected) {
                consecutiveNoDetection++
                if (current is ScanUiState.Detecting && consecutiveNoDetection >= IDLE_RETURN_THRESHOLD) {
                    Log.d(TAG, "no detection for $IDLE_RETURN_THRESHOLD frames, returning to Idle")
                    emitScanEvent(ScanEvent.NoDetectionStreak)
                    returnToIdle(cooldownClass = null)
                }
                return
            }
            consecutiveNoDetection = 0

            val isNewConsensus = consensus.push(topClass)

            // Transition to Detecting on the first frame with a candidate
            if (current is ScanUiState.Idle && result.detected) {
                _state.value = ScanUiState.Detecting
                emitScanEvent(ScanEvent.FirstDetection)
            }

            // Consensus reached → accept (unless in cooldown)
            if (isNewConsensus) {
                val locked = consensus.consensus ?: return
                if (locked == cooldownClass && now < cooldownUntilMs) {
                    Log.d(TAG, "consensus on $locked but in cooldown, ignoring")
                    return
                }
                Log.d(TAG, "consensus reached: $locked (sim=$topSimilarity)")
                emitAccepted(locked, topSimilarity)
            }
        } finally {
            // Best-frame capture (chunk-3b): every continuous-mode frame that
            // hasn't terminated in Accepted feeds the active trigger strategy.
            // The `finally` keeps the observation at a single call site even
            // when the body returns early (cooldown, no detection, …) so the
            // trigger sees the full frame sequence and not just the
            // happy-path frames.
            if (_state.value !is ScanUiState.Accepted) {
                observeTrigger(result)
            }
        }
    }

    /**
     * Build a [FrameContext] from the latest analyzer outputs and let the
     * active strategy observe it. Fire / Abort events are handled inline;
     * `null` (still observing) is the common case.
     */
    private fun observeTrigger(result: ScanResult) {
        val strategy = coinAnalyzer.triggerStrategy
        val snapshot = coinAnalyzer.rollingBuffer.snapshot()
        val primaryBbox = result.bestDetection?.let { BboxF.fromRectF(it.bbox) }
        // Chunk-5c — stash for the next takePicture metadata stamp.
        lastFrameDetectionBbox = primaryBbox
        lastFrameDetectionConfidence = result.bestDetection?.confidence
        lastFrameDetectionSource = result.bestDetection?.source
        val context = FrameContext(
            sequenceId = snapshot.lastOrNull()?.sequenceId ?: -1,
            buffer = snapshot,
            primaryBbox = primaryBbox,
            primaryConfidence = result.bestDetection?.confidence,
            primarySource = result.bestDetection?.source,
            arcfaceTop1 = result.matches.firstOrNull(),
            consensusLockedClass = consensus.consensus,
        )
        when (val event = strategy.observe(context)) {
            is TriggerEvent.Fire -> handleFire(event, result.frameWidth, result.frameHeight)
            TriggerEvent.Abort -> handleAbort(result, context)
            null -> Unit
        }
    }

    private fun handleFire(event: TriggerEvent.Fire, frameWidth: Int, frameHeight: Int) {
        when (val selection = bestFrameSelector.select(event.bufferSnapshot)) {
            is SelectionResult.Best -> {
                Log.d(
                    TAG,
                    "trigger fired: ${event.reason} → ${selection.reason} " +
                        "idx=${selection.indexInSnapshot} agg=${"%.2f".format(selection.frame.score.aggregate)}",
                )
                _hudState.update {
                    it.copy(
                        triggerFireReason = event.reason,
                        bestSelectionReason = selection.reason.short(),
                        bestFrameIndex = selection.indexInSnapshot,
                        bestFrameScore = selection.frame.score,
                    )
                }
                // Chunk-6.2b — AE/AF/AWB lock is now driven by the
                // reducer's `SideEffect.StartLock` (fired from `TriggerFire
                // → Locking`). We stash the lock options here because the
                // reducer doesn't carry the bbox / frame dimensions ; the
                // side-effect handler picks them up and calls
                // `CameraLockController.lock(options)`.
                if (frameWidth > 0 && frameHeight > 0) {
                    val region = selection.frame.bbox.toMeteringRect(frameWidth, frameHeight)
                    pendingLockOptions = LockOptions.fromDebugConfig(debugConfig.value, region)
                }
                emitScanEvent(ScanEvent.TriggerFire(event.reason))
            }
            SelectionResult.Empty -> {
                Log.d(TAG, "trigger fired but buffer was empty: ${event.reason}")
                _hudState.update {
                    it.copy(
                        triggerFireReason = event.reason,
                        bestSelectionReason = "empty_buffer",
                        bestFrameIndex = null,
                        bestFrameScore = null,
                    )
                }
            }
        }
        coinAnalyzer.triggerStrategy.reset()
    }

    private fun handleAbort(result: ScanResult, context: FrameContext) {
        Log.d(TAG, "trigger abort")
        _hudState.update {
            it.copy(triggerFireReason = "aborted", bestSelectionReason = null)
        }
        // Chunk-4b — push a one-shot abort event so the overlay can flash red.
        // Use the live primary bbox first, fall back to the last buffered
        // frame's bbox (case: motion right after fire, current frame has no
        // detection but the buffered ones do).
        val abortBbox = context.primaryBbox ?: context.buffer.lastOrNull()?.bbox
        _abortEvents.tryEmit(
            AbortEvent(
                timestampMs = System.currentTimeMillis(),
                reason = "motion",
                lastBbox = abortBbox,
                frameWidth = result.frameWidth,
                frameHeight = result.frameHeight,
            )
        )
        // Chunk-4 — release any active lock so the camera resumes hunting.
        _cameraLockController.value?.let { controller ->
            viewModelScope.launch { controller.release() }
        }
        coinAnalyzer.triggerStrategy.reset()
        emitScanEvent(ScanEvent.TriggerAbort)
    }

    /**
     * Convert a frame-pixel-space bbox to a 0..1 normalized [MeteringRect] in
     * SurfaceOrientedMeteringPointFactory space. Falls back to a centered
     * 30 % box if the bbox is degenerate (defensive — should not happen since
     * the best frame always carries a real detection).
     */
    private fun BboxF.toMeteringRect(frameWidth: Int, frameHeight: Int): MeteringRect {
        if (frameWidth <= 0 || frameHeight <= 0) {
            return MeteringRect(0.35f, 0.35f, 0.65f, 0.65f)
        }
        val fw = frameWidth.toFloat()
        val fh = frameHeight.toFloat()
        return MeteringRect(
            left = (left / fw).coerceIn(0f, 1f),
            top = (top / fh).coerceIn(0f, 1f),
            right = (right / fw).coerceIn(0f, 1f),
            bottom = (bottom / fh).coerceIn(0f, 1f),
        )
    }

    private fun SelectionReason.short(): String = when (this) {
        SelectionReason.PASSED_ALL_GATES -> "passed_all_gates"
        SelectionReason.BEST_AGGREGATE_FALLBACK -> "best_aggregate_fallback"
    }

    private fun updateDebugData(result: ScanResult) {
        val bbox = result.bestDetection?.let { det ->
            DebugViewData.BboxInfo(
                left = det.bbox.left,
                top = det.bbox.top,
                right = det.bbox.right,
                bottom = det.bbox.bottom,
                frameWidth = result.frameWidth,
                frameHeight = result.frameHeight,
                label = "${det.source.name} ${String.format("%.0f%%", det.confidence * 100)}",
            )
        }

        _debugData.value = DebugViewData(
            bbox = bbox,
            top5 = result.matches.take(5).map {
                DebugViewData.DebugMatch(it.className.take(24), it.similarity)
            },
            deltaTop1Top2 = if (result.matches.size >= 2) {
                result.matches[0].similarity - result.matches[1].similarity
            } else 0f,
            latencies = DebugViewData.Latencies(
                detMs = result.yoloTotalMs,
                embMs = result.identificationInferenceMs,
                knnMs = result.rerankMs,
                totalMs = result.totalInferenceMs,
                fps = lastFps,
            ),
            runtime = DebugViewData.Runtime(
                model = if (coinAnalyzer.useEmbeddings) "arcface" else "class",
                embeddings = result.matches.size,
                hash = result.rerankDecisionReason.take(30),
                camera = result.cropSize,
                deviceTempC = 0,
            ),
            histogram = DebugViewData.Histogram(
                okCount = if (consensus.consensus != null) 1 else 0,
                failCount = if (result.rerankRejectedAll) 1 else 0,
                skipCount = if (!result.detected) 1 else 0,
                window = 5,
            ),
        )
    }

    private fun emitAccepted(classifierName: String, confidence: Float) {
        viewModelScope.launch {
            val coin = coinRepository.resolveByClassifierName(classifierName) ?: run {
                Log.w(TAG, "accepted $classifierName has no catalog entry, staying in Detecting")
                return@launch
            }
            val alreadyOwned = vaultRepository.containsCoin(coin.eurioId)

            // Chunk-6.2a — fire the domain event first so the shadow machine
            // can jump to Accepted alongside the legacy state. The archive
            // step that follows is the same `ArchiveCompleted` event that
            // 6.2b will route through the reducer.
            emitScanEvent(
                ScanEvent.ConsensusReached(
                    eurioId = coin.eurioId,
                    topK = _hudState.value.arcfaceTop3,
                )
            )

            // Chunk-5c — pair the consensus with any pending archive: if a
            // JPEG produced by `ImageCapture.takePicture` is still alive in
            // the buffer (lock acquired moments ago), persist it now under
            // this `eurioId`. The archive write is independent of the user's
            // upcoming "Ajouter au coffre" decision (D24).
            val archivedCaptureId = archivePendingIfAny(coin.eurioId)

            _state.value = ScanUiState.Accepted(
                coin = coin,
                confidence = confidence,
                alreadyOwned = alreadyOwned,
                captureId = archivedCaptureId,
            )

            if (alreadyOwned) {
                autoReturnJob?.cancel()
                autoReturnJob = viewModelScope.launch {
                    delay(ALREADY_OWNED_TOAST_MS)
                    returnToIdle(cooldownClass = classifierName)
                }
            }
        }
    }

    /**
     * If a JPEG is pending and matches the resolved consensus, archive it
     * (insert `coin_captures` + write file). Returns the captureId on
     * success, null otherwise (no pending / expired / repo unavailable).
     */
    private suspend fun archivePendingIfAny(eurioId: String): String? {
        val repo = vaultCaptureRepository ?: return null
        val pending = pendingArchiveBuffer.consume(eurioId) ?: run {
            emitScanEvent(ScanEvent.ArchiveDiscarded("no_pending_or_expired"))
            return null
        }
        return when (
            val result = repo.archive(
                eurioId = eurioId,
                captureId = pending.captureId,
                jpegBytes = pending.jpegBytes,
                score = pending.score,
                metadata = pending.metadata,
            )
        ) {
            is VaultCaptureRepository.ArchiveResult.Success -> {
                Log.d(
                    TAG,
                    "archive ok: ${result.captureId} eurioId=$eurioId " +
                        "isPossessed=${result.isPossessed} promoted=${result.promoted}",
                )
                pendingCaptureId = null
                emitScanEvent(ScanEvent.ArchiveCompleted(result.captureId))
                // Chunk-5d — fire the D17 snackbar exclusively on the
                // promotion-by-quality branch (auto-fill of a NULL primary
                // is silent — see VaultCaptureRepository.archive).
                if (result.promoted && result.previousPrimaryId != null) {
                    _snackbarEvents.tryEmit(
                        ScanSnackbarEvent.PrimaryPromoted(
                            eurioId = eurioId,
                            newPrimaryId = result.captureId,
                            previousPrimaryId = result.previousPrimaryId,
                        )
                    )
                }
                result.captureId
            }
            is VaultCaptureRepository.ArchiveResult.Failure -> {
                Log.w(TAG, "archive failed: ${result.cause}")
                emitScanEvent(ScanEvent.ArchiveDiscarded("archive_failed:${result.cause}"))
                null
            }
        }
    }

    // Per-frame detection snapshot kept for the metadata stamp at lock time.
    @Volatile private var lastFrameDetectionBbox: com.musubi.eurio.ml.trigger.BboxF? = null
    @Volatile private var lastFrameDetectionConfidence: Float? = null
    @Volatile private var lastFrameDetectionSource: com.musubi.eurio.ml.DetectionSource? = null

    // ─────────────────────────────────────────────────────────────────────
    // User actions from the UI
    // ─────────────────────────────────────────────────────────────────────

    /**
     * D17 "Annuler" path — restore the previous primary capture on the
     * coin that was just promoted by [archivePendingIfAny]. No-op if
     * the repository is unavailable (test path).
     */
    fun onRevertPromotion(event: ScanSnackbarEvent.PrimaryPromoted) {
        val repo = vaultCaptureRepository ?: return
        viewModelScope.launch {
            repo.revertPrimary(event.eurioId, event.previousPrimaryId)
            Log.d(TAG, "primary reverted: ${event.eurioId} → ${event.previousPrimaryId}")
        }
    }

    fun onAddToVault() {
        val current = _state.value as? ScanUiState.Accepted ?: return
        // Chunk-6.2b — confirmPossession + streak + checkSetCompletions
        // are now driven by the reducer's `SideEffect.ConfirmPossession`
        // (gated on !alreadyOwned in `applySideEffect`). The legacy
        // returnToIdle still handles cleanup of the legacy `_state` and
        // cooldown bookkeeping until 6.2c collapses both flows.
        emitScanEvent(ScanEvent.UserConfirmAdd)
        returnToIdle(cooldownClass = current.coin.eurioId)
    }

    fun onDismissCard() {
        val cooldownId = when (val s = _state.value) {
            is ScanUiState.Accepted -> s.coin.eurioId
            is ScanUiState.Failure -> null
            else -> null
        }
        emitScanEvent(ScanEvent.UserDismiss)
        returnToIdle(cooldownClass = cooldownId)
    }

    fun onVersionBadgeTap() {
        val now = System.currentTimeMillis()
        if (now - lastDebugTapMs > DEBUG_TAP_WINDOW_MS) {
            debugTapCount = 0
        }
        debugTapCount++
        lastDebugTapMs = now
        if (debugTapCount >= DEBUG_TAP_COUNT) {
            debugTapCount = 0
            _debugMode.value = !_debugMode.value
            Log.d(TAG, "debug mode toggled: ${_debugMode.value}")
        }
    }

    // Capture cohort / photo / carousel : déplacés vers features/dev/* (refacto 2026-05-28).

    /**
     * Toggle the continuous record mode. Starting a session creates a fresh
     * sub-directory under the debug root and resets the frame counter; stopping
     * just flips the flag (files stay on disk for `go-task android:pull-debug`).
     */
    fun onRecordToggle() {
        if (_recordMode.value) {
            coinAnalyzer.recordMode = false
            _recordMode.value = false
            Log.d(TAG, "record stopped at ${coinAnalyzer.recordedFrameCount} frames")
            return
        }
        val root = coinAnalyzer.debugRootDir
        if (root == null) {
            Log.w(TAG, "cannot start record: debugRootDir not configured")
            return
        }
        val ts = java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.US)
            .format(java.util.Date())
        val sessionDir = java.io.File(root, "session_$ts").apply { mkdirs() }
        coinAnalyzer.resetRecordCounter()
        coinAnalyzer.recordSessionDir = sessionDir
        coinAnalyzer.recordMode = true
        _recordedFrameCount.value = 0
        _recordMode.value = true
        Log.d(TAG, "record started: ${sessionDir.absolutePath}")
    }

    fun setDebugMode(enabled: Boolean) {
        _debugMode.value = enabled
    }

    // ─────────────────────────────────────────────────────────────────────
    // Internals
    // ─────────────────────────────────────────────────────────────────────

    private fun returnToIdle(cooldownClass: String?) {
        autoReturnJob?.cancel()
        autoReturnJob = null
        consensus.reset()
        consecutiveNoDetection = 0
        // Chunk-5c — release any JPEG still parked. If a fire happened
        // but the consensus never caught up (anti-objectif §6), the bytes
        // are dropped here when the scan run terminates.
        pendingCaptureId = null
        viewModelScope.launch { pendingArchiveBuffer.clear() }
        if (cooldownClass != null) {
            this.cooldownClass = cooldownClass
            cooldownUntilMs = System.currentTimeMillis() + DISMISS_COOLDOWN_MS
        }
        // Best-frame capture (chunk-3b): each scan run owns its trigger state.
        // Wipe the strategy + buffer so the next run starts cold; recycling
        // the bitmaps avoids cumulative RAM growth across long sessions.
        coinAnalyzer.triggerStrategy.reset()
        coinAnalyzer.rollingBuffer.clear()
        // Chunk-4 — release any active AE/AF/AWB lock so the camera resumes
        // continuous AF/AE between scan runs.
        _cameraLockController.value?.let { controller ->
            viewModelScope.launch { controller.release() }
        }
        _hudState.update {
            it.copy(
                triggerFireReason = null,
                bestSelectionReason = null,
                bestFrameIndex = null,
                bestFrameScore = null,
            )
        }
        _state.value = ScanUiState.Idle
    }

    private suspend fun checkSetCompletions(eurioId: String) {
        val repo = setRepository ?: return
        val impactedSets = repo.findSetsContaining(eurioId)
        for (set in impactedSets) {
            if (set.isComplete) {
                val completion = repo.checkCompletion(set.id)
                if (completion != null) {
                    repo.markCompleted(set.id, completion.completedAt)
                    onAppEvent?.invoke(
                        com.musubi.eurio.domain.AppEvent.SetCompleted(completion.nameFr)
                    )
                    Log.d(TAG, "Set completed: ${completion.nameFr}")
                }
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        autoReturnJob?.cancel()
        captureExecutor.shutdown()
    }
}
