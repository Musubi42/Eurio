package com.musubi.eurio.features.dev.capture

import android.util.Log
import androidx.lifecycle.ViewModel
import com.musubi.eurio.features.scan.CaptureProtocol
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.CoinMatch
import com.musubi.eurio.ml.ScanResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * ViewModel pour /dev/capture — protocole cohort capture (Phase 0 golden-set).
 *
 * UX (raph 2026-05-28) : la vue reste stable (caméra + bannière + ring + 2
 * boutons), seuls les boutons changent selon qu'un snap est en attente. Pas
 * d'auto-advance — l'utilisateur tap "suivant" lui-même après chaque snap.
 * Mode ABLATION : 4 snaps consécutifs dans la même step avant de basculer
 * automatiquement vers la step suivante.
 *
 *  ┌────────────────────────────────┬────────────────────────┐
 *  │ État                           │ Boutons (gauche / droite)
 *  ├────────────────────────────────┼────────────────────────┤
 *  │ Pas de snap pending            │ skip cellule │ ● SNAP
 *  │ Snap pending (cropPath != null)│ ↻ refaire    │ ✓ suivant
 *  │ Snap pending (cropPath == null)│ ↻ refaire    │ (suivant disabled)
 *  └────────────────────────────────┴────────────────────────┘
 *
 * Cf. docs/scan-normalization/phase-0-capture.md et plan refacto B
 * (memory project_scan_screen_refacto).
 */
