package com.musubi.eurio.features.dev.photo

import android.util.Log
import androidx.camera.core.ImageProxy
import androidx.lifecycle.ViewModel
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.CoinMatch
import com.musubi.eurio.ml.ScanResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * ViewModel pour /dev/photo — photo snap standalone (ArcFace inspect).
 *
 * Single-shot : viseur + guide circle, l'utilisateur tap SNAP, ArcFace tourne
 * sur le crop normalisé, on affiche top-K + decision reason. Reset pour refaire.
 * Pas de progression cellule (≠ /dev/capture), pas de manifeste.
 */
class PhotoViewModel(
    private val coinAnalyzer: CoinAnalyzer,
) : ViewModel() {

    companion object {
        private const val TAG = "PhotoVM"
    }

    data class PhotoSnap(
        val cropPath: String?,
        val accepted: Boolean,
        val decisionReason: String,
        val top1: Float,
        val top2: Float,
        val matches: List<CoinMatch>,
        val cropSize: Int,
    )

    private val _snap = MutableStateFlow<PhotoSnap?>(null)
    val snap: StateFlow<PhotoSnap?> = _snap.asStateFlow()

    private val _liveCircleFound = MutableStateFlow(false)
    val liveCircleFound: StateFlow<Boolean> = _liveCircleFound.asStateFlow()

    fun enter() {
        coinAnalyzer.photoMode = true
        coinAnalyzer.snapRequested = false
        coinAnalyzer.captureContext = null
        coinAnalyzer.onPhotoLiveDetection = { detection ->
            _liveCircleFound.value = detection != null
        }
        _snap.value = null
        _liveCircleFound.value = false
        Log.d(TAG, "photo session started")
    }

    fun leave() {
        coinAnalyzer.photoMode = false
        coinAnalyzer.snapRequested = false
        coinAnalyzer.captureContext = null
        coinAnalyzer.onPhotoLiveDetection = null
        coinAnalyzer.clearPhotoCache()
        _snap.value = null
        _liveCircleFound.value = false
        Log.d(TAG, "photo session ended")
    }

    fun onScanResult(result: ScanResult) {
        val cropPath = result.photoSnapCropPath
        _snap.value = PhotoSnap(
            cropPath = cropPath,
            accepted = result.detected,
            decisionReason = result.rerankDecisionReason,
            top1 = result.rerankSimilaritiesTop1.firstOrNull() ?: 0f,
            top2 = result.rerankSimilaritiesTop2.firstOrNull() ?: 0f,
            matches = result.matches,
            cropSize = result.cropWidth,
        )
        Log.d(TAG, "photo snap stored: ${cropPath ?: "<no crop>"} (${result.rerankDecisionReason})")
    }

    /** Tap SNAP — request the next analyzed frame. */
    fun onSnap() {
        _snap.value = null
        coinAnalyzer.captureContext = null
        coinAnalyzer.snapRequested = true
        Log.d(TAG, "snap requested")
    }

    /** Tap reset — clear snap result, return to live guide. */
    fun onReset() {
        _snap.value = null
    }

    fun onFrame(image: ImageProxy) {
        coinAnalyzer.analyze(image)
    }

    override fun onCleared() {
        super.onCleared()
        coinAnalyzer.photoMode = false
        coinAnalyzer.snapRequested = false
        coinAnalyzer.onPhotoLiveDetection = null
        coinAnalyzer.clearPhotoCache()
    }
}
