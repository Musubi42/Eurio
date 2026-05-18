package com.musubi.eurio.features.scan.debug

import com.musubi.eurio.ml.trigger.BboxF

/**
 * One-shot event emitted when the trigger aborts (motion mid-lock, etc.).
 *
 * Carries the last known bbox so the [com.musubi.eurio.features.scan.debug.ScanLockOverlay]
 * can flash a red pulse at the right spot — a transient signal that wouldn't
 * survive as a `StateFlow` value because both arrival and decay matter.
 *
 * The bbox is in frame-pixel coords; the overlay maps it to its draw space
 * the same way as the live HUD bbox.
 */
data class AbortEvent(
    val timestampMs: Long,
    val reason: String,
    val lastBbox: BboxF?,
    val frameWidth: Int,
    val frameHeight: Int,
)
