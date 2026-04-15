package com.musubi.eurio.ml

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import org.opencv.android.Utils
import org.opencv.core.Mat
import org.opencv.core.Size as CvSize
import org.opencv.imgproc.Imgproc
import org.tensorflow.lite.Interpreter
import org.tensorflow.lite.support.common.FileUtil
import java.nio.ByteBuffer
import java.nio.ByteOrder
import android.util.Log
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Source that produced a detection — so the debug report can attribute credit.
 */
enum class DetectionSource { YOLO, HOUGH }

/**
 * Single bounding box detection.
 * Coordinates are expressed in the original frame's pixel space.
 */
data class Detection(
    val bbox: RectF,
    val confidence: Float,
    val source: DetectionSource = DetectionSource.YOLO,
)

/**
 * Result of running the detector on one frame.
 */
data class DetectionBatch(
    val detections: List<Detection>,     // post-merge, sorted by confidence desc, cap 5
    val yoloKeptCount: Int,               // YOLO detections after NMS
    val houghKeptCount: Int,              // Hough detections (after radius filtering)
    val rawAboveThreshold: Int,           // raw YOLO candidates count before NMS
    val yoloInferenceMs: Long,            // YOLO interpreter.run() time
    val yoloTotalMs: Long,                // YOLO preprocess + infer + NMS
    val houghInferenceMs: Long,           // Hough call time
    val houghRan: Boolean,                // Hough was actually executed
    val mergeDedupCount: Int,             // how many Hough candidates were dedup'd against YOLO
    val totalMs: Long,                    // end-to-end detect() time
    val modelInputSize: Int,
    val letterboxScale: Float,
    val letterboxPadX: Int,
    val letterboxPadY: Int,
)

/**
 * YOLOv8-nano coin detector — detects whether there is a coin in the frame
 * and returns its bounding box.
 *
 * Input:  320×320 RGB image
 * Output: bounding boxes with confidence scores
 */
