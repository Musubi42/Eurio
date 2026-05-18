package com.musubi.eurio.ml.camera

import com.musubi.eurio.domain.scan.LockResultSnapshot

/**
 * Map a live [LockState] to the domain's persistable
 * [LockResultSnapshot]. Lives here (not in `domain/scan/`) so the
 * domain layer stays free of camera deps.
 */
fun LockState.toSnapshot(): LockResultSnapshot? = when (this) {
    is LockState.Locked -> LockResultSnapshot(
        durationMs = durationMs,
        afConverged = afConverged,
        aeLocked = aeLocked,
        awbLocked = awbLocked,
    )
    else -> null
}
