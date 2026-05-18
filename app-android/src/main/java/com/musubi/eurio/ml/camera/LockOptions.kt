package com.musubi.eurio.ml.camera

import com.musubi.eurio.features.scan.debug.DebugScanConfig

/**
 * Normalized metering region in 0..1 surface coords (top-left origin).
 * The [CameraLockController] expands this by [LockOptions.regionExpansion]
 * before handing it to `SurfaceOrientedMeteringPointFactory`.
 */
data class MeteringRect(
    val left: Float,
    val top: Float,
    val right: Float,
    val bottom: Float,
) {
    val centerX: Float get() = (left + right) / 2f
    val centerY: Float get() = (top + bottom) / 2f
}

/**
 * Inputs to one lock() call. The three booleans come from the debug bar (D11
 * toggles, BuildConfig.DEBUG only — release defaults set in DebugScanConfig).
 * `afTimeoutMs` and `regionExpansion` are bench-tunables for chunk-7.
 */
data class LockOptions(
    val aeLock: Boolean,
    val afLock: Boolean,
    val awbLock: Boolean,
    val region: MeteringRect,
    val afTimeoutMs: Long = 800L,
    val regionExpansion: Float = 0.12f,
) {
    companion object
}

fun LockOptions.Companion.fromDebugConfig(
    config: DebugScanConfig,
    region: MeteringRect,
): LockOptions = LockOptions(
    aeLock = config.aeLockEnabled,
    afLock = config.afLockEnabled,
    awbLock = config.awbLockEnabled,
    region = region,
)
