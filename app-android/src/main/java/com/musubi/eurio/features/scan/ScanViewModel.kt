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

    private val _debugData = MutableStateFlow(DebugViewData())
    val debugData: StateFlow<DebugViewData> = _debugData.asStateFlow()

    val streakCount: StateFlow<Int> = streakRepository.currentStreak

    private val consensus = ConsensusBuffer()

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

    fun onCaptureClicked() {
        coinAnalyzer.captureNextFrame = true
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
