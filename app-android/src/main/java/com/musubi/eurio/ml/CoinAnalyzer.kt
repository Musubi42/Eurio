package com.musubi.eurio.ml

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color as AndroidColor
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.YuvImage
import android.util.Log
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import java.io.ByteArrayOutputStream

/**
 * Result emitted by CoinAnalyzer each time a frame is analyzed.
 */
data class ScanResult(
    val matches: List<CoinMatch>,
    val totalInferenceMs: Long = 0,
    // Detection stage (YOLO + Hough + merge)
    val yoloInferenceMs: Long = 0,
    val yoloTotalMs: Long = 0,
    val yoloKeptCount: Int = 0,
    val houghInferenceMs: Long = 0,
    val houghRan: Boolean = false,
    val houghKeptCount: Int = 0,
    val mergeDedupCount: Int = 0,
    val rawYoloCount: Int = 0,
    // Rerank stage (ArcFace re-scoring across ALL merged candidates)
    val rerankMs: Long = 0,
    val rerankSimilaritiesTop1: List<Float> = emptyList(),  // top1 sim per candidate (same order as detections)
    val rerankSimilaritiesTop2: List<Float> = emptyList(),  // top2 sim per candidate
    val rerankRejectedAll: Boolean = false,                 // every candidate failed the decision rule
    val rerankDecisionReason: String = "",                  // human-readable reason for accept/reject
    // Final identification (reuses rerank result for the winner — no extra inference)
    val identificationInferenceMs: Long = 0,
    val detections: List<Detection> = emptyList(),           // merged list, post dedup, cap 5
    val selectedDetectionIndex: Int = -1,
    // Frame info
    val frameWidth: Int = 0,
    val frameHeight: Int = 0,
    val cropWidth: Int = 0,
    val cropHeight: Int = 0,
    val letterboxScale: Float = 0f,
    val letterboxPadX: Int = 0,
    val letterboxPadY: Int = 0,
    val timestamp: Long = System.currentTimeMillis(),
    // Photo mode (one-shot): absolute path to the masked crop sent to ArcFace.
    // Null in continuous mode. UI displays this exact image so the user can
    // see what the model actually saw.
    val photoSnapCropPath: String? = null,
) {
    val detected: Boolean get() = detections.isNotEmpty() && selectedDetectionIndex >= 0
    val bestDetection: Detection? get() = detections.getOrNull(selectedDetectionIndex)
    val cropSize: String get() = if (cropWidth > 0) "${cropWidth}x${cropHeight}" else ""
}

/**
 * Two-stage coin analysis pipeline:
 *   1. [CoinDetector] (YOLOv8-nano) detects if there's a coin → bounding box
 *   2. [CoinRecognizer] + [EmbeddingMatcher] identifies which coin via embedding similarity
 *
 * If no detector is provided, falls back to full-frame analysis (legacy behavior).
 */
