package com.musubi.eurio.features.scan

import android.util.Log
import androidx.camera.core.ImageProxy
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.BuildConfig
import com.musubi.eurio.data.repository.CoinRepository
import com.musubi.eurio.data.repository.SetRepository
import com.musubi.eurio.data.repository.StreakRepository
import com.musubi.eurio.data.repository.VaultRepository
import com.musubi.eurio.features.scan.components.DebugViewData
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.ScanResult
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
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
) : ViewModel() {

    companion object {
        private const val TAG = "ScanVM"
        const val DISMISS_COOLDOWN_MS = 3_000L
        const val ALREADY_OWNED_TOAST_MS = 2_000L
        const val DEBUG_TAP_COUNT = 7
        const val DEBUG_TAP_WINDOW_MS = 2_000L
        private const val IDLE_RETURN_THRESHOLD = 4
    }

    private val _state = MutableStateFlow<ScanState>(ScanState.Idle)
    val state: StateFlow<ScanState> = _state.asStateFlow()

    fun forceState(state: ScanState) {
        if (!BuildConfig.IS_QA) return
        Log.d(TAG, "[QA] Forcing scan state: $state")
        _state.value = state
    }

    private val _debugMode = MutableStateFlow(false)
    val debugMode: StateFlow<Boolean> = _debugMode.asStateFlow()

    // ── Debug carousel mode (Phase 4) ───────────────────────────────────────
    // When ON (debugMode required), the camera/ML pipeline is bypassed and the
    // user cycles through every 2 € coin via prev/next buttons. Each step
    // emits ScanState.Accepted through the same path as a real detection so
    // the UI/animation stays identical between fake and real flows.
    private val _carouselMode = MutableStateFlow(false)
    val carouselMode: StateFlow<Boolean> = _carouselMode.asStateFlow()

    private val _carouselCurrent = MutableStateFlow<com.musubi.eurio.data.repository.CoinViewData?>(null)
    val carouselCurrent: StateFlow<com.musubi.eurio.data.repository.CoinViewData?> = _carouselCurrent.asStateFlow()

    private var carouselCoins: List<com.musubi.eurio.data.repository.CoinViewData> = emptyList()
    private var carouselIndex: Int = 0

    private val _debugData = MutableStateFlow(DebugViewData())
    val debugData: StateFlow<DebugViewData> = _debugData.asStateFlow()

    // Continuous record mode (debug bar). Captures full pipeline state per frame
    // into a session directory under the analyzer's debugRootDir.
    private val _recordMode = MutableStateFlow(false)
    val recordMode: StateFlow<Boolean> = _recordMode.asStateFlow()

    private val _recordedFrameCount = MutableStateFlow(0)
    val recordedFrameCount: StateFlow<Int> = _recordedFrameCount.asStateFlow()

    // Photo mode (debug bar): pauses continuous scan, shows a guide circle,
    // user taps SNAP → one-shot analyze on a circular-masked centered crop.
    private val _photoMode = MutableStateFlow(false)
    val photoMode: StateFlow<Boolean> = _photoMode.asStateFlow()

    /** Latest photo snap result — set after each snap, cleared on snap-again. */
    private val _photoSnap = MutableStateFlow<PhotoSnap?>(null)
    val photoSnap: StateFlow<PhotoSnap?> = _photoSnap.asStateFlow()

    /**
     * Live Hough probe state for the on-screen ring color. True when the
     * analyzer's last cheap probe found a centered circle (= a snap taken
     * now would normalize successfully); false otherwise. Updated at the
     * analyzer's [com.musubi.eurio.ml.CoinAnalyzer.photoLiveDetectIntervalMs]
     * cadence (5 fps default). Reset to false when leaving photo mode.
     */
    private val _photoLiveCircleFound = MutableStateFlow(false)
    val photoLiveCircleFound: StateFlow<Boolean> = _photoLiveCircleFound.asStateFlow()

    /**
     * Outcome of one photo-mode snap. [cropPath] is null when normalization
     * (Hough) failed — the layer renders a failure card in that case
     * (no ArcFace ran, [matches] is empty, [decisionReason] carries the
     * "NORMALIZE FAILED: …" reason from CoinAnalyzer).
     */
    data class PhotoSnap(
        val cropPath: String?,
        val accepted: Boolean,
        val decisionReason: String,
        val top1: Float,
        val top2: Float,
        val matches: List<com.musubi.eurio.ml.CoinMatch>,
        val cropSize: Int,
    )

    // ── Capture mode (Phase 0 golden-set) ──────────────────────────────────
    // Drives the user through CaptureProtocol.coins × CaptureProtocol.steps,
    // writing each snap to eval_real/<eurio_id>/<step_id>_*. Auto-enables
    // photoMode internally so the same circular guide + snap path is reused.
    data class CaptureProgress(
        val coinIndex: Int,
        val stepIndex: Int,
        val coin: CaptureProtocol.Coin,
        val step: CaptureProtocol.Step,
        val captured: Int,
        val total: Int,
        val isComplete: Boolean,
    )

    private val _captureMode = MutableStateFlow(false)
    val captureMode: StateFlow<Boolean> = _captureMode.asStateFlow()

    private val _captureProgress = MutableStateFlow<CaptureProgress?>(null)
    val captureProgress: StateFlow<CaptureProgress?> = _captureProgress.asStateFlow()

    private var captureCoinIdx = 0
    private var captureStepIdx = 0
    private var captureCount = 0
    private var captureSessionDir: java.io.File? = null

    val streakCount: StateFlow<Int> = streakRepository.currentStreak

    private val consensus = ConsensusBuffer()

    init {
        // Wire the analyzer's cheap live-detection probe to the ring color
        // state. The probe only fires while photoMode is on (analyzer-side
        // gate), so the callback is implicitly silent in continuous mode.
        coinAnalyzer.onPhotoLiveDetection = { detection ->
            _photoLiveCircleFound.value = detection != null
        }
    }

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

        if (_recordMode.value) {
            _recordedFrameCount.value = coinAnalyzer.recordedFrameCount
        }

        // Photo mode: bypass consensus and the 3D viewer entirely. Surface the
        // exact masked crop the model saw, plus its top-K scores, so we can
        // diagnose ArcFace misbehavior visually. When normalization fails
        // (Hough finds no centered circle), cropPath is null — we still emit
        // a PhotoSnap so the layer can render the failure card; ArcFace was
        // not invoked and matches is empty.
        if (_photoMode.value) {
            val cropPath = result.photoSnapCropPath
            _photoSnap.value = PhotoSnap(
                cropPath = cropPath,
                accepted = result.detected,
                decisionReason = result.rerankDecisionReason,
                top1 = result.rerankSimilaritiesTop1.firstOrNull() ?: 0f,
                top2 = result.rerankSimilaritiesTop2.firstOrNull() ?: 0f,
                matches = result.matches,
                cropSize = result.cropWidth,
            )
            Log.d(TAG, "photo snap stored: ${cropPath ?: "<no crop>"} (${result.rerankDecisionReason})")
            // Capture mode: only count snaps with a successful normalization.
            // A failed snap does not advance the protocol — user taps "refaire"
            // to retry the same step. Keeps the golden set strictly composed
            // of usable inputs.
            if (_captureMode.value) {
                if (cropPath != null) {
                    val coin = CaptureProtocol.coins.getOrNull(captureCoinIdx)
                    val step = CaptureProtocol.steps.getOrNull(captureStepIdx)
                    if (coin != null && step != null) {
                        appendCaptureManifest(coin, step, cropPath)
                        captureCount++
                        updateCaptureProgress()
                    }
                }
                coinAnalyzer.captureContext = null
            }
            return
        }

        val current = _state.value
        if (current is ScanState.Accepted) return

        // Track consecutive frames without detection → return to Idle silently
        if (!result.detected) {
            consecutiveNoDetection++
            if (current is ScanState.Detecting && consecutiveNoDetection >= IDLE_RETURN_THRESHOLD) {
                Log.d(TAG, "no detection for $IDLE_RETURN_THRESHOLD frames, returning to Idle")
                _state.value = ScanState.Idle
                consensus.reset()
                consecutiveNoDetection = 0
            }
            return
        }
        consecutiveNoDetection = 0

        val isNewConsensus = consensus.push(topClass)

        // Transition to Detecting on the first frame with a candidate
        if (current is ScanState.Idle && result.detected) {
            _state.value = ScanState.Detecting
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
            _state.value = ScanState.Accepted(coin, confidence, alreadyOwned)

            if (alreadyOwned) {
                autoReturnJob?.cancel()
                autoReturnJob = viewModelScope.launch {
                    delay(ALREADY_OWNED_TOAST_MS)
                    returnToIdle(cooldownClass = classifierName)
                }
            }
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // User actions from the UI
    // ─────────────────────────────────────────────────────────────────────

    fun onAddToVault() {
        val current = _state.value as? ScanState.Accepted ?: return
        if (current.alreadyOwned) {
            returnToIdle(cooldownClass = current.coin.eurioId)
            return
        }
        viewModelScope.launch {
            vaultRepository.addCoin(current.coin.eurioId, current.confidence)
            streakRepository.onScanAccepted()
            checkSetCompletions(current.coin.eurioId)
            returnToIdle(cooldownClass = current.coin.eurioId)
        }
    }

    fun onDismissCard() {
        val cooldownId = when (val s = _state.value) {
            is ScanState.Accepted -> s.coin.eurioId
            is ScanState.Failure -> null
            else -> null
        }
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

    /**
     * Toggle capture mode (Phase 0 golden-set). Auto-enables photoMode so the
     * circular guide + snap path are reused. Disabling capture mode also
     * disables photoMode and clears any in-flight result.
     */
    fun onCaptureToggle() {
        val turningOn = !_captureMode.value
        _captureMode.value = turningOn
        if (turningOn) {
            captureCoinIdx = 0
            captureStepIdx = 0
            captureCount = 0
            // Session dir: eval_real/ is the stable parent (so multiple sessions
            // overwrite cleanly per coin/step) — re-running a step replaces the file.
            captureSessionDir = coinAnalyzer.debugRootDir?.let { java.io.File(it, "eval_real") }
            captureSessionDir?.mkdirs()
            if (!_photoMode.value) {
                _photoMode.value = true
                coinAnalyzer.photoMode = true
            }
            consensus.reset()
            _photoSnap.value = null
            if (_state.value !is ScanState.Accepted) _state.value = ScanState.Idle
            updateCaptureProgress()
            Log.d(TAG, "capture mode ON, dir=${captureSessionDir?.absolutePath}")
        } else {
            _captureProgress.value = null
            coinAnalyzer.captureContext = null
            if (_photoMode.value) {
                _photoMode.value = false
                coinAnalyzer.photoMode = false
            }
            _photoSnap.value = null
            Log.d(TAG, "capture mode OFF")
        }
    }

    /**
     * Re-take the current step (clears the photo result, lets the user re-frame
     * and tap snap again — file is overwritten because the path is deterministic).
     */
    fun onCaptureRedo() {
        if (!_captureMode.value) return
        _photoSnap.value = null
    }

    /** Advance to the next step (or next coin, or completion). */
    fun onCaptureNext() {
        if (!_captureMode.value) return
        _photoSnap.value = null
        captureStepIdx++
        if (captureStepIdx >= CaptureProtocol.steps.size) {
            captureStepIdx = 0
            captureCoinIdx++
        }
        if (captureCoinIdx >= CaptureProtocol.coins.size) {
            // Session complete — keep mode on so the user sees the completion banner.
            updateCaptureProgress(complete = true)
            coinAnalyzer.captureContext = null
            Log.d(TAG, "capture session complete: $captureCount snaps")
            return
        }
        updateCaptureProgress()
    }

    private fun updateCaptureProgress(complete: Boolean = false) {
        val coin = CaptureProtocol.coins.getOrNull(captureCoinIdx)
        val step = CaptureProtocol.steps.getOrNull(captureStepIdx)
        if (coin == null || step == null) {
            _captureProgress.value = CaptureProgress(
                coinIndex = CaptureProtocol.coins.size,
                stepIndex = 0,
                coin = CaptureProtocol.coins.last(),
                step = CaptureProtocol.steps.last(),
                captured = captureCount,
                total = CaptureProtocol.totalSnaps,
                isComplete = true,
            )
            return
        }
        _captureProgress.value = CaptureProgress(
            coinIndex = captureCoinIdx,
            stepIndex = captureStepIdx,
            coin = coin,
            step = step,
            captured = captureCount,
            total = CaptureProtocol.totalSnaps,
            isComplete = complete,
        )
    }

    /**
     * Append one entry to the capture session manifest.jsonl. Append-style is
     * crash-resilient — partial sessions still leave a parsable trail.
     */
    private fun appendCaptureManifest(coin: CaptureProtocol.Coin, step: CaptureProtocol.Step, cropPath: String) {
        val dir = captureSessionDir ?: return
        val manifest = java.io.File(dir, "manifest.jsonl")
        val ts = java.text.SimpleDateFormat("yyyyMMdd_HHmmss_SSS", java.util.Locale.US)
            .format(java.util.Date())
        val safeLabel = step.label.replace("\"", "\\\"")
        val line = """{"ts":"$ts","eurio_id":"${coin.eurioId}","step_id":"${step.id}",""" +
            """"step_label":"$safeLabel","step_index":${captureStepIdx},""" +
            """"crop_path":"${cropPath.replace("\"", "\\\"")}"}"""
        try {
            manifest.appendText(line + "\n")
        } catch (e: Exception) {
            Log.e(TAG, "manifest append failed", e)
        }
    }

    /** Toggle the photo mode (single-shot, isolated coin via circular mask). */
    fun onPhotoToggle() {
        val turningOn = !_photoMode.value
        _photoMode.value = turningOn
        coinAnalyzer.photoMode = turningOn
        coinAnalyzer.snapRequested = false
        _photoSnap.value = null
        // Reset the live-ring state so it doesn't carry over from a previous
        // photo session. Stays false until the analyzer's next probe fires.
        _photoLiveCircleFound.value = false
        consensus.reset()
        consecutiveNoDetection = 0
        if (_state.value !is ScanState.Accepted) {
            _state.value = ScanState.Idle
        }
        Log.d(TAG, "photo mode toggled: $turningOn")
    }

    /** Capture the next frame and run it through the photo pipeline. */
    fun onSnap() {
        if (!_photoMode.value) return
        _photoSnap.value = null
        // If capture mode is active, tag the next snap so the analyzer routes
        // it under eval_real/<eurio_id>/<step_id>_*.
        if (_captureMode.value) {
            val coin = CaptureProtocol.coins.getOrNull(captureCoinIdx)
            val step = CaptureProtocol.steps.getOrNull(captureStepIdx)
            coinAnalyzer.captureContext = if (coin != null && step != null) {
                com.musubi.eurio.ml.CoinAnalyzer.CaptureContext(
                    eurioId = coin.eurioId,
                    stepId = step.id,
                    stepLabel = step.label,
                    stepIndex = captureStepIdx,
                )
            } else null
        } else {
            coinAnalyzer.captureContext = null
        }
        coinAnalyzer.snapRequested = true
        Log.d(TAG, "snap requested")
    }

    /** Clear the current photo snap result; UI returns to the guide circle. */
    fun onSnapAgain() {
        _photoSnap.value = null
    }

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

    /** Toggle the debug carousel. No-op if debug mode is off. */
    fun toggleCarouselMode() {
        if (!_debugMode.value) return
        val turningOn = !_carouselMode.value
        _carouselMode.value = turningOn
        if (turningOn) {
            viewModelScope.launch {
                if (carouselCoins.isEmpty()) {
                    carouselCoins = coinRepository.findAllByFaceValue(2.0)
                    Log.d(TAG, "carousel loaded ${carouselCoins.size} 2€ coins")
                }
                if (carouselCoins.isNotEmpty()) {
                    carouselIndex = 0
                    showCarouselAt(carouselIndex)
                }
            }
        } else {
            // Leaving carousel mode — drop any Accepted state and return to Idle
            // so the live camera resumes cleanly.
            returnToIdle(cooldownClass = null)
            _carouselCurrent.value = null
        }
    }

    fun onCarouselNext() = stepCarousel(+1)
    fun onCarouselPrev() = stepCarousel(-1)

    private fun stepCarousel(delta: Int) {
        if (!_carouselMode.value || carouselCoins.isEmpty()) return
        carouselIndex = ((carouselIndex + delta) % carouselCoins.size + carouselCoins.size) % carouselCoins.size
        Log.d(TAG, "carousel step delta=$delta → index=$carouselIndex/${carouselCoins.size} ${carouselCoins[carouselIndex].eurioId}")
        showCarouselAt(carouselIndex)
    }

    private fun showCarouselAt(index: Int) {
        val coin = carouselCoins[index]
        viewModelScope.launch {
            val alreadyOwned = vaultRepository.containsCoin(coin.eurioId)
            _carouselCurrent.value = coin
            // Same emission path as a real detection — the UI doesn't know the
            // difference, which is the whole point of the debug carousel.
            _state.value = ScanState.Accepted(coin, confidence = 1.0f, alreadyOwned = alreadyOwned)
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // Internals
    // ─────────────────────────────────────────────────────────────────────

    private fun returnToIdle(cooldownClass: String?) {
        autoReturnJob?.cancel()
        autoReturnJob = null
        consensus.reset()
        consecutiveNoDetection = 0
        if (cooldownClass != null) {
            this.cooldownClass = cooldownClass
            cooldownUntilMs = System.currentTimeMillis() + DISMISS_COOLDOWN_MS
        }
        _state.value = ScanState.Idle
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
    }
}
