package com.musubi.eurio.ml.camera

/**
 * State of the AE/AF/AWB lock controlled by [CameraLockController].
 *
 * Lives next to the controller and surfaces through `state: StateFlow<LockState>`
 * so the HUD + overlay can observe transitions without polling.
 */
sealed class LockState {
    object Idle : LockState()
    object Acquiring : LockState()
    data class Locked(
        val acquiredAtNs: Long,
        val durationMs: Long,
        val afConverged: Boolean,
        val aeLocked: Boolean,
        val awbLocked: Boolean,
    ) : LockState()
    data class Failed(
        val reason: String,
        val durationMs: Long,
    ) : LockState()
    object Released : LockState()
}
