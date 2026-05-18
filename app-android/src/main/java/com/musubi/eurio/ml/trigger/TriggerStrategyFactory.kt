package com.musubi.eurio.ml.trigger

import com.musubi.eurio.features.scan.debug.DebugScanConfig
import com.musubi.eurio.features.scan.debug.TriggerMode

/**
 * Creates a fresh [TriggerStrategy] instance from the current
 * [DebugScanConfig]. Called from the ViewModel whenever the debug config
 * changes — new instance ⇒ wiped state (cf. P3 — "trigger interchangeable,
 * jamais figé, jamais auto-supprimé").
 *
 * Every mode resolves to a concrete strategy that compiles in release; the
 * runtime switch is the only thing gating which one runs.
 */
object TriggerStrategyFactory {
    fun create(config: DebugScanConfig): TriggerStrategy = when (config.triggerMode) {
        TriggerMode.OFF -> NoOpTriggerStrategy()
        TriggerMode.BOX_STABILITY -> BoxStabilityTrigger(
            iouMin = config.stabilityIouMin,
            nFramesRequired = config.stabilityNFrames,
        )
        TriggerMode.YOLO_CONFIDENCE -> YoloConfidenceTrigger(
            confMin = config.yoloConfMin,
            nFramesRequired = config.stabilityNFrames,
        )
        TriggerMode.ARCFACE_CONSENSUS -> ArcfaceConsensusTrigger()
    }
}
