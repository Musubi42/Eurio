package com.musubi.eurio.features.scan.debug

import com.musubi.eurio.domain.scan.ArcfaceMatch
import com.musubi.eurio.domain.scan.quality.FrameScore
import com.musubi.eurio.ml.camera.LockState

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
    /**
     * Shadow state machine label (chunk-6.2a). Mirrors the new domain
     * reducer running in parallel with the legacy flow. Identical to
     * [machineState] while only 3 states existed ; diverges to expose
     * `Locking` / `Capturing` / `Identifying` / `Aborted` once the
     * reducer is wired. Visual-only — does not drive any pipeline.
     */
    val shadowState: String = "Idle",
    val sinceTriggerMs: Long? = null,
    val lastFrameScore: FrameScore? = null,
    val bestFrameScore: FrameScore? = null,
    val bestFrameIndex: Int? = null,
    val arcfaceTop3: List<ArcfaceMatch> = emptyList(),
    val timings: TimingBreakdown = TimingBreakdown(),
    val bufferSize: Int = 0,
    val bufferCapacity: Int = 0,
    /** Reason emitted by the trigger when it last fired — null when no fire is active. */
    val triggerFireReason: String? = null,
    /** Short selector-reason ("passed_all_gates" or "best_aggregate_fallback") accompanying the fire. */
    val bestSelectionReason: String? = null,
    /** Live AE/AF/AWB lock controller state (chunk-4). Mirrors `ScanViewModel.lockState`. */
    val lockState: LockState = LockState.Idle,
)

data class TimingBreakdown(
    val detectMs: Long = 0,
    val normalizeMs: Long = 0,
    val arcfaceMs: Long = 0,
    val scoreMs: Long = 0,
)
