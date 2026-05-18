package com.musubi.eurio.ml.trigger

/**
 * Fires once the primary detection's bbox has stayed within [iouMin] of the
 * previous frame's bbox for [nFramesRequired] consecutive frames.
 *
 * Source-agnostic — works on YOLO and Hough detections alike. That makes it
 * the default candidate for the chunk-7 bench since `YoloConfidenceTrigger`
 * is silent on Hough-only frames (bimetal coins, lower-contrast lighting).
 *
 * State semantics (cf. doc §BoxStabilityTrigger):
 *  - `consecutive` counts current run length (1 when entering a new run).
 *  - A null bbox resets `lastBbox` and `consecutive`, so a brief loss
 *    cancels the run.
 *  - `firedForRun` blocks further fires until [reset] — the ViewModel is
 *    expected to call reset on `returnToIdle`.
 */
class BoxStabilityTrigger(
    private val iouMin: Float,
    private val nFramesRequired: Int,
) : TriggerStrategy {

    override val name: String = "box_stability"

    private var firedForRun = false
    private var consecutive = 0
    private var lastBbox: BboxF? = null

    override fun observe(context: FrameContext): TriggerEvent? {
        if (firedForRun) return null

        val current = context.primaryBbox
        if (current == null) {
            consecutive = 0
            lastBbox = null
            return null
        }

        val prev = lastBbox
        if (prev != null) {
            val iouValue = iou(prev, current)
            if (iouValue >= iouMin) consecutive++ else consecutive = 1
        } else {
            consecutive = 1
        }
        lastBbox = current

        if (consecutive >= nFramesRequired) {
            firedForRun = true
            return TriggerEvent.Fire(
                reason = "stable ${consecutive}f IoU≥${"%.2f".format(iouMin)}",
                bufferSnapshot = context.buffer,
            )
        }
        return null
    }

    override fun reset() {
        firedForRun = false
        consecutive = 0
        lastBbox = null
    }
}
