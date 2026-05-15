package com.musubi.eurio.features.scan.debug

import com.musubi.eurio.domain.scan.quality.FrameScore

/**
 * Live snapshot rendered by [ScanHud]. The flow lives on [com.musubi.eurio.features.scan.ScanViewModel]
 * regardless of build type, but only the debug build composes the HUD — release
 * keeps the flow inert at its defaults.
 *
 * Filled by [com.musubi.eurio.ml.CoinAnalyzer] (frame score / timings) and by
 * the ScanViewModel itself (machineState / sinceTriggerMs once the trigger
 * state machine lands at chunk-3/6).
 */
data class ScanHudState(
    val machineState: String = "Idle",
    val sinceTriggerMs: Long? = null,
    val lastFrameScore: FrameScore? = null,
    val bestFrameScore: FrameScore? = null,
    val bestFrameIndex: Int? = null,
    val arcfaceTop3: List<ArcfaceMatch> = emptyList(),
    val timings: TimingBreakdown = TimingBreakdown(),
    val bufferSize: Int = 0,
    val bufferCapacity: Int = 0,
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