class CoinAnalyzer(
    private val recognizer: CoinRecognizer,
    private val matcher: EmbeddingMatcher? = null,
    private val detector: CoinDetector? = null,
    private val onResult: (ScanResult) -> Unit,
    private val analyzeIntervalMs: Long = 400L,
    private val detectionThreshold: Float = 0.40f,
) : ImageAnalysis.Analyzer {

    companion object {
        // Rerank decision thresholds (see plan, fix ③).
        // All calibrated on very sparse data — tune as more captures come in.
        const val RERANK_TOP1_MIN = 0.20f          // absolute floor — below this is garbage
        const val RERANK_CONFIDENT_ALONE = 0.55f   // top1 high enough to accept regardless of spread
        const val RERANK_SPREAD_MIN = 0.08f        // required top1−top2 gap when in the middle band
    }

    /** Toggle YOLO detection on/off at runtime. */
    @Volatile
    var useDetector: Boolean = detector != null

    /** Toggle embedding matching vs classification at runtime. */
    @Volatile
    var useEmbeddings: Boolean = matcher != null

    /** Root debug directory (set by the application). Record sessions go inside. */
    var debugRootDir: java.io.File? = null

    /**
     * Continuous record mode. When true and [recordSessionDir] is set, every
     * analyzed frame is dumped to disk: raw jpg + annotated jpg + a JSONL line
     * with the full pipeline state (YOLO, Hough, ArcFace top-3 per candidate,
     * decision, timings). Toggled from the debug overlay.
     */
    @Volatile
    var recordMode: Boolean = false

    /** Session directory for the current record run. Set when recording starts. */
    @Volatile
    var recordSessionDir: java.io.File? = null

    /** Frame index within the current record session. Reset on session start. */
    private val recordFrameIndex = java.util.concurrent.atomic.AtomicInteger(0)

    /** Last frame index written (read by the UI for the live counter). */
    @Volatile
    var recordedFrameCount: Int = 0
        private set

    fun resetRecordCounter() {
        recordFrameIndex.set(0)
        recordedFrameCount = 0
    }

    /**
     * Photo mode: continuous analysis is paused; frames are dropped until the
     * user taps SNAP. On snap we crop a centered square (matching the on-screen
     * guide diameter), apply a circular gray-114 mask, and feed the result
     * straight to ArcFace — bypassing YOLO/Hough (the user did the framing).
     */
    @Volatile
    var photoMode: Boolean = false

    @Volatile
    var snapRequested: Boolean = false

    /**
     * When set, the next snap is written to `eval_real/<eurioId>/<stepId>_*`
     * (golden-set capture for Phase 0) instead of the rolling `snaps/snap_<ts>/`
     * directory. The VM sets this before flipping [snapRequested] and clears it
     * after the snap is consumed.
     */
    data class CaptureContext(
        val eurioId: String,
        val stepId: String,
        val stepLabel: String,
        val stepIndex: Int,
    )

    @Volatile
    var captureContext: CaptureContext? = null

    /**
     * Diameter of the photo-mode on-screen guide circle, fraction of the
     * frame's short side. Purely a UX hint now ("aim your coin here roughly")
     * — the actual crop is determined by Hough in [SnapNormalizer], which
     * recenters precisely on the detected coin regardless of where the user
     * placed it inside the guide. Kept so the on-screen overlay stays in
     * sync with the user expectation set during capture-mode framing.
     */
    var photoCropDiameterRatio: Float = 0.70f

    /**
     * Callback fired when a live Hough check produces a new ring state in
     * photo mode. Called at most every [photoLiveDetectIntervalMs] ms; never
     * called outside photo mode. Allows the overlay to color the on-screen
     * guide ring (green when a centered circle is found, gray otherwise)
     * without burning ArcFace cycles on every frame.
     */
    var onPhotoLiveDetection: ((SnapNormalizer.Detection?) -> Unit)? = null

    /**
     * Throttle for the live photo-mode detection loop. 200 ms = 5 fps —
     * Hough on a 480p frame takes ~10–30 ms, so this leaves ~85% of the CPU
     * idle and the camera pipeline unblocked, while still being responsive
     * enough that the ring color tracks the user's framing motion.
     */
    var photoLiveDetectIntervalMs: Long = 200L

    private var lastAnalyzedTimestamp = 0L
    private var lastPhotoLiveDetectMs = 0L

    override fun analyze(imageProxy: ImageProxy) {
        // Photo mode: drop full pipeline (YOLO + Hough + ArcFace) and only
        // run a cheap Hough probe at [photoLiveDetectIntervalMs] cadence to
        // drive the on-screen ring color. The full normalization + ArcFace
        // pass runs only when the user taps SNAP (snapRequested=true).
        if (photoMode) {
            if (!snapRequested) {
                val now = System.currentTimeMillis()
                if (now - lastPhotoLiveDetectMs >= photoLiveDetectIntervalMs) {
                    lastPhotoLiveDetectMs = now
                    try {
                        val bitmap = imageProxyToBitmap(imageProxy)
                        if (bitmap != null) {
                            val det = SnapNormalizer.detectCircleOnly(bitmap)
                            onPhotoLiveDetection?.invoke(det)
                            bitmap.recycle()
                        }
                    } catch (e: Exception) {
                        Log.w("CoinAnalyzer", "Photo live-detect failed", e)
                    }
                }
                imageProxy.close()
                return
            }
            snapRequested = false
            try {
                val bitmap = imageProxyToBitmap(imageProxy)
                if (bitmap != null) {
                    val start = System.currentTimeMillis()
                    val result = analyzePhotoBitmap(bitmap)
                    val elapsed = System.currentTimeMillis() - start
                    onResult(result.copy(totalInferenceMs = elapsed))
                    bitmap.recycle()
                }
            } catch (e: Exception) {
                Log.e("CoinAnalyzer", "Photo analysis failed", e)
            } finally {
                imageProxy.close()
            }
            return
        }

        val now = System.currentTimeMillis()
        if (now - lastAnalyzedTimestamp < analyzeIntervalMs) {
            imageProxy.close()
            return
        }
        lastAnalyzedTimestamp = now

        try {
            val bitmap = imageProxyToBitmap(imageProxy)
            if (bitmap != null) {
                val start = System.currentTimeMillis()
                val result = analyzeBitmap(bitmap)
                val elapsed = System.currentTimeMillis() - start

                onResult(result.copy(totalInferenceMs = elapsed))
                bitmap.recycle()
            }
        } catch (e: Exception) {
            Log.e("CoinAnalyzer", "Analysis failed", e)
        } finally {
            imageProxy.close()
        }
    }

    /**
     * One-shot analysis path used in photo mode. The raw camera frame is
     * normalized by [SnapNormalizer] (Hough → tight crop → black mask → 224)
     * — the same algorithm `ml/scan/normalize_snap.py` runs on studio
     * sources at training time. ArcFace then sees an input from the same
     * distribution it was trained on, which is what makes photo mode usable
     * for identification (vs. continuous scan, which feeds raw bbox crops
     * with a different geometry).
     *
     * Failure mode: if Hough finds no centered circle, the snap is rejected
     * before ArcFace runs. Raw frame + meta are still saved so the user can
     * inspect what the camera actually saw and tune framing/lighting; the
     * UI surfaces the "no circle" reason instead of a fake match.
     */
    private fun analyzePhotoBitmap(bitmap: Bitmap): ScanResult {
        val frameW = bitmap.width
        val frameH = bitmap.height

        val normStart = System.currentTimeMillis()
        val norm = SnapNormalizer.normalize(bitmap)
        val normMs = System.currentTimeMillis() - normStart

        val syntheticBbox = if (norm.r > 0) {
            // Tangent square in raw-frame coords matches what SnapNormalizer
            // cropped, so the debug overlay can render the actual crop region.
            val half = (norm.r + norm.marginPx).toFloat()
            RectF(
                (norm.cx - half).coerceAtLeast(0f),
                (norm.cy - half).coerceAtLeast(0f),
                (norm.cx + half).coerceAtMost(frameW.toFloat()),
                (norm.cy + half).coerceAtMost(frameH.toFloat()),
            )
        } else {
            RectF(0f, 0f, frameW.toFloat(), frameH.toFloat())
        }

        if (norm.image == null) {
            // Normalization failed — surface the reason, save raw + meta only,
            // skip ArcFace entirely. PhotoSnapResultLayer reads the empty crop
            // path and the decision reason to render the failure card.
            val reason = "NORMALIZE FAILED: ${norm.error ?: "unknown"}"
            Log.d("CoinAnalyzer", reason)
            saveSnapToDisk(
                raw = bitmap,
                masked = null,
                matches = emptyList(),
                rerankMs = 0L,
                frameW = frameW,
                frameH = frameH,
                cropSize = 0,
                norm = norm,
            )
            return ScanResult(
                matches = emptyList(),
                detections = emptyList(),
                selectedDetectionIndex = -1,
                rerankMs = 0L,
                rerankSimilaritiesTop1 = emptyList(),
                rerankSimilaritiesTop2 = emptyList(),
                rerankRejectedAll = true,
                rerankDecisionReason = reason,
                frameWidth = frameW,
                frameHeight = frameH,
                cropWidth = 0,
                cropHeight = 0,
                photoSnapCropPath = null,
            )
        }

        val masked = norm.image
        val rerankStart = System.currentTimeMillis()
        val matches = identifyCrop(masked)
        val rerankMs = System.currentTimeMillis() - rerankStart

        val cropPath = saveSnapToDisk(
            raw = bitmap,
            masked = masked,
            matches = matches,
            rerankMs = rerankMs,
            frameW = frameW,
            frameH = frameH,
            cropSize = masked.width,
            norm = norm,
        )
        masked.recycle()

        val top1 = matches.getOrNull(0)?.similarity ?: Float.NEGATIVE_INFINITY
        val top2 = matches.getOrNull(1)?.similarity ?: Float.NEGATIVE_INFINITY
        val accepted = top1 > RERANK_TOP1_MIN
        val reason = if (accepted) {
            "PHOTO ACCEPTED top1=${"%.2f".format(top1)} norm=${norm.method} (${normMs}ms)"
        } else {
            "PHOTO REJECTED top1=${"%.2f".format(top1)} < $RERANK_TOP1_MIN norm=${norm.method}"
        }
        Log.d("CoinAnalyzer", reason)

        val syntheticDet = Detection(
            bbox = syntheticBbox,
            confidence = top1.coerceIn(0f, 1f),
            source = DetectionSource.HOUGH,
        )

        return ScanResult(
            matches = matches,
            detections = listOf(syntheticDet),
            selectedDetectionIndex = if (accepted) 0 else -1,
            rerankMs = rerankMs,
            rerankSimilaritiesTop1 = listOf(top1),
            rerankSimilaritiesTop2 = listOf(top2),
            rerankRejectedAll = !accepted,
            rerankDecisionReason = reason,
            frameWidth = frameW,
            frameHeight = frameH,
            cropWidth = masked.width,
            cropHeight = masked.height,
            photoSnapCropPath = cropPath,
        )
    }

    /**
     * Persist a snap to disk. Always writes the raw frame and meta.json; the
     * normalized 224×224 crop is only written when [masked] is non-null
     * (Hough succeeded). Capture mode (eval_real/) and rolling snap mode
     * (snaps/snap_<ts>/) share the same write logic — only the path layout
     * differs. Returns the crop path for the UI, or null if no crop was
     * produced (failure path).
     */
    private fun saveSnapToDisk(
        raw: Bitmap,
        masked: Bitmap?,
        matches: List<CoinMatch>,
        rerankMs: Long,
        frameW: Int,
        frameH: Int,
        cropSize: Int,
        norm: SnapNormalizer.Result,
    ): String? {
        val root = debugRootDir ?: return null
        return try {
            val ts = java.text.SimpleDateFormat("yyyyMMdd_HHmmss_SSS", java.util.Locale.US)
                .format(java.util.Date())
            val matchesJson = matches.joinToString(",", "[", "]") { m ->
                """{"class":"${m.className.replace("\"", "\\\"")}","sim":${"%.4f".format(java.util.Locale.US, m.similarity)}}"""
            }
            val safeError = norm.error?.replace("\"", "\\\"") ?: ""
            val normJson = """{"method":"${norm.method}","cx":${norm.cx},"cy":${norm.cy},""" +
                """"r":${norm.r},"crop_side":${norm.cropSide},"margin_px":${norm.marginPx},""" +
                """"error":"$safeError"}"""

            val ctx = captureContext
            val cropFile: java.io.File
            val rawFile: java.io.File
            val metaFile: java.io.File
            val meta: String

            if (ctx != null) {
                // Capture mode (Phase 0 golden-set): write under eval_real/<eurioId>/.
                val dir = java.io.File(root, "eval_real/${ctx.eurioId}").apply { mkdirs() }
                cropFile = java.io.File(dir, "${ctx.stepId}_crop.jpg")
                rawFile = java.io.File(dir, "${ctx.stepId}_raw.jpg")
                metaFile = java.io.File(dir, "${ctx.stepId}.json")
                val safeLabel = ctx.stepLabel.replace("\"", "\\\"")
                meta = """{"ts":"$ts","eurio_id":"${ctx.eurioId}",""" +
                    """"step_id":"${ctx.stepId}","step_label":"$safeLabel",""" +
                    """"step_index":${ctx.stepIndex},""" +
                    """"frame_size":[$frameW,$frameH],"crop_size":$cropSize,""" +
                    """"rerank_ms":$rerankMs,"normalize":$normJson,"matches":$matchesJson}"""
            } else {
                val dir = java.io.File(root, "snaps/snap_$ts").apply { mkdirs() }
                cropFile = java.io.File(dir, "crop.jpg")
                rawFile = java.io.File(dir, "raw.jpg")
                metaFile = java.io.File(dir, "meta.json")
                meta = """{"ts":"$ts","frame_size":[$frameW,$frameH],""" +
                    """"crop_size":$cropSize,"rerank_ms":$rerankMs,"normalize":$normJson,"matches":$matchesJson}"""
            }

            // Stale-state hygiene: a previous run may have left a crop here when
            // Hough succeeded; if this run failed, drop it so the absence of a
            // crop file matches the absence of a normalized output.
            if (masked == null && cropFile.exists()) cropFile.delete()
            if (masked != null) {
                cropFile.outputStream().use { masked.compress(Bitmap.CompressFormat.JPEG, 95, it) }
            }
            rawFile.outputStream().use { raw.compress(Bitmap.CompressFormat.JPEG, 90, it) }
            metaFile.writeText(meta)
            if (masked != null) cropFile.absolutePath else null
        } catch (e: Exception) {
            Log.e("CoinAnalyzer", "Snap save failed", e)
            null
        }
    }

    private fun analyzeBitmap(bitmap: Bitmap): ScanResult {
        val frameW = bitmap.width
        val frameH = bitmap.height

        var detections: List<Detection> = emptyList()
        var yoloInferMs = 0L
        var yoloTotalMs = 0L
        var yoloKept = 0
        var rawYolo = 0
        var houghInferMs = 0L
        var houghRan = false
        var houghKept = 0
        var dedupCount = 0
        var lbScale = 0f
        var lbPadX = 0
        var lbPadY = 0

        // -------- Stage 1: Detection (YOLO ∪ Hough merged) --------
        if (useDetector && detector != null) {
            val batch = detector.detect(bitmap, detectionThreshold)
            detections = batch.detections
            yoloInferMs = batch.yoloInferenceMs
            yoloTotalMs = batch.yoloTotalMs
            yoloKept = batch.yoloKeptCount
            rawYolo = batch.rawAboveThreshold
            houghInferMs = batch.houghInferenceMs
            houghRan = batch.houghRan
            houghKept = batch.houghKeptCount
            dedupCount = batch.mergeDedupCount
            lbScale = batch.letterboxScale
            lbPadX = batch.letterboxPadX
            lbPadY = batch.letterboxPadY
        }

        // -------- Stage 2: Rerank ALL merged candidates via ArcFace --------
        var selectedIndex = -1
        var matches: List<CoinMatch> = emptyList()
        var rerankMs = 0L
        var rerankTop1s: List<Float> = emptyList()
        var rerankTop2s: List<Float> = emptyList()
        var rerankRejectedAll = false
        var rerankDecisionReason = ""
        var perCandidateMatches: List<List<CoinMatch>> = emptyList()

        if (detections.isNotEmpty()) {
            val rerankStart = System.currentTimeMillis()
            val top1s = mutableListOf<Float>()
            val top2s = mutableListOf<Float>()
            val pcm = mutableListOf<List<CoinMatch>>()

            detections.forEach { det ->
                // Padding adapts to the detection source: Hough needs more to capture
                // the outer ring of bimetal coins; YOLO's bbox is already tight.
                val pad = if (det.source == DetectionSource.HOUGH) 0.25f else 0.10f
                val crop = cropDetection(bitmap, det.bbox, padRatio = pad)
                val candMatches = identifyCrop(crop)
                crop.recycle()
                pcm.add(candMatches)
                top1s.add(candMatches.getOrNull(0)?.similarity ?: Float.NEGATIVE_INFINITY)
                top2s.add(candMatches.getOrNull(1)?.similarity ?: Float.NEGATIVE_INFINITY)
            }
            rerankMs = System.currentTimeMillis() - rerankStart
            rerankTop1s = top1s
            rerankTop2s = top2s
            perCandidateMatches = pcm

            // Pick the candidate with the highest top1 similarity.
            var bestIdx = -1
            var bestTop1 = Float.NEGATIVE_INFINITY
            top1s.forEachIndexed { i, s -> if (s > bestTop1) { bestTop1 = s; bestIdx = i } }
            val bestTop2 = top2s.getOrNull(bestIdx) ?: Float.NEGATIVE_INFINITY
            val spread = bestTop1 - bestTop2

            // Decision rule (see plan, fix ③):
            //   absolute_ok    = top1 > 0.20
            //   confident_alone = top1 > 0.55           → accept regardless of spread
            //   clear_winner    = top1 > 0.20 AND spread > 0.08
            //   accepted        = absolute_ok AND (confident_alone OR clear_winner)
            val absoluteOk = bestTop1 > RERANK_TOP1_MIN
            val confidentAlone = bestTop1 > RERANK_CONFIDENT_ALONE
            val clearWinner = absoluteOk && spread > RERANK_SPREAD_MIN
            val accepted = absoluteOk && (confidentAlone || clearWinner)

            rerankDecisionReason = when {
                !absoluteOk -> "REJECTED top1=${"%.2f".format(bestTop1)} < ${RERANK_TOP1_MIN} (garbage floor)"
                confidentAlone -> "ACCEPTED top1=${"%.2f".format(bestTop1)} ≥ ${RERANK_CONFIDENT_ALONE} (confident_alone)"
                clearWinner -> "ACCEPTED top1=${"%.2f".format(bestTop1)} spread=${"%.2f".format(spread)} > ${RERANK_SPREAD_MIN} (clear_winner)"
                else -> "REJECTED top1=${"%.2f".format(bestTop1)} spread=${"%.2f".format(spread)} (mid-range without spread)"
            }

            if (accepted) {
                selectedIndex = bestIdx
                matches = pcm[bestIdx]
                Log.d("CoinAnalyzer", "Rerank: $rerankDecisionReason → pick #${bestIdx + 1}/${detections.size}")
            } else {
                rerankRejectedAll = true
                Log.d("CoinAnalyzer", "Rerank: $rerankDecisionReason → miss")
            }
        }

        // -------- Stage 3: Produce crop + capture debug frames --------
        val coinBitmap: Bitmap
        var cropW = 0
        var cropH = 0
        if (selectedIndex >= 0) {
            val best = detections[selectedIndex]
            val pad = if (best.source == DetectionSource.HOUGH) 0.25f else 0.10f
            coinBitmap = cropDetection(bitmap, best.bbox, padRatio = pad)
            cropW = coinBitmap.width
            cropH = coinBitmap.height

            Log.d(
                "CoinAnalyzer",
                "DET[${best.source}]: sel=${selectedIndex + 1}/${detections.size} conf=${"%.2f".format(best.confidence)} " +
                    "bbox=[${best.bbox.left.toInt()},${best.bbox.top.toInt()},${best.bbox.right.toInt()},${best.bbox.bottom.toInt()}] " +
                    "crop=${coinBitmap.width}x${coinBitmap.height} frame=${frameW}x${frameH} " +
                    "merge=yolo=${yoloKept}+hough=${houghKept}(-${dedupCount})"
            )
        } else {
            coinBitmap = bitmap
        }

        // Continuous record mode: dump full pipeline state (frame + JSONL).
        maybeRecordFrame(
            bitmap = bitmap,
            cropBitmap = if (coinBitmap !== bitmap) coinBitmap else null,
            detections = detections,
            selectedIndex = selectedIndex,
            perCandidateMatches = perCandidateMatches,
            rerankTop1s = rerankTop1s,
            rerankTop2s = rerankTop2s,
            decisionReason = rerankDecisionReason,
            yoloInferMs = yoloInferMs,
            yoloTotalMs = yoloTotalMs,
            yoloKept = yoloKept,
            rawYolo = rawYolo,
            houghInferMs = houghInferMs,
            houghKept = houghKept,
            dedupCount = dedupCount,
            rerankMs = rerankMs,
            frameW = frameW,
            frameH = frameH,
            lbScale = lbScale,
            lbPadX = lbPadX,
            lbPadY = lbPadY,
        )

        if (coinBitmap !== bitmap) {
            coinBitmap.recycle()
        }

        return ScanResult(
            matches = matches,
            yoloInferenceMs = yoloInferMs,
            yoloTotalMs = yoloTotalMs,
            yoloKeptCount = yoloKept,
            houghInferenceMs = houghInferMs,
            houghRan = houghRan,
            houghKeptCount = houghKept,
            mergeDedupCount = dedupCount,
            rawYoloCount = rawYolo,
            rerankMs = rerankMs,
            rerankSimilaritiesTop1 = rerankTop1s,
            rerankSimilaritiesTop2 = rerankTop2s,
            rerankRejectedAll = rerankRejectedAll,
            rerankDecisionReason = rerankDecisionReason,
            identificationInferenceMs = rerankMs,  // rerank includes the winner's inference
            detections = detections,
            selectedDetectionIndex = selectedIndex,
            frameWidth = frameW,
            frameHeight = frameH,
            cropWidth = cropW,
            cropHeight = cropH,
            letterboxScale = lbScale,
            letterboxPadX = lbPadX,
            letterboxPadY = lbPadY,
        )
    }

    private fun maybeRecordFrame(
        bitmap: Bitmap,
        cropBitmap: Bitmap?,
        detections: List<Detection>,
        selectedIndex: Int,
        perCandidateMatches: List<List<CoinMatch>>,
        rerankTop1s: List<Float>,
        rerankTop2s: List<Float>,
        decisionReason: String,
        yoloInferMs: Long,
        yoloTotalMs: Long,
        yoloKept: Int,
        rawYolo: Int,
        houghInferMs: Long,
        houghKept: Int,
        dedupCount: Int,
        rerankMs: Long,
        frameW: Int,
        frameH: Int,
        lbScale: Float,
        lbPadX: Int,
        lbPadY: Int,
    ) {
        val sessionDir = recordSessionDir ?: return
        if (!recordMode) return

        val idx = recordFrameIndex.incrementAndGet()
        val name = "frame_${"%06d".format(idx)}"
        try {
            // Raw frame
            java.io.File(sessionDir, "$name.jpg").outputStream().use {
                bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it)
            }
            // Annotated frame (with bboxes)
            val annotated = drawYoloOverlay(bitmap, detections, selectedIndex)
            java.io.File(sessionDir, "${name}_annotated.jpg").outputStream().use {
                annotated.compress(Bitmap.CompressFormat.JPEG, 90, it)
            }
            annotated.recycle()
            // Crop, if any
            if (cropBitmap != null) {
                java.io.File(sessionDir, "${name}_crop.jpg").outputStream().use {
                    cropBitmap.compress(Bitmap.CompressFormat.JPEG, 90, it)
                }
            }
            // JSONL line — full pipeline state
            val line = buildFrameJson(
                idx = idx,
                detections = detections,
                selectedIndex = selectedIndex,
                perCandidateMatches = perCandidateMatches,
                rerankTop1s = rerankTop1s,
                rerankTop2s = rerankTop2s,
                decisionReason = decisionReason,
                yoloInferMs = yoloInferMs,
                yoloTotalMs = yoloTotalMs,
                yoloKept = yoloKept,
                rawYolo = rawYolo,
                houghInferMs = houghInferMs,
                houghKept = houghKept,
                dedupCount = dedupCount,
                rerankMs = rerankMs,
                frameW = frameW,
                frameH = frameH,
                lbScale = lbScale,
                lbPadX = lbPadX,
                lbPadY = lbPadY,
            )
            java.io.File(sessionDir, "session.jsonl").appendText(line + "\n")
            recordedFrameCount = idx
        } catch (e: Exception) {
            Log.e("CoinAnalyzer", "Record frame failed", e)
        }
    }

    private fun buildFrameJson(
        idx: Int,
        detections: List<Detection>,
        selectedIndex: Int,
        perCandidateMatches: List<List<CoinMatch>>,
        rerankTop1s: List<Float>,
        rerankTop2s: List<Float>,
        decisionReason: String,
        yoloInferMs: Long,
        yoloTotalMs: Long,
        yoloKept: Int,
        rawYolo: Int,
        houghInferMs: Long,
        houghKept: Int,
        dedupCount: Int,
        rerankMs: Long,
        frameW: Int,
        frameH: Int,
        lbScale: Float,
        lbPadX: Int,
        lbPadY: Int,
    ): String {
        fun f(x: Float) = "%.4f".format(java.util.Locale.US, x)
        fun esc(s: String) = s.replace("\\", "\\\\").replace("\"", "\\\"")

        val candidatesJson = detections.mapIndexed { i, det ->
            val matches = perCandidateMatches.getOrNull(i).orEmpty()
            val matchesJson = matches.joinToString(",", "[", "]") { m ->
                """{"class":"${esc(m.className)}","sim":${f(m.similarity)}}"""
            }
            val top1 = rerankTop1s.getOrNull(i) ?: Float.NaN
            val top2 = rerankTop2s.getOrNull(i) ?: Float.NaN
            """{"idx":$i,"source":"${det.source}","conf":${f(det.confidence)},""" +
                """"bbox":[${det.bbox.left.toInt()},${det.bbox.top.toInt()},${det.bbox.right.toInt()},${det.bbox.bottom.toInt()}],""" +
                """"top1":${f(top1)},"top2":${f(top2)},"matches":$matchesJson}"""
        }.joinToString(",", "[", "]")

        return """{"frame":$idx,"ts":${System.currentTimeMillis()},""" +
            """"frame_size":[$frameW,$frameH],""" +
            """"letterbox":{"scale":${f(lbScale)},"pad_x":$lbPadX,"pad_y":$lbPadY},""" +
            """"yolo":{"raw_above_thr":$rawYolo,"kept":$yoloKept,"infer_ms":$yoloInferMs,"total_ms":$yoloTotalMs},""" +
            """"hough":{"kept":$houghKept,"infer_ms":$houghInferMs},""" +
            """"merge":{"dedup":$dedupCount,"final":${detections.size}},""" +
            """"rerank":{"ms":$rerankMs,"selected":$selectedIndex,"reason":"${esc(decisionReason)}"},""" +
            """"candidates":$candidatesJson}"""
    }

    /**
     * Crop the detected coin from the frame with padding around the bbox.
     * Default 10% for YOLO (already tight). Use 25% for Hough (inner-disc on bimetal coins).
     */
    private fun cropDetection(bitmap: Bitmap, bbox: RectF, padRatio: Float = 0.10f): Bitmap {
        val padX = (bbox.width() * padRatio).toInt()
        val padY = (bbox.height() * padRatio).toInt()

        val left = (bbox.left.toInt() - padX).coerceAtLeast(0)
        val top = (bbox.top.toInt() - padY).coerceAtLeast(0)
        val right = (bbox.right.toInt() + padX).coerceAtMost(bitmap.width)
        val bottom = (bbox.bottom.toInt() + padY).coerceAtMost(bitmap.height)

        val width = (right - left).coerceAtLeast(1)
        val height = (bottom - top).coerceAtLeast(1)

        return Bitmap.createBitmap(bitmap, left, top, width, height)
    }

    /**
     * Run identification (ArcFace embed + match, or classification) on a crop.
     */
    private fun identifyCrop(crop: Bitmap): List<CoinMatch> {
        return if (useEmbeddings && matcher != null) {
            val embedding = recognizer.infer(crop)
            matcher.match(embedding, topK = 3)
        } else {
            recognizer.classify(crop)
        }
    }

    /**
     * Draw every detection bbox + confidence label on a copy of the frame.
     * The selected detection (used for identification) is drawn with a thicker stroke.
     */
    private fun drawYoloOverlay(src: Bitmap, detections: List<Detection>, selectedIndex: Int): Bitmap {
        val out = src.copy(Bitmap.Config.ARGB_8888, true)
        if (detections.isEmpty()) return out
        val canvas = Canvas(out)
        val textSize = (out.width.coerceAtLeast(out.height) * 0.035f).coerceAtLeast(24f)
        val baseStroke = (out.width.coerceAtLeast(out.height) * 0.006f).coerceAtLeast(4f)

        detections.forEachIndexed { index, det ->
            val color = when {
                det.confidence > 0.7f -> AndroidColor.rgb(76, 175, 80)
                det.confidence > 0.5f -> AndroidColor.rgb(255, 152, 0)
                else -> AndroidColor.rgb(244, 67, 54)
            }
            // Selected detection = thicker stroke
            val strokeWidth = if (index == selectedIndex) baseStroke * 1.6f else baseStroke

            val boxPaint = Paint().apply {
                this.color = color
                style = Paint.Style.STROKE
                this.strokeWidth = strokeWidth
                isAntiAlias = true
            }
            canvas.drawRect(det.bbox, boxPaint)

            val label = "${det.source} ${(det.confidence * 100).toInt()}%"
            val textPaint = Paint().apply {
                this.color = AndroidColor.WHITE
                this.textSize = textSize
                isAntiAlias = true
                typeface = Typeface.DEFAULT_BOLD
            }
            val bgPaint = Paint().apply {
                this.color = color
                style = Paint.Style.FILL
                isAntiAlias = true
            }
            val textWidth = textPaint.measureText(label)
            val padding = textSize * 0.3f
            val labelLeft = det.bbox.left
            val labelBottom = (det.bbox.top - padding).coerceAtLeast(textSize + padding)
            val labelTop = labelBottom - textSize - padding
            canvas.drawRect(
                labelLeft,
                labelTop,
                labelLeft + textWidth + padding * 2,
                labelBottom,
                bgPaint,
            )
            canvas.drawText(label, labelLeft + padding, labelBottom - padding * 0.6f, textPaint)
        }

        return out
    }

    private fun imageProxyToBitmap(imageProxy: ImageProxy): Bitmap? {
        val yBuffer = imageProxy.planes[0].buffer
        val uBuffer = imageProxy.planes[1].buffer
        val vBuffer = imageProxy.planes[2].buffer

        val ySize = yBuffer.remaining()
        val uSize = uBuffer.remaining()
        val vSize = vBuffer.remaining()

        val nv21 = ByteArray(ySize + uSize + vSize)
        yBuffer.get(nv21, 0, ySize)
        vBuffer.get(nv21, ySize, vSize)
        uBuffer.get(nv21, ySize + vSize, uSize)

        val yuvImage = YuvImage(nv21, ImageFormat.NV21, imageProxy.width, imageProxy.height, null)
        val out = ByteArrayOutputStream()
        yuvImage.compressToJpeg(Rect(0, 0, imageProxy.width, imageProxy.height), 85, out)
        val jpegBytes = out.toByteArray()
        val bitmap = BitmapFactory.decodeByteArray(jpegBytes, 0, jpegBytes.size) ?: return null

        val rotation = imageProxy.imageInfo.rotationDegrees
        if (rotation == 0) return bitmap

        val matrix = Matrix().apply { postRotate(rotation.toFloat()) }
        val rotated = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
        bitmap.recycle()
        return rotated
    }
}