class CoinDetector(
    context: Context,
    val modelPath: String = "models/coin_detector.tflite",
) {
    private val interpreter: Interpreter
    val inputSize = 320

    init {
        val model = FileUtil.loadMappedFile(context, modelPath)
        interpreter = Interpreter(model)
    }

    /**
     * Detect all coins in a bitmap. Returns a batch with every detection kept
     * after NMS, plus timing and letterbox metadata for debug.
     *
     * Model output is [1, 5, 2100] (raw YOLO11-nano without NMS):
     *   row 0 = x_center, row 1 = y_center, row 2 = width, row 3 = height, row 4 = confidence
     * Coordinates are in 320×320 letterboxed pixel space.
     */
    fun detect(
        bitmap: Bitmap,
        confidenceThreshold: Float = 0.40f,
        iouThreshold: Float = 0.45f,
        runHough: Boolean = true,
        finalCap: Int = 5,
    ): DetectionBatch {
        val totalStart = System.currentTimeMillis()
        // Letterbox: preserve aspect ratio, pad with gray 114 (Ultralytics convention).
        val srcW = bitmap.width
        val srcH = bitmap.height
        val scale = min(inputSize.toFloat() / srcW, inputSize.toFloat() / srcH)
        val newW = (srcW * scale).roundToInt()
        val newH = (srcH * scale).roundToInt()
        val padX = (inputSize - newW) / 2f
        val padY = (inputSize - newH) / 2f

        val input = preprocessLetterbox(bitmap, newW, newH, padX.toInt(), padY.toInt())

        val outputTensor = interpreter.getOutputTensor(0)
        val outputShape = outputTensor.shape() // [1, 5, 2100]
        val numChannels = outputShape[1]       // 5
        val numPredictions = outputShape[2]    // 2100

        val output = Array(1) { Array(numChannels) { FloatArray(numPredictions) } }
        val inferStart = System.currentTimeMillis()
        interpreter.run(input, output)
        val inferenceMs = System.currentTimeMillis() - inferStart

        val raw = output[0] // [5][2100]

        // Collect every candidate above threshold (in original frame coords).
        val candidates = ArrayList<Detection>()
        for (i in 0 until numPredictions) {
            val conf = raw[4][i]
            if (conf < confidenceThreshold) continue
            val cx = (raw[0][i] - padX) / scale
            val cy = (raw[1][i] - padY) / scale
            val w = raw[2][i] / scale
            val h = raw[3][i] / scale
            candidates.add(
                Detection(
                    bbox = RectF(
                        (cx - w / 2).coerceAtLeast(0f),
                        (cy - h / 2).coerceAtLeast(0f),
                        (cx + w / 2).coerceAtMost(srcW.toFloat()),
                        (cy + h / 2).coerceAtMost(srcH.toFloat()),
                    ),
                    confidence = conf,
                )
            )
        }

        val rawAboveThreshold = candidates.size
        val yoloKept = nonMaxSuppression(candidates, iouThreshold)
        val yoloTotalMs = System.currentTimeMillis() - totalStart

        // Unified pipeline: Hough runs in parallel with YOLO (same frame), and its
        // candidates are merged via IoU-based dedup. YOLO wins on overlaps because
        // it's a real ML model vs geometric guess.
        var houghInferenceMs = 0L
        var houghRan = false
        var houghKept: List<Detection> = emptyList()
        if (runHough) {
            houghRan = true
            val houghStart = System.currentTimeMillis()
            houghKept = detectWithHough(bitmap)
            houghInferenceMs = System.currentTimeMillis() - houghStart
        }

        // Merge: start with all YOLO, then add Hough candidates that don't overlap.
        val merged = ArrayList<Detection>(yoloKept)
        var dedupCount = 0
        for (hough in houghKept) {
            val overlapsYolo = yoloKept.any { iou(it.bbox, hough.bbox) > 0.60f }
            if (overlapsYolo) {
                dedupCount++
            } else {
                merged.add(hough)
            }
        }

        // Cap at finalCap, sorted by confidence desc (mostly for display ordering;
        // ArcFace rerank downstream is the real decision maker).
        val finalDetections = merged.sortedByDescending { it.confidence }.take(finalCap)

        return DetectionBatch(
            detections = finalDetections,
            yoloKeptCount = yoloKept.size,
            houghKeptCount = houghKept.size,
            rawAboveThreshold = rawAboveThreshold,
            yoloInferenceMs = inferenceMs,
            yoloTotalMs = yoloTotalMs,
            houghInferenceMs = houghInferenceMs,
            houghRan = houghRan,
            mergeDedupCount = dedupCount,
            totalMs = System.currentTimeMillis() - totalStart,
            modelInputSize = inputSize,
            letterboxScale = scale,
            letterboxPadX = padX.toInt(),
            letterboxPadY = padY.toInt(),
        )
    }

    /**
     * OpenCV Hough Circle Transform fallback. Runs only when YOLO returns nothing.
     *
     * Strategy:
     * - Returns up to [topK] candidates ranked by a geometric score (size + centrality).
     * - Caller (CoinAnalyzer) is expected to rerank these using ArcFace similarity to
     *   the coin catalog, so geometric order is NOT final — it's a shortlist.
     * - Hard radius ceiling at 30% of frame short side rejects the "laptop/screen
     *   false positive" case where Hough hooks onto the device chassis.
     */
    private fun detectWithHough(bitmap: Bitmap, topK: Int = 5): List<Detection> {
        val srcW = bitmap.width
        val srcH = bitmap.height
        val shortSide = minOf(srcW, srcH)

        // Downscale to ~640 on the short side for Hough speed. We rescale results back.
        val targetShort = 640
        val houghScale = if (shortSide > targetShort) targetShort.toFloat() / shortSide else 1f
        val workW = (srcW * houghScale).roundToInt()
        val workH = (srcH * houghScale).roundToInt()

        val srcMat = Mat()
        val work = if (houghScale < 1f) {
            val scaled = Bitmap.createScaledBitmap(bitmap, workW, workH, true)
            Utils.bitmapToMat(scaled, srcMat)
            if (scaled !== bitmap) scaled.recycle()
            srcMat
        } else {
            Utils.bitmapToMat(bitmap, srcMat)
            srcMat
        }

        val gray = Mat()
        Imgproc.cvtColor(work, gray, Imgproc.COLOR_RGBA2GRAY)
        Imgproc.medianBlur(gray, gray, 5)

        val workShort = minOf(workW, workH)
        val minRadius = (workShort * 0.08).toInt()   // loosened from 10%
        val maxRadius = (workShort * 0.30).toInt()   // tightened from 45% — rejects laptop chassis
        val minDist = (workShort * 0.25).toDouble()  // allow closer circles (for topK)

        val circles = Mat()
        Imgproc.HoughCircles(
            gray,
            circles,
            Imgproc.HOUGH_GRADIENT,
            1.0,
            minDist,
            100.0,   // Canny high threshold
            28.0,    // accumulator threshold — slightly lower for more recall
            minRadius,
            maxRadius,
        )

        val detections = mutableListOf<Detection>()
        if (circles.cols() > 0) {
            val workCx = workW / 2f
            val workCy = workH / 2f
            val diag = hypot(workW.toFloat(), workH.toFloat())

            data class Candidate(val x: Float, val y: Float, val r: Float, val score: Float)
            val ranked = (0 until circles.cols()).map { i ->
                val data = circles[0, i]
                val x = data[0].toFloat()
                val y = data[1].toFloat()
                val r = data[2].toFloat()
                val centerDist = hypot(x - workCx, y - workCy) / diag  // 0..1
                val sizeScore = r / workShort                          // 0..0.30
                val score = sizeScore * 2f - centerDist
                Candidate(x, y, r, score)
            }.sortedByDescending { it.score }.take(topK)

            val invScale = 1f / houghScale
            ranked.forEach { c ->
                val cx = c.x * invScale
                val cy = c.y * invScale
                val r = c.r * invScale

                // Hard rejection: radius > 30% of frame short side is almost certainly
                // a false positive (laptop chassis, screen frame, table edge).
                val radiusFraction = r / shortSide.toFloat()
                if (radiusFraction > 0.30f) return@forEach

                // Synthetic confidence: 0.50 base + geometric score bump.
                val confidence = (0.50f + c.score * 0.3f).coerceIn(0.40f, 0.85f)

                detections.add(
                    Detection(
                        bbox = RectF(
                            (cx - r).coerceAtLeast(0f),
                            (cy - r).coerceAtLeast(0f),
                            (cx + r).coerceAtMost(srcW.toFloat()),
                            (cy + r).coerceAtMost(srcH.toFloat()),
                        ),
                        confidence = confidence,
                        source = DetectionSource.HOUGH,
                    )
                )
            }
        }

        circles.release()
        gray.release()
        srcMat.release()
        return detections
    }

    /**
     * Greedy Non-Max Suppression. Sort by confidence desc, keep the best,
     * suppress any remaining box whose IoU with the kept one exceeds the threshold.
     */
    private fun nonMaxSuppression(detections: List<Detection>, iouThreshold: Float): List<Detection> {
        if (detections.isEmpty()) return emptyList()
        val sorted = detections.sortedByDescending { it.confidence }.toMutableList()
        val kept = ArrayList<Detection>()
        while (sorted.isNotEmpty()) {
            val best = sorted.removeAt(0)
            kept.add(best)
            sorted.removeAll { iou(best.bbox, it.bbox) > iouThreshold }
        }
        return kept
    }

    private fun iou(a: RectF, b: RectF): Float {
        val interLeft = maxOf(a.left, b.left)
        val interTop = maxOf(a.top, b.top)
        val interRight = minOf(a.right, b.right)
        val interBottom = minOf(a.bottom, b.bottom)
        val interW = (interRight - interLeft).coerceAtLeast(0f)
        val interH = (interBottom - interTop).coerceAtLeast(0f)
        val interArea = interW * interH
        val aArea = (a.right - a.left) * (a.bottom - a.top)
        val bArea = (b.right - b.left) * (b.bottom - b.top)
        val union = aArea + bArea - interArea
        return if (union <= 0f) 0f else interArea / union
    }

    private fun preprocessLetterbox(
        bitmap: Bitmap,
        newW: Int,
        newH: Int,
        padX: Int,
        padY: Int,
    ): ByteBuffer {
        // Create a 320×320 canvas filled with gray 114 and paint the resized source centered.
        val canvasBitmap = Bitmap.createBitmap(inputSize, inputSize, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(canvasBitmap)
        canvas.drawColor(Color.rgb(114, 114, 114))
        val dst = Rect(padX, padY, padX + newW, padY + newH)
        canvas.drawBitmap(bitmap, null, dst, Paint(Paint.FILTER_BITMAP_FLAG))

        val pixels = IntArray(inputSize * inputSize)
        canvasBitmap.getPixels(pixels, 0, inputSize, 0, 0, inputSize, inputSize)

        // NHWC [1, 320, 320, 3], float32, normalized [0,1].
        val buffer = ByteBuffer.allocateDirect(1 * inputSize * inputSize * 3 * 4)
        buffer.order(ByteOrder.nativeOrder())
        for (pixel in pixels) {
            buffer.putFloat(((pixel shr 16) and 0xFF) / 255f) // R
            buffer.putFloat(((pixel shr 8) and 0xFF) / 255f)  // G
            buffer.putFloat((pixel and 0xFF) / 255f)           // B
        }
        buffer.rewind()
        canvasBitmap.recycle()
        return buffer
    }

    fun close() {
        interpreter.close()
    }
}
