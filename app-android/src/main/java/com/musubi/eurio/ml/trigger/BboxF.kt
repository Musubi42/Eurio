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
