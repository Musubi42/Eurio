package com.musubi.eurio.ml.trigger

import com.musubi.eurio.ml.DetectionSource

/**
 * Fires once YOLO confidence on the primary detection stays at or above
 * [confMin] for [nFramesRequired] consecutive frames.
 *
 * **Silent on Hough-only frames.** When the detector reports only a
 * Hough-source bbox, `primaryConfidence` carries the Hough placeholder score
 * which is not comparable — we reset the counter to avoid false positives.
 * Documented trade-off (cf. chunk-3 doc §YoloConfidenceTrigger).
 */
class YoloConfidenceTrigger(
    private val confMin: Float,
    private val nFramesRequired: Int,
) : TriggerStrategy {

    override val name: String = "yolo_confidence"

    private var firedForRun = false
    private var consecutive = 0

    override fun observe(context: FrameContext): TriggerEvent? {
        if (firedForRun) return null

        val conf = context.primaryConfidence
        val source = context.primarySource
        if (conf == null || source != DetectionSource.YOLO || conf < confMin) {
            consecutive = 0
            return null
        }
        consecutive++

        if (consecutive >= nFramesRequired) {
            firedForRun = true
            return TriggerEvent.Fire(
                reason = "yolo ${consecutive}f conf≥${"%.2f".format(confMin)}",
                bufferSnapshot = context.buffer,
            )
        }
        return null
    }

    override fun reset() {
        firedForRun = false
        consecutive = 0
    }
}
