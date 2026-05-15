package com.musubi.eurio.ml.trigger

/**
 * Pluggable trigger that decides when the best-frame selector should fire.
 *
 * Implementations are **stateful per instance** (they accumulate consecutive
 * frame counters, last bbox, etc.). The factory creates a fresh instance on
 * every [com.musubi.eurio.features.scan.debug.DebugScanConfig] change so a
 * parameter tweak wipes the running state automatically (cf. D5 / P3).
 *
 * Convention: every strategy must compile in release. Per `feedback_no_debt`
 * and P3, we never code-eliminate an unused strategy "silently" — runtime
 * selection is the only switch.
 */
interface TriggerStrategy {
    /** Identifier surfaced in logs and the HUD ("off", "box_stability", …). */
    val name: String

    /**
     * Called once per analyzed frame. Returns:
     *  - `null`             — nothing yet, keep observing
     *  - [TriggerEvent.Fire]  — trigger the best-frame selector now
     *  - [TriggerEvent.Abort] — abort an in-flight trigger run (the strategy
     *                           saw the user move out of the stability zone)
     *
     * Strategies typically gate themselves with an internal `firedForRun` flag
     * so they emit a single Fire until [reset] is called.
     */
    fun observe(context: FrameContext): TriggerEvent?

    /** Wipe internal state. Called after Fire and on strategy swap. */
    fun reset()
}

sealed class TriggerEvent {
    data class Fire(
        val reason: String,
        val bufferSnapshot: List<BufferedFrame>,
    ) : TriggerEvent()

    object Abort : TriggerEvent()
}
