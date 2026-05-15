package com.musubi.eurio.ml.trigger

/**
 * Default strategy: never fires.
 *
 * Active whenever the debug-bar's `triggerMode` is `OFF` (chunk-1 default).
 * Guarantees the continuous scan behaves exactly like before chunk-3 — the
 * buffer fills and frames flow through, but no Fire event is ever produced,
 * so no side-effect downstream (chunks 4-6) gets activated.
 */
class NoOpTriggerStrategy : TriggerStrategy {
    override val name: String = "off"
    override fun observe(context: FrameContext): TriggerEvent? = null
    override fun reset() = Unit
}
