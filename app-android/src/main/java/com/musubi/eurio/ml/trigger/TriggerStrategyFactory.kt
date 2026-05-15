package com.musubi.eurio.ml.trigger

import com.musubi.eurio.features.scan.debug.DebugScanConfig
import com.musubi.eurio.features.scan.debug.TriggerMode

/**
 * Creates a fresh [TriggerStrategy] instance from the current
 * [DebugScanConfig]. Called from the ViewModel whenever the debug config
 * changes — new instance ⇒ wiped state (cf. P3).
 *
 * Chunk-3a stub: every mode resolves to [NoOpTriggerStrategy]. Chunk-3b will
 * add `BoxStabilityTrigger`, `YoloConfidenceTrigger`, `ArcfaceConsensusTrigger`
 * branches reading the relevant parameters off [DebugScanConfig].
 */
object TriggerStrategyFactory {
    fun create(config: DebugScanConfig): TriggerStrategy {
        return when (config.triggerMode) {
            TriggerMode.OFF -> NoOpTriggerStrategy()
            TriggerMode.BOX_STABILITY,
            TriggerMode.YOLO_CONFIDENCE,
            TriggerMode.ARCFACE_CONSENSUS -> NoOpTriggerStrategy()
        }
    }
}
