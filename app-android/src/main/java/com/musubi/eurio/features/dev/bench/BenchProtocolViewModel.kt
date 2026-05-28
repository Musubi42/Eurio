package com.musubi.eurio.features.dev.bench

import android.util.Log
import androidx.camera.core.ImageProxy
import androidx.lifecycle.ViewModel
import com.musubi.eurio.features.scan.debug.DebugScanConfig
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.ScanResult
import com.musubi.eurio.ml.bench.ArcfacePayload
import com.musubi.eurio.ml.bench.BenchEvent
import com.musubi.eurio.ml.bench.BenchProtocol
import com.musubi.eurio.ml.bench.BenchProtocolState
import com.musubi.eurio.ml.bench.BenchRecorder
import com.musubi.eurio.ml.bench.DetectionPayload
import com.musubi.eurio.ml.bench.PassesPayload
import com.musubi.eurio.ml.bench.ScorePayload
import com.musubi.eurio.ml.bench.TimingsPayload
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * ViewModel pour /dev/bench — protocole bench guidé (chunk-7b).
 *
 * Drive l'opérateur cellule par cellule (coin × condition) en taggant
 * automatiquement chaque session BenchRecorder avec les métadonnées. Pendant
 * qu'une cellule est IN_PROGRESS, chaque frame analyzée par CoinAnalyzer est
 * loggée comme `frame_analyzed` event dans la session du recorder.
 *
 * Différence vs. record-mode dans /scan : ici la state machine scan ne tourne
 * pas, donc on n'a PAS les events TriggerFire/Lock/Consensus. C'est volontaire :
 * /dev/bench mesure le comportement analyzer-par-frame sous conditions
 * standardisées ; pour un enregistrement complet du pipeline il faut utiliser
 * /scan avec record toggle ON.
 */
class BenchProtocolViewModel(
    private val coinAnalyzer: CoinAnalyzer,
    private val benchRecorder: BenchRecorder,
    private val debugConfigProvider: () -> DebugScanConfig,
) : ViewModel() {

    companion object {
        private const val TAG = "BenchProtocolVM"
    }

    private val _state = MutableStateFlow<BenchProtocolState?>(null)
    val state: StateFlow<BenchProtocolState?> = _state.asStateFlow()

    /**
     * À appeler depuis le composable (DisposableEffect) à l'entrée de l'écran.
     * Init les cellules depuis BenchProtocol.cells() et stoppe défensivement
     * une session recorder pré-existante (p.ex. record-mode scan resté actif).
     */
    fun enter() {
        benchRecorder.takeIf { it.isActive }?.let {
            Log.w(TAG, "enter: recorder déjà actif, stop défensif")
            it.stop()
        }
        coinAnalyzer.photoMode = false
        coinAnalyzer.snapRequested = false
        coinAnalyzer.captureContext = null
        coinAnalyzer.onPhotoLiveDetection = null

        val cells = BenchProtocol.cells()
        _state.value = if (cells.isEmpty()) {
            Log.w(TAG, "enter: pas de coins dans CaptureProtocol — push cohort.csv first")
            null
        } else {
            BenchProtocolState.fresh(cells)
        }
        Log.d(TAG, "bench protocol started: ${cells.size} cells")
    }

    /**
     * À appeler depuis DisposableEffect.onDispose. Stoppe la session en cours
     * si présente. Pas de nettoyage analyzer (pas de flags posés en bench).
     */
    fun leave() {
        benchRecorder.takeIf { it.isActive }?.stop()
        Log.d(TAG, "bench protocol ended")
    }

    /** Begin recording the current cell. Marks the cell IN_PROGRESS. */
    fun startCurrent() {
        val s = _state.value ?: return
        val cell = s.currentCell ?: return
        if (benchRecorder.isActive) {
            Log.w(TAG, "startCurrent: recorder déjà actif, ignore")
            return
        }
        benchRecorder.start(
            config = debugConfigProvider(),
            deviceInfo = buildDeviceInfo(),
            coin = cell.coin.eurioId,
            condition = cell.condition.id,
        )
        _state.value = s.withStatus(s.currentIndex, BenchProtocolState.CellStatus.IN_PROGRESS)
    }

    /** Stop the recorder and advance, marking current DONE. */
    fun markCurrentDone() {
        val s = _state.value ?: return
        benchRecorder.takeIf { it.isActive }?.stop()
        _state.value = s
            .withStatus(s.currentIndex, BenchProtocolState.CellStatus.DONE)
            .copy(currentIndex = s.currentIndex + 1)
    }

    /** Skip the current cell. If a session was active, stop it (still flushed). */
    fun skipCurrent() {
        val s = _state.value ?: return
        benchRecorder.takeIf { it.isActive }?.stop()
        _state.value = s
            .withStatus(s.currentIndex, BenchProtocolState.CellStatus.SKIPPED)
            .copy(currentIndex = s.currentIndex + 1)
    }

    /**
     * Délégué appelé par `scanCallbackRelay`. Log un `frame_analyzed` event
     * vers le recorder si une cellule est IN_PROGRESS.
     */
    fun onScanResult(result: ScanResult) {
        val rec = benchRecorder.takeIf { it.isActive } ?: return
        val s = _state.value ?: return
        if (s.currentStatus != BenchProtocolState.CellStatus.IN_PROGRESS) return
        rec.log(buildFrameAnalyzedEvent(result, rec.nowSeconds()))
    }

    /** Pipe les frames CameraX vers l'analyzer. */
    fun onFrame(image: ImageProxy) {
        coinAnalyzer.analyze(image)
    }

    override fun onCleared() {
        super.onCleared()
        benchRecorder.takeIf { it.isActive }?.stop()
    }

    private fun buildDeviceInfo(): BenchEvent.DeviceInfo = BenchEvent.DeviceInfo(
        t = 0.0,
        model = android.os.Build.MODEL,
        api = android.os.Build.VERSION.SDK_INT,
        manufacturer = android.os.Build.MANUFACTURER,
        sensor = null,
    )

    private fun buildFrameAnalyzedEvent(
        result: ScanResult,
        t: Double,
    ): BenchEvent.FrameAnalyzed {
        val det = result.bestDetection
        val detection = det?.let {
            DetectionPayload(
                method = it.source.name,
                bbox = listOf(it.bbox.left, it.bbox.top, it.bbox.right, it.bbox.bottom),
                yoloConf = it.confidence,
            )
        }
        val s = result.frameScore
        val score = s?.let {
            ScorePayload(
                sharpness = it.sharpness,
                sharpnessRaw = it.sharpnessRaw,
                exposure = it.exposure,
                meanLuminance = it.meanLuminance,
                clippingRatio = it.clippingRatio,
                completeness = it.completeness,
                motion = it.motion,
                aggregate = it.aggregate,
                passes = PassesPayload(
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
            timingsMs = TimingsPayload(
                detect = result.yoloTotalMs,
                normalize = result.normalizeMs,
                arcface = result.rerankMs,
                score = result.scoreMs,
            ),
        )
    }
}
