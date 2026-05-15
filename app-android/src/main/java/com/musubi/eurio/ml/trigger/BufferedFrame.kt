package com.musubi.eurio.ml.trigger

import android.graphics.Bitmap
import com.musubi.eurio.domain.scan.quality.FrameScore
import com.musubi.eurio.ml.CoinMatch
import com.musubi.eurio.ml.DetectionSource

/**
 * One entry in the [RollingFrameBuffer] — the smallest amount of state the
 * best-frame selector needs to compare frames after the trigger fires.
 *
 * `crop` carries the normalized 224×224 bitmap with its black-disc mask, the
 * same one [com.musubi.eurio.ml.quality.FrameQualityScorer] scored. Ownership
 * is held by the buffer: when the buffer evicts a frame, it recycles the
 * bitmap. Consumers must never call `crop.recycle()` themselves.
 *
 * The field is nullable strictly so the data class is JVM-instantiable from
 * unit tests (no Android Bitmap on the classpath there). In production the
 * crop is always non-null — `CoinAnalyzer` only pushes after a successful
 * `SnapNormalizer.normalize`.
 *
 * `bbox` / `detectionConfidence` / `detectionSource` are flattened off
 * [com.musubi.eurio.ml.Detection] so the trigger logic stays pure (no
 * `RectF` import).
 */
data class BufferedFrame(
    val sequenceId: Int,
    val timestampNs: Long,
    val crop: Bitmap?,
    val score: FrameScore,
    val bbox: BboxF,
    val detectionConfidence: Float,
    val detectionSource: DetectionSource,
    val arcfaceTop3: List<CoinMatch>,
)
