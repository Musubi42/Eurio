package com.musubi.eurio.ml.trigger

import android.graphics.RectF

/**
 * Pure-data bounding box mirroring [android.graphics.RectF] without the
 * Android dependency, so [BufferedFrame] and the trigger strategies stay
 * JVM-instantiable in unit tests.
 *
 * Conversions sit at the boundary in [com.musubi.eurio.ml.CoinAnalyzer], which
 * translates the detector's `RectF` into a `BboxF` when constructing a
 * [BufferedFrame].
 */
data class BboxF(
    val left: Float,
    val top: Float,
    val right: Float,
    val bottom: Float,
) {
    val width: Float get() = right - left
    val height: Float get() = bottom - top
    val area: Float get() = (width.coerceAtLeast(0f)) * (height.coerceAtLeast(0f))

    companion object {
        fun fromRectF(r: RectF): BboxF = BboxF(r.left, r.top, r.right, r.bottom)
    }
}

/**
 * Intersection-over-union between two boxes. Returns 0 for empty/degenerate
 * boxes — never NaN. Used by [BoxStabilityTrigger] to measure temporal
 * stability of the primary detection.
 */
fun iou(a: BboxF, b: BboxF): Float {
    val interLeft = maxOf(a.left, b.left)
    val interTop = maxOf(a.top, b.top)
    val interRight = minOf(a.right, b.right)
    val interBottom = minOf(a.bottom, b.bottom)
    val interW = (interRight - interLeft).coerceAtLeast(0f)
    val interH = (interBottom - interTop).coerceAtLeast(0f)
    val interArea = interW * interH
    val unionArea = a.area + b.area - interArea
    return if (unionArea <= 0f) 0f else interArea / unionArea
}
