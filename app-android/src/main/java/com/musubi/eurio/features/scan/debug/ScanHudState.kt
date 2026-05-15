package com.musubi.eurio.features.scan.debug

/**
 * Live snapshot rendered by [ScanHud]. The flow lives on [com.musubi.eurio.features.scan.ScanViewModel]
 * regardless of build type, but only the debug build composes the HUD — release
 * keeps the flow inert at its defaults.
 *
 * Future chunks fill in the fields:
 *  - chunk-2 → [lastFrameScore], [bestFrameScore], [bestFrameIndex]
 *  - chunk-3 → [machineState] transitions, [sinceTriggerMs]
 *  - chunk-6 → state machine transitions
 *  - chunks 2/3/5 → [timings]
 */
data class ScanHudState(
    val machineState: String = "Idle",
    val sinceTriggerMs: Long? = null,
    val lastFrameScore: FrameScore? = null,
    val bestFrameScore: FrameScore? = null,
    val bestFrameIndex: Int? = null,
    val arcfaceTop3: List<ArcfaceMatch> = emptyList(),
    val timings: TimingBreakdown = TimingBreakdown(),
)

data class FrameScore(
    val sharpness: Float,
    val exposure: Float,
    val completeness: Float,
    val aggregate: Float,
)

data class ArcfaceMatch(
    val className: String,
    val similarity: Float,
)

data class TimingBreakdown(
    val detectMs: Long = 0,
    val normalizeMs: Long = 0,
    val arcfaceMs: Long = 0,
    val scoreMs: Long = 0,
)
