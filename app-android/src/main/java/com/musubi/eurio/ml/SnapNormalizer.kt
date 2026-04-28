package com.musubi.eurio.ml

import android.graphics.Bitmap
import org.opencv.android.Utils
import org.opencv.core.CvType
import org.opencv.core.Mat
import org.opencv.core.Point
import org.opencv.core.Rect
import org.opencv.core.Scalar
import org.opencv.core.Size as CvSize
import org.opencv.imgproc.Imgproc

/**
 * Bit-for-bit Kotlin port of `ml/scan/normalize_snap.py`. Same OpenCV calls,
 * same params, same selection rule — the JPEG produced here on a `_raw.jpg`
 * should be diffable byte-for-byte against `python -m scan.preview_normalized`
 * on the same input (see Phase 4 validation in docs/scan-normalization/).
 *
 * Pipeline (must mirror normalize_snap.py exactly):
 *   1. Median-blurred grayscale.
 *   2. Hough 2-pass: tight precision (rejects most phantoms) then relaxed
 *      recall (small/tilted coins where tight params miss).
 *   3. Selection: drop circles whose center is >30% of the short side away
 *      from the frame center, then pick the **largest** radius among
 *      survivors. The "largest centered" rule is critical for bimetallic
 *      2 EUR coins where Hough scores the inner gold/silver ring higher
 *      than the outer edge — first-by-vote returns the wrong (inner) circle.
 *   4. Square crop tangent to the detected circle + 2% margin, recentered.
 *   5. Mask outside the disk → opaque black (RGBA 0,0,0,255).
 *   6. Resize 224×224 with INTER_AREA.
 *
 * Returned [Result.image] is an ARGB_8888 224×224 bitmap consumable directly
 * by [CoinRecognizer.infer]. On failure (empty input, no centered circle,
 * empty crop) [Result.image] is null and [Result.error] carries the reason —
 * the snap path is expected to write the raw frame + meta and surface the
 * failure in the UI without invoking ArcFace.
 */
object SnapNormalizer {

    private const val OUTPUT_SIZE = 224
    private const val COIN_MARGIN = 0.02f      // margin around detected radius before crop
    private const val CENTER_TOL_FRACTION = 0.30 // max distance from frame center, fraction of short side

    data class Result(
        val image: Bitmap?,
        val cx: Int = 0,
        val cy: Int = 0,
        val r: Int = 0,
        val method: String = "failed",  // "hough_tight" | "hough_relaxed" | "failed"
        val error: String? = null,
        val inputW: Int = 0,
        val inputH: Int = 0,
        val cropSide: Int = 0,
        val marginPx: Int = 0,
    )

    private data class HoughPass(
        val name: String,
        val param1: Double,
        val param2: Double,
        val rMinFrac: Double,
        val rMaxFrac: Double,
    )

    // Same two passes, same params as normalize_snap._detect_coin_circle.
    private val PASSES = listOf(
        HoughPass("hough_tight",   param1 = 100.0, param2 = 30.0, rMinFrac = 0.15, rMaxFrac = 0.55),
        HoughPass("hough_relaxed", param1 =  60.0, param2 = 22.0, rMinFrac = 0.10, rMaxFrac = 0.55),
    )

    /**
     * Lightweight live-detection for the photo-mode ring color feedback.
     * Runs only the Hough stage of [normalize] (same params, same selection
     * rule) and returns whether a centered circle was found — no crop, no
     * mask, no resize, no Mat-to-Bitmap conversion. Designed to be called
     * 5 fps in [CoinAnalyzer]'s photo-mode loop without burning the battery.
     * Returns null when no centered circle is found.
     */
    fun detectCircleOnly(bitmap: Bitmap): Detection? {
        if (bitmap.width == 0 || bitmap.height == 0) return null
        val src = Mat()
        Utils.bitmapToMat(bitmap, src)
        try {
            return detectCoinCircle(src)
        } finally {
            src.release()
        }
    }