class CaptureViewModel(
    private val coinAnalyzer: CoinAnalyzer,
) : ViewModel() {

    companion object {
        private const val TAG = "CaptureVM"
    }

    data class CaptureProgress(
        val coinIndex: Int,
        val stepIndex: Int,
        val photoIndex: Int,
        val photosPerStep: Int,
        val coin: CaptureProtocol.Coin,
        val step: CaptureProtocol.Step,
        val captured: Int,
        val total: Int,
        val isComplete: Boolean,
    )

    /**
     * Snapshot d'une snap photo (réussie ou non). cropPath=null → normalisation
     * échouée (Hough n'a trouvé aucun cercle centré) ; la cellule n'est pas
     * comptée et l'utilisateur doit refaire.
     */
    data class PhotoSnap(
        val cropPath: String?,
        val accepted: Boolean,
        val decisionReason: String,
        val top1: Float,
        val top2: Float,
        val matches: List<CoinMatch>,
        val cropSize: Int,
    )

    private val _progress = MutableStateFlow<CaptureProgress?>(null)
    val progress: StateFlow<CaptureProgress?> = _progress.asStateFlow()

    private val _photoSnap = MutableStateFlow<PhotoSnap?>(null)
    val photoSnap: StateFlow<PhotoSnap?> = _photoSnap.asStateFlow()

    private val _photoLiveCircleFound = MutableStateFlow(false)
    val photoLiveCircleFound: StateFlow<Boolean> = _photoLiveCircleFound.asStateFlow()

    private var coinIdx = 0
    private var stepIdx = 0
    private var photoIdx = 0
    private var captured = 0
    private var sessionDir: java.io.File? = null

    /**
     * True entre le tap "SNAP" et l'arrivée du `ScanResult` correspondant.
     * Sans ce gate, des frames in-flight du scan continu (émises avant le
     * basculement photoMode de l'analyzer) atteignent `onScanResult` avec
     * `photoSnapCropPath=null` et provoquent un faux "NORMALIZE FAILED" au
     * premier passage sur l'écran.
     */
    @Volatile private var awaitingSnapResult: Boolean = false

    /**
     * À appeler depuis le composable (DisposableEffect) à l'entrée de l'écran.
     * Active photoMode analyzer + initialise le compteur.
     */
    fun enter() {
        coinIdx = 0
        stepIdx = 0
        photoIdx = 0
        captured = 0
        sessionDir = coinAnalyzer.debugRootDir?.let { java.io.File(it, "eval_real") }
        sessionDir?.mkdirs()
        coinAnalyzer.photoMode = true
        coinAnalyzer.snapRequested = false
        coinAnalyzer.captureContext = null
        coinAnalyzer.onPhotoLiveDetection = { detection ->
            _photoLiveCircleFound.value = detection != null
        }
        awaitingSnapResult = false
        _photoSnap.value = null
        _photoLiveCircleFound.value = false
        updateProgress()
        Log.d(TAG, "capture session started, dir=${sessionDir?.absolutePath}")
    }

    /**
     * À appeler depuis DisposableEffect.onDispose. Reset analyzer flags ; les
     * fichiers déjà écrits sous eval_real/ restent en place pour `go-task
     * android:pull-debug`.
     */
    fun leave() {
        coinAnalyzer.photoMode = false
        coinAnalyzer.snapRequested = false
        coinAnalyzer.captureContext = null
        coinAnalyzer.onPhotoLiveDetection = null
        _photoSnap.value = null
        _photoLiveCircleFound.value = false
        Log.d(TAG, "capture session ended, captured=$captured")
    }

    /**
     * Délégué appelé par `scanCallbackRelay` après chaque snap. On set
     * `_photoSnap` (la vue passe en mode "snap pending" : crop dans le ring,
     * boutons refaire/suivant) mais on n'avance PAS les indices — l'utilisateur
     * inspecte le crop et tap "suivant" pour confirmer (ou "refaire" pour rejeter).
     */
    fun onScanResult(result: ScanResult) {
        if (!awaitingSnapResult) return
        awaitingSnapResult = false
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
        Log.d(TAG, "snap stored: ${cropPath ?: "<no crop>"} (${result.rerankDecisionReason})")
        if (cropPath != null) {
            val coin = CaptureProtocol.coins.getOrNull(coinIdx)
            val step = CaptureProtocol.steps.getOrNull(stepIdx)
            if (coin != null && step != null) {
                appendManifest(coin, step, cropPath, photoIdx)
                captured++
                updateProgress()
            }
        }
        coinAnalyzer.captureContext = null
    }

    /**
     * Tap utilisateur sur "SNAP". Tag le contexte capture pour que l'analyzer
     * route le crop sous eval_real/<eurioId>/<stepId>_*.
     */
    fun onSnap() {
        _photoSnap.value = null
        val coin = CaptureProtocol.coins.getOrNull(coinIdx)
        val step = CaptureProtocol.steps.getOrNull(stepIdx)
        coinAnalyzer.captureContext = if (coin != null && step != null) {
            CoinAnalyzer.CaptureContext(
                eurioId = coin.eurioId,
                stepId = step.id,
                stepLabel = step.label,
                stepIndex = stepIdx,
                photoIndex = photoIdx,
            )
        } else null
        awaitingSnapResult = true
        coinAnalyzer.snapRequested = true
        Log.d(TAG, "snap requested coin=${coin?.eurioId} step=${step?.id} photo=$photoIdx")
    }

    /**
     * Tap "↻ refaire" — rejette le snap courant. Le fichier déjà écrit sous
     * eval_real/ est laissé en place (overwrite au prochain snap puisque le
     * path est déterministe sur step_id + photo_idx).
     */
    fun onRedo() {
        awaitingSnapResult = false
        _photoSnap.value = null
    }

    /**
     * Tap "✓ suivant" après un snap réussi. Avance d'une photo dans la même
     * step ; quand photoIdx atteint photosPerStep, passe automatiquement à la
     * step suivante (puis coin suivant si toutes les steps sont faites).
     */
    fun onAdvancePhoto() {
        awaitingSnapResult = false
        _photoSnap.value = null
        photoIdx++
        if (photoIdx >= CaptureProtocol.photosPerStep) {
            photoIdx = 0
            stepIdx++
            if (stepIdx >= CaptureProtocol.steps.size) {
                stepIdx = 0
                coinIdx++
            }
            if (coinIdx >= CaptureProtocol.coins.size) {
                updateProgress(complete = true)
                coinAnalyzer.captureContext = null
                Log.d(TAG, "capture session complete: $captured snaps")
                return
            }
        }
        updateProgress()
    }

    /**
     * Tap "skip cellule" en absence de snap pending — saute la step courante
     * intégralement (force step++). Utile quand on ne veut pas faire les 4
     * photos restantes d'une condition donnée.
     */
    fun onSkipCell() {
        awaitingSnapResult = false
        _photoSnap.value = null
        photoIdx = 0
        stepIdx++
        if (stepIdx >= CaptureProtocol.steps.size) {
            stepIdx = 0
            coinIdx++
        }
        if (coinIdx >= CaptureProtocol.coins.size) {
            updateProgress(complete = true)
            coinAnalyzer.captureContext = null
            Log.d(TAG, "capture session complete: $captured snaps")
            return
        }
        updateProgress()
    }

    private fun updateProgress(complete: Boolean = false) {
        val coin = CaptureProtocol.coins.getOrNull(coinIdx)
        val step = CaptureProtocol.steps.getOrNull(stepIdx)
        if (coin == null || step == null) {
            val coins = CaptureProtocol.coins
            val steps = CaptureProtocol.steps
            if (coins.isEmpty() || steps.isEmpty()) {
                _progress.value = null
                Log.w(TAG, "no coins/steps in CaptureProtocol — push cohort.csv first")
                return
            }
            _progress.value = CaptureProgress(
                coinIndex = coins.size,
                stepIndex = 0,
                photoIndex = 0,
                photosPerStep = CaptureProtocol.photosPerStep,
                coin = coins.last(),
                step = steps.last(),
                captured = captured,
                total = CaptureProtocol.totalSnaps,
                isComplete = true,
            )
            return
        }
        _progress.value = CaptureProgress(
            coinIndex = coinIdx,
            stepIndex = stepIdx,
            photoIndex = photoIdx,
            photosPerStep = CaptureProtocol.photosPerStep,
            coin = coin,
            step = step,
            captured = captured,
            total = CaptureProtocol.totalSnaps,
            isComplete = complete,
        )
    }

    private fun appendManifest(
        coin: CaptureProtocol.Coin,
        step: CaptureProtocol.Step,
        cropPath: String,
        photoIdx: Int,
    ) {
        val dir = sessionDir ?: return
        val manifest = java.io.File(dir, "manifest.jsonl")
        val ts = java.text.SimpleDateFormat("yyyyMMdd_HHmmss_SSS", java.util.Locale.US)
            .format(java.util.Date())
        val safeLabel = step.label.replace("\"", "\\\"")
        val line = """{"ts":"$ts","eurio_id":"${coin.eurioId}","step_id":"${step.id}",""" +
            """"step_label":"$safeLabel","step_index":${stepIdx},""" +
            """"photo_index":${photoIdx},"photos_per_step":${CaptureProtocol.photosPerStep},""" +
            """"protocol_mode":"${CaptureProtocol.mode.name.lowercase()}",""" +
            """"crop_path":"${cropPath.replace("\"", "\\\"")}"}"""
        try {
            manifest.appendText(line + "\n")
        } catch (e: Exception) {
            Log.e(TAG, "manifest append failed", e)
        }
    }

    /** Pipe les frames CameraX vers l'analyzer (qui les filtre via photoMode). */
    fun onFrame(image: androidx.camera.core.ImageProxy) {
        coinAnalyzer.analyze(image)
    }

    override fun onCleared() {
        super.onCleared()
        coinAnalyzer.photoMode = false
        coinAnalyzer.captureContext = null
        coinAnalyzer.onPhotoLiveDetection = null
    }
}
