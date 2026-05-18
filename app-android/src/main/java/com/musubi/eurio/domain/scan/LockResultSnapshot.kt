package com.musubi.eurio.domain.scan

/**
 * Persistable subset of an AE/AF/AWB lock outcome. Pure data — the
 * factory mapping from the live `ml.camera.LockState` lives in
 * `ml/camera/LockStateExt.kt` so the domain stays free of camera deps.
 *
 * `acquiredAtNs` is intentionally omitted: it's a monotonic-clock
 * value with no meaning post-process.
 */
data class LockResultSnapshot(
    val durationMs: Long,
    val afConverged: Boolean,
    val aeLocked: Boolean,
    val awbLocked: Boolean,
)
