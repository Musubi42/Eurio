package com.musubi.eurio.features.scan.debug

/**
 * Runtime-tunable knobs for the best-frame capture pipeline.
 *
 * Defaults encode "current behavior + best-frame disabled" ([TriggerMode.OFF]) :
 * as long as the user doesn't move a slider, the app behaves exactly like the
 * pre-best-frame scan. Sliders/toggles in [com.musubi.eurio.features.scan.debug.DebugBar]
 * mutate this through [DebugScanConfigStore]; pipeline components read it via
 * [com.musubi.eurio.features.scan.ScanViewModel.debugConfig].
 *
 * The class is compiled in release too (it's referenced from ScanViewModel),
 * but only the debug build mutates it from UI — see [DebugScanConfigStore].
 */
data class DebugScanConfig(
    // Trigger
    val triggerMode: TriggerMode = TriggerMode.OFF,
    val stabilityIouMin: Float = 0.7f,
    val stabilityNFrames: Int = 3,
    val yoloConfMin: Float = 0.50f,

    // Burst
    val burstSize: Int = 5,
    val rollingBufferEnabled: Boolean = true,

    // Lock
    val aeLockEnabled: Boolean = true,
    val afLockEnabled: Boolean = true,
    val awbLockEnabled: Boolean = true,

    // Quality gates (absolute thresholds for early-stop)
    val sharpnessMin: Float = 80f,
    val exposureBandHalfWidth: Float = 0.2f,
    val completenessMin: Float = 0.95f,
    val motionEnabled: Boolean = false,

    // Capture
    val captureMode: CaptureMode = CaptureMode.PREVIEW_ONLY,

    // Session record (consumed by chunk-7 replay tooling)
    val recordEnabled: Boolean = false,
)

enum class TriggerMode { OFF, BOX_STABILITY, YOLO_CONFIDENCE, ARCFACE_CONSENSUS }

enum class CaptureMode { PREVIEW_ONLY, IMAGECAPTURE_FULL, BOTH_PARALLEL }