    fun normalize(bitmap: Bitmap): Result {
        val w = bitmap.width
        val h = bitmap.height
        if (w == 0 || h == 0) {
            return Result(image = null, error = "empty input", inputW = w, inputH = h)
        }

        val src = Mat()
        Utils.bitmapToMat(bitmap, src)
        try {
            val detection = detectCoinCircle(src) ?: return Result(
                image = null, error = "no circle",
                inputW = w, inputH = h,
            )
            val (cx, cy, r, method) = detection

            val margin = (r * COIN_MARGIN).toInt()
            val half = r + margin
            val x0 = (cx - half).coerceAtLeast(0)
            val y0 = (cy - half).coerceAtLeast(0)
            val x1 = (cx + half).coerceAtMost(w)
            val y1 = (cy + half).coerceAtMost(h)

            // Force a square crop. Image-edge clipping can asymmetrically bias
            // the bbox (e.g. coin near a frame edge), so collapse to the smaller
            // dimension and re-emit a square anchored at (x0, y0). Identical to
            // the `side = min(...); x1, y1 = x0 + side, y0 + side` trick in
            // normalize_snap.py.
            val side = minOf(x1 - x0, y1 - y0)
            if (side <= 0) return Result(
                image = null, error = "empty crop",
                inputW = w, inputH = h,
                cx = cx, cy = cy, r = r, method = method, marginPx = margin,
            )

            val crop = Mat(src, Rect(x0, y0, side, side))
            try {
                val cropCx = cx - x0
                val cropCy = cy - y0

                // Single-channel mask: filled white disk inside, black outside.
                val mask = Mat.zeros(crop.size(), CvType.CV_8UC1)
                try {
                    Imgproc.circle(
                        mask,
                        Point(cropCx.toDouble(), cropCy.toDouble()),
                        r,
                        Scalar(255.0),
                        -1,
                    )

                    // Init destination as opaque black (alpha=255 — matters
                    // only for in-app rendering; JPEG strips alpha and the
                    // model reads R/G/B only). copyTo overwrites where mask>0,
                    // leaving the black init untouched outside the disk.
                    val masked = Mat(crop.size(), crop.type(), Scalar(0.0, 0.0, 0.0, 255.0))
                    try {
                        crop.copyTo(masked, mask)

                        // Resize to 224 with INTER_AREA (same call as Python).
                        val out224 = Mat()
                        try {
                            Imgproc.resize(
                                masked,
                                out224,
                                CvSize(OUTPUT_SIZE.toDouble(), OUTPUT_SIZE.toDouble()),
                                0.0,
                                0.0,
                                Imgproc.INTER_AREA,
                            )
                            val outBitmap = Bitmap.createBitmap(
                                OUTPUT_SIZE,
                                OUTPUT_SIZE,
                                Bitmap.Config.ARGB_8888,
                            )
                            Utils.matToBitmap(out224, outBitmap)

                            return Result(
                                image = outBitmap,
                                cx = cx, cy = cy, r = r, method = method,
                                inputW = w, inputH = h,
                                cropSide = side, marginPx = margin,
                            )
                        } finally {
                            out224.release()
                        }
                    } finally {
                        masked.release()
                    }
                } finally {
                    mask.release()
                }
            } finally {
                crop.release()
            }
        } finally {
            src.release()
        }
    }

    data class Detection(val cx: Int, val cy: Int, val r: Int, val method: String)

    private fun detectCoinCircle(src: Mat): Detection? {
        val w = src.cols()
        val h = src.rows()
        val short = minOf(w, h).toDouble()
        val imgCx = w / 2.0
        val imgCy = h / 2.0
        val centerTol = CENTER_TOL_FRACTION * short
        val centerTolSq = centerTol * centerTol

        val gray = Mat()
        try {
            Imgproc.cvtColor(src, gray, Imgproc.COLOR_RGBA2GRAY)
            Imgproc.medianBlur(gray, gray, 5)

            for (pass in PASSES) {
                val circles = Mat()
                try {
                    Imgproc.HoughCircles(
                        gray,
                        circles,
                        Imgproc.HOUGH_GRADIENT,
                        1.0,                                         // dp
                        short,                                       // minDist
                        pass.param1,                                 // param1 (Canny high)
                        pass.param2,                                 // param2 (accumulator)
                        (short * pass.rMinFrac).toInt(),             // minRadius
                        (short * pass.rMaxFrac).toInt(),             // maxRadius
                    )
                    if (circles.cols() == 0) continue

                    var bestX = 0.0
                    var bestY = 0.0
                    var bestR = -1.0
                    for (i in 0 until circles.cols()) {
                        val data = circles.get(0, i) ?: continue
                        val x = data[0]
                        val y = data[1]
                        val r = data[2]
                        val dx = x - imgCx
                        val dy = y - imgCy
                        if (dx * dx + dy * dy <= centerTolSq && r > bestR) {
                            bestX = x
                            bestY = y
                            bestR = r
                        }
                    }
                    if (bestR > 0) return Detection(
                        cx = bestX.toInt(),
                        cy = bestY.toInt(),
                        r = bestR.toInt(),
                        method = pass.name,
                    )
                } finally {
                    circles.release()
                }
            }
            return null
        } finally {
            gray.release()
        }
    }
}
