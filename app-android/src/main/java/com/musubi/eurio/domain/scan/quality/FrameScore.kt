package com.musubi.eurio.domain.scan.quality

/**
 * Multi-criteria quality score computed once per analyzed frame.
 *
 * Each named axis is normalized to `[0, 1]` for aggregation and HUD rendering,
 * but raw values ([sharpnessRaw], [meanLuminance], [clippingRatio]) are kept
 * alongside because a human reading a debug session understands "variance 142"
 * faster than "sharpness 0.71", and the replay tooling (chunk-7) needs the
 * raw values to re-evaluate frames under different thresholds.
 *
 * [aggregate] is a weighted mean of the active axes per [ScoringPolicy]
 * (motion only contributes when [ScoringPolicy.motionEnabled]).
 *
 * Decision per D9: `aggregate` is **never surfaced to the user as a grade** —
 * it's an internal signal only.
 */
data class FrameScore(
    val sharpness: Float,
    val sharpnessRaw: Float,
    val exposure: Float,
    val meanLuminance: Float,
    val clippingRatio: Float,
    val completeness: Float,
    val motion: Float?,
    val aggregate: Float,
    val passes: GatesResult,
) {
    companion object {
        /**
         * Sentinel emitted when scoring couldn't run (no detection, normalize
         * failure, OpenCV error). All zeros + all gates failing — surfaces in
         * the HUD as `sharp 0✗ exp 0.00✗ comp 0.00✗ agg 0.00`, and lands in
         * the future record JSONL as a first-class row instead of being
         * silently dropped (cf. `feedback_no_debt`).
         */
        val Failed = FrameScore(
            sharpness = 0f,
            sharpnessRaw = 0f,
            exposure = 0f,
            meanLuminance = 0f,
            clippingRatio = 1f,
            completeness = 0f,
            motion = null,
            aggregate = 0f,
            passes = GatesResult(
                sharpness = false,
                exposure = false,
                completeness = false,
                motion = null,
                all = false,
            ),
        )
    }
}

data class GatesResult(
    val sharpness: Boolean,
    val exposure: Boolean,
    val completeness: Boolean,
    val motion: Boolean?,
    val all: Boolean,
)
