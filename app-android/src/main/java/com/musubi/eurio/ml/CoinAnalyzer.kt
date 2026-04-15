package com.musubi.eurio.ml

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.graphics.Rect
import android.graphics.RectF
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
    val inferenceTimeMs: Long,
    val detected: Boolean = false,
    val detectionConfidence: Float = 0f,
    val detectionBbox: android.graphics.RectF? = null,
    val frameWidth: Int = 0,
    val frameHeight: Int = 0,
    val cropSize: String = "",
    val timestamp: Long = System.currentTimeMillis(),
)

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
    private val analyzeIntervalMs: Long = 300L,
    private val detectionThreshold: Float = 0.70f,
) : ImageAnalysis.Analyzer {

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

                onResult(result.copy(inferenceTimeMs = elapsed))
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

        // Stage 1: Detection (if detector is available)
        val coinBitmap: Bitmap
        var detected = false
        var detectionConf = 0f
        var detectionBbox: RectF? = null
        var cropInfo = ""

        if (useDetector && detector != null) {
            val detection = detector.detect(bitmap, detectionThreshold)
            if (detection == null) {
                return ScanResult(
                    matches = emptyList(),
                    inferenceTimeMs = 0,
                    detected = false,
                    frameWidth = frameW,
                    frameHeight = frameH,
                )
            }

            detected = true
            detectionConf = detection.confidence
            detectionBbox = detection.bbox
            coinBitmap = cropDetection(bitmap, detection.bbox)
            cropInfo = "${coinBitmap.width}x${coinBitmap.height}"

            Log.d("CoinAnalyzer", "YOLO: conf=${String.format("%.2f", detectionConf)} bbox=[${detection.bbox.left.toInt()},${detection.bbox.top.toInt()},${detection.bbox.right.toInt()},${detection.bbox.bottom.toInt()}] crop=$cropInfo frame=${frameW}x${frameH}")
        } else {
            coinBitmap = bitmap
        }

        // Save frame + crop if capture requested
        if (captureNextFrame && captureDir != null) {
            captureNextFrame = false
            val ts = captureTimestamp ?: java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.US).format(java.util.Date())
            captureTimestamp = null
            val savedFiles = mutableListOf<String>()
            try {
                // Save full frame
                val frameName = "frame_$ts.jpg"
                val frameFile = java.io.File(captureDir, frameName)
                frameFile.outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG, 95, it) }
                savedFiles.add(frameName)
                // Save crop (if different from frame)
                if (coinBitmap !== bitmap) {
                    val cropName = "crop_$ts.jpg"
                    val cropFile = java.io.File(captureDir, cropName)
                    cropFile.outputStream().use { coinBitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG, 95, it) }
                    savedFiles.add(cropName)
                }
                Log.d("CoinAnalyzer", "Frame captured: $frameName")
            } catch (e: Exception) {
                Log.e("CoinAnalyzer", "Frame capture failed", e)
            }
            lastCapturedFiles = savedFiles
        }

        // Stage 2: Identification
        val matches = if (useEmbeddings && matcher != null) {
            val embedding = recognizer.infer(coinBitmap)
            matcher.match(embedding, topK = 3)
        } else {
            recognizer.classify(coinBitmap)
        }

        if (matches.isNotEmpty()) {
            val top = matches.first()
            Log.d("CoinAnalyzer", "ID: ${top.className} sim=${String.format("%.3f", top.similarity)}")
        }

        if (coinBitmap !== bitmap) {
            coinBitmap.recycle()
        }

        return ScanResult(
            matches = matches,
            inferenceTimeMs = 0,
            detected = detected,
            detectionConfidence = detectionConf,
            detectionBbox = detectionBbox,
            frameWidth = frameW,
            frameHeight = frameH,
            cropSize = cropInfo,
        )
    }

    /**
     * Crop the detected coin from the frame with some padding.
     */
    private fun cropDetection(bitmap: Bitmap, bbox: RectF): Bitmap {
        // Add 10% padding around the detection
        val padX = (bbox.width() * 0.1f).toInt()
        val padY = (bbox.height() * 0.1f).toInt()

        val left = (bbox.left.toInt() - padX).coerceAtLeast(0)
        val top = (bbox.top.toInt() - padY).coerceAtLeast(0)
        val right = (bbox.right.toInt() + padX).coerceAtMost(bitmap.width)
        val bottom = (bbox.bottom.toInt() + padY).coerceAtMost(bitmap.height)

        val width = (right - left).coerceAtLeast(1)
        val height = (bottom - top).coerceAtLeast(1)

        return Bitmap.createBitmap(bitmap, left, top, width, height)
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
