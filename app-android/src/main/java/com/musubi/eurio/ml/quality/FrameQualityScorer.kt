package com.musubi.eurio.ml.quality

import android.graphics.Bitmap
import com.musubi.eurio.domain.scan.quality.FrameScore
import com.musubi.eurio.domain.scan.quality.GatesResult
import com.musubi.eurio.domain.scan.quality.QualityMath
import com.musubi.eurio.domain.scan.quality.ScoringPolicy
import org.opencv.android.Utils
import org.opencv.core.Core
import org.opencv.core.CvType
import org.opencv.core.Mat
import org.opencv.core.MatOfDouble
import org.opencv.imgproc.Imgproc

/**
 * OpenCV-backed scorer that turns a normalized 224 bitmap + Hough output into
 * a [FrameScore]. Stateless — the caller (`CoinAnalyzer`) keeps the previous
 * detection center for motion scoring.
 *
 * Bit-for-bit faithful to the algorithm in `docs/best-frame-capture/chunk-2.md
 * §Algos détaillés` :
 *
 *  - Sharpness  : `var(Laplacian(gray, CV_64F, ksize=3))` restricted to the
 *                 disc mask (pixels with gray > 5), then divided by
 *                 `policy.sharpnessNormalizationCeiling` and clamped to [0,1].
 *  - Exposure   : mean luminance (gray > 5) + clipping ratio (gray < 4 OR
 *                 gray > 251) inside the disc, combined per [QualityMath].
 *  - Completeness : geometric — depends only on (cx, cy, r) vs frame size.
 *  - Motion     : euclidean center delta / radius vs [previousCenter].
 *
 * Failure semantics: returns [FrameScore.Failed] when the input bitmap is
 * empty or the disc mask covers zero pixels (degenerate input). Per
 * `feedback_no_debt` we never return null — the caller logs the failure as a
 * first-class row instead of silently skipping (chunk-7 replay).
 */
object FrameQualityScorer {

    fun score(
        normalizedCrop: Bitmap,
        houghCx: Int,
        houghCy: Int,
        houghR: Int,
        sourceFrameW: Int,
        sourceFrameH: Int,
        previousCenter: Pair<Float, Float>?,
        policy: ScoringPolicy,
    ): FrameScore {
        if (normalizedCrop.width == 0 || normalizedCrop.height == 0) {
            return FrameScore.Failed
        }

        val src = Mat()
        Utils.bitmapToMat(normalizedCrop, src)
        val gray = Mat()
        val mask = Mat()
        val lap = Mat()
        val laplacianMean = MatOfDouble()
        val laplacianStddev = MatOfDouble()
        val grayMean = MatOfDouble()
        val grayStddev = MatOfDouble()
        try {
            Imgproc.cvtColor(src, gray, Imgproc.COLOR_RGBA2GRAY)
            Imgproc.threshold(gray, mask, 5.0, 255.0, Imgproc.THRESH_BINARY)
            val maskPixels = Core.countNonZero(mask)
            if (maskPixels == 0) {
                return FrameScore.Failed
            }

            // ── Sharpness ─────────────────────────────────────────────────
            Imgproc.Laplacian(gray, lap, CvType.CV_64F, 3, 1.0, 0.0)
            Core.meanStdDev(lap, laplacianMean, laplacianStddev, mask)
            val stddev = laplacianStddev.toArray().firstOrNull() ?: 0.0
            val sharpnessRaw = (stddev * stddev).toFloat()
            val sharpness = QualityMath.normalizeSharpness(sharpnessRaw, policy.sharpnessNormalizationCeiling)
            val sharpnessPasses = sharpnessRaw >= policy.sharpnessMin

            // ── Exposure ──────────────────────────────────────────────────
            Core.meanStdDev(gray, grayMean, grayStddev, mask)
            val meanGray = (grayMean.toArray().firstOrNull() ?: 0.0).toFloat()
            val meanLuminance = (meanGray / 255f).coerceIn(0f, 1f)
            val clippingRatio = countClippingRatio(gray, mask, maskPixels)
            val exposure = QualityMath.exposureScore(
                meanLuminance = meanLuminance,
                clippingRatio = clippingRatio,
                bandHalfWidth = policy.exposureBandHalfWidth,
                clippingMax = policy.clippingMax,
            )
            val exposurePasses = QualityMath.exposurePasses(
                meanLuminance, clippingRatio, policy.exposureBandHalfWidth, policy.clippingMax,
            )

            // ── Completeness ──────────────────────────────────────────────
            val completeness = QualityMath.completeness(
                cx = houghCx, cy = houghCy, r = houghR,
                frameW = sourceFrameW, frameH = sourceFrameH,
            )
            val completenessPasses = completeness >= policy.completenessMin

            // ── Motion (optional) ─────────────────────────────────────────
            val motion: Float?
            val motionPasses: Boolean?
            if (policy.motionEnabled) {
                motion = QualityMath.motion(previousCenter, houghCx, houghCy, houghR, policy.motionMax)
                motionPasses = QualityMath.motionPasses(previousCenter, houghCx, houghCy, houghR, policy.motionMax)
            } else {
                motion = null
                motionPasses = null
            }

            val aggregate = QualityMath.aggregate(sharpness, exposure, completeness, motion, policy)
            val all = sharpnessPasses && exposurePasses && completenessPasses &&
                (motionPasses ?: true)

            return FrameScore(
                sharpness = sharpness,
                sharpnessRaw = sharpnessRaw,
                exposure = exposure,
                meanLuminance = meanLuminance,
                clippingRatio = clippingRatio,
                completeness = completeness,
                motion = motion,
                aggregate = aggregate,
                passes = GatesResult(
                    sharpness = sharpnessPasses,
                    exposure = exposurePasses,
                    completeness = completenessPasses,
                    motion = motionPasses,
                    all = all,
                ),
            )
        } finally {
            src.release()
            gray.release()
            mask.release()
            lap.release()
            laplacianMean.release()
            laplacianStddev.release()
            grayMean.release()
            grayStddev.release()
        }
    }

    /**
     * Fraction of pixels inside the disc that are at the dark (<4) or bright
     * (>251) extremes. Marge of 4 absorbs JPEG/YUV noise around true black /
     * true white — tunable in chunk-7 if false positives appear on bright
     * reflections.
     */
    private fun countClippingRatio(gray: Mat, mask: Mat, maskPixels: Int): Float {
        if (maskPixels == 0) return 0f
        val dark = Mat()
        val bright = Mat()
        val darkAnd = Mat()
        val brightAnd = Mat()
        try {
            Imgproc.threshold(gray, dark, 4.0, 255.0, Imgproc.THRESH_BINARY_INV)
            Imgproc.threshold(gray, bright, 251.0, 255.0, Imgproc.THRESH_BINARY)
            Core.bitwise_and(dark, mask, darkAnd)
            Core.bitwise_and(bright, mask, brightAnd)
            val clipped = Core.countNonZero(darkAnd) + Core.countNonZero(brightAnd)
            return clipped.toFloat() / maskPixels.toFloat()
        } finally {
            dark.release()
            bright.release()
            darkAnd.release()
            brightAnd.release()
        }
    }
}
