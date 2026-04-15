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

    /** Set to true to save the next frame + crop to disk. Reset automatically after capture. */
    @Volatile
    var captureNextFrame: Boolean = false

    /** Directory to save debug captures. Must be set by the activity. */
    var captureDir: java.io.File? = null

    /** Timestamp to use for capture filenames. Set by the activity before triggering capture. */
    @Volatile
    var captureTimestamp: String? = null

    /** Files saved during the last capture (populated after capture completes). */
    @Volatile
    var lastCapturedFiles: List<String> = emptyList()

    private var lastAnalyzedTimestamp = 0L

    override fun analyze(imageProxy: ImageProxy) {
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

        if (detections.isNotEmpty()) {
            val rerankStart = System.currentTimeMillis()
            val top1s = mutableListOf<Float>()
            val top2s = mutableListOf<Float>()
            val perCandidateMatches = mutableListOf<List<CoinMatch>>()

            detections.forEach { det ->
                // Padding adapts to the detection source: Hough needs more to capture
                // the outer ring of bimetal coins; YOLO's bbox is already tight.
                val pad = if (det.source == DetectionSource.HOUGH) 0.25f else 0.10f
                val crop = cropDetection(bitmap, det.bbox, padRatio = pad)
                val candMatches = identifyCrop(crop)
                crop.recycle()
                perCandidateMatches.add(candMatches)
                top1s.add(candMatches.getOrNull(0)?.similarity ?: Float.NEGATIVE_INFINITY)
                top2s.add(candMatches.getOrNull(1)?.similarity ?: Float.NEGATIVE_INFINITY)
            }
            rerankMs = System.currentTimeMillis() - rerankStart
            rerankTop1s = top1s
            rerankTop2s = top2s

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
                matches = perCandidateMatches[bestIdx]
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

        // Save debug frames (always honor capture, even on miss so we can inspect)
        maybeCaptureFrame(bitmap, if (coinBitmap !== bitmap) coinBitmap else null, detections, selectedIndex)

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

    private fun maybeCaptureFrame(
        bitmap: Bitmap,
        coinBitmap: Bitmap?,
        detections: List<Detection>,
        selectedIndex: Int,
    ) {
        if (!captureNextFrame || captureDir == null) return
        captureNextFrame = false
        val ts = captureTimestamp ?: java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.US).format(java.util.Date())
        captureTimestamp = null
        val savedFiles = mutableListOf<String>()
        try {
            // Raw frame
            val frameName = "frame_$ts.jpg"
            val frameFile = java.io.File(captureDir, frameName)
            frameFile.outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG, 95, it) }
            savedFiles.add(frameName)
            // Annotated frame — always saved (even if no detection) so we see what YOLO saw
            val annotated = drawYoloOverlay(bitmap, detections, selectedIndex)
            val annotatedName = "frame_annotated_$ts.jpg"
            val annotatedFile = java.io.File(captureDir, annotatedName)
            annotatedFile.outputStream().use { annotated.compress(android.graphics.Bitmap.CompressFormat.JPEG, 95, it) }
            annotated.recycle()
            savedFiles.add(annotatedName)
            // Crop (when a coin was actually cropped out)
            if (coinBitmap != null) {
                val cropName = "crop_$ts.jpg"
                val cropFile = java.io.File(captureDir, cropName)
                cropFile.outputStream().use { coinBitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG, 95, it) }
                savedFiles.add(cropName)
            }
            Log.d("CoinAnalyzer", "Frame captured: $frameName (${detections.size} detections)")
        } catch (e: Exception) {
            Log.e("CoinAnalyzer", "Frame capture failed", e)
        }
        lastCapturedFiles = savedFiles
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
