package com.musubi.eurio.domain.scan.quality

import com.musubi.eurio.features.scan.debug.DebugScanConfig

/**
 * Tunable weights + absolute thresholds for [FrameScore].
 *
 * Defaults are placeholder values from the chunk-2 spec — they'll be
 * calibrated on ~50 captures in the chunk-7 bench. The debug-bar
 * (chunk-1) lets us slide [sharpnessMin], [exposureBandHalfWidth],
 * [completenessMin], [motionEnabled] at runtime; the other knobs stay
 * frozen here for now.
 */
data class ScoringPolicy(
    val wSharpness: Float = 0.5f,
    val wExposure: Float = 0.2f,
    val wCompleteness: Float = 0.2f,
    val wMotion: Float = 0.1f,

    val sharpnessMin: Float = 80f,
    val exposureBandHalfWidth: Float = 0.2f,
    val clippingMax: Float = 0.01f,
    val completenessMin: Float = 0.95f,
    val motionMax: Float = 0.05f,
    val motionEnabled: Boolean = false,

    val sharpnessNormalizationCeiling: Float = 400f,
) {
    companion object {
        fun fromDebugConfig(config: DebugScanConfig): ScoringPolicy =
            ScoringPolicy(
                sharpnessMin = config.sharpnessMin,
                exposureBandHalfWidth = config.exposureBandHalfWidth,
                completenessMin = config.completenessMin,
                motionEnabled = config.motionEnabled,
            )
    }
}
