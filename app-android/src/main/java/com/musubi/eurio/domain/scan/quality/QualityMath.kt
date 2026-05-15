package com.musubi.eurio.domain.scan.quality

import kotlin.math.abs
import kotlin.math.hypot

/**
 * Stateless pure-math helpers used by [com.musubi.eurio.ml.quality.FrameQualityScorer].
 *
 * Lives in `domain/scan/quality/` (no OpenCV, no Android) so it's testable on
 * the JVM and reusable by future bench tooling. The OpenCV-dependent pieces
 * (Laplacian variance, mean / clipping over a masked region) sit in
 * `ml/quality/` and feed their raw outputs into these functions.
 */
internal object QualityMath {

    /** Normalize raw Laplacian variance into `[0, 1]` using the policy ceiling. */
    fun normalizeSharpness(raw: Float, ceiling: Float): Float =
        (raw / ceiling).coerceIn(0f, 1f)

    /**
     * Exposure score combining a "stay in the [0.5 ± band] luminance window"
     * subscore with a clipping-ratio subscore. Each subscore is `[0, 1]`,
     * final exposure is their mean.
     */
    fun exposureScore(
        meanLuminance: Float,
        clippingRatio: Float,
        bandHalfWidth: Float,
        clippingMax: Float,
    ): Float {
        val bandDistance = if (bandHalfWidth > 0f) abs(meanLuminance - 0.5f) / bandHalfWidth else 1f
        val bandSubScore = (1f - bandDistance).coerceIn(0f, 1f)
        val clippingSubScore =
            if (clippingMax > 0f) (1f - clippingRatio / clippingMax).coerceIn(0f, 1f) else 0f
        return (bandSubScore + clippingSubScore) / 2f
    }

    fun exposurePasses(
        meanLuminance: Float,
        clippingRatio: Float,
        bandHalfWidth: Float,
        clippingMax: Float,
    ): Boolean {
        val bandDistance = if (bandHalfWidth > 0f) abs(meanLuminance - 0.5f) / bandHalfWidth else 1f
        return bandDistance <= 1f && clippingRatio <= clippingMax
    }

    /**
     * Completeness on the basis of the Hough output (cx, cy, r) in source-frame
     * coordinates. Score 1.0 if every edge has ≥ 5% margin (in radius units),
     * 0.5 if the disc just touches an edge (margin = 0), 0.0 if it's clipped by
     * ≥ 5% of the radius.
     *
     * Degenerate `r ≤ 0` yields 0.
     */
    fun completeness(cx: Int, cy: Int, r: Int, frameW: Int, frameH: Int): Float {
        if (r <= 0) return 0f
        val rf = r.toFloat()
        val leftMargin = (cx - r) / rf
        val rightMargin = (frameW - cx - r) / rf
        val topMargin = (cy - r) / rf
        val bottomMargin = (frameH - cy - r) / rf
        val minMargin = minOf(leftMargin, rightMargin, topMargin, bottomMargin)
        return ((minMargin + 0.05f) / 0.10f).coerceIn(0f, 1f)
    }

    /**
     * Motion score from the euclidean center delta between consecutive frames,
     * normalized by the radius. Returns `1.0` if [previousCenter] is null
     * (first frame of a trigger window).
     */
    fun motion(
        previousCenter: Pair<Float, Float>?,
        currentCx: Int,
        currentCy: Int,
        radius: Int,
        motionMax: Float,
    ): Float {
        if (previousCenter == null || radius <= 0) return 1f
        val (px, py) = previousCenter
        val delta = hypot((currentCx - px).toDouble(), (currentCy - py).toDouble()).toFloat() / radius
        if (motionMax <= 0f) return if (delta == 0f) 1f else 0f
        return (1f - delta / motionMax).coerceIn(0f, 1f)
    }

    fun motionPasses(
        previousCenter: Pair<Float, Float>?,
        currentCx: Int,
        currentCy: Int,
        radius: Int,
        motionMax: Float,
    ): Boolean {
        if (previousCenter == null || radius <= 0) return true
        val (px, py) = previousCenter
        val delta = hypot((currentCx - px).toDouble(), (currentCy - py).toDouble()).toFloat() / radius
        return delta <= motionMax
    }

    /**
     * Weighted mean of active axes. Motion is included iff [motionEnabled] is
     * true (and [motion] is non-null). Weights are renormalized over active
     * axes so the result is always `[0, 1]` regardless of which axes are on.
     */
    fun aggregate(
        sharpness: Float,
        exposure: Float,
        completeness: Float,
        motion: Float?,
        policy: ScoringPolicy,
    ): Float {
        var num = sharpness * policy.wSharpness +
            exposure * policy.wExposure +
            completeness * policy.wCompleteness
        var den = policy.wSharpness + policy.wExposure + policy.wCompleteness
        if (policy.motionEnabled && motion != null) {
            num += motion * policy.wMotion
            den += policy.wMotion
        }
        return if (den > 0f) num / den else 0f
    }
}
