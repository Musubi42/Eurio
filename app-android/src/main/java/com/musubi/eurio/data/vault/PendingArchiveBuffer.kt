package com.musubi.eurio.data.vault

import android.os.SystemClock
import com.musubi.eurio.domain.scan.quality.FrameScore
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * In-memory parking spot for a JPEG produced by `ImageCapture` after a
 * successful AE/AF/AWB lock, waiting for the ArcFace consensus to
 * settle on an `eurioId` before it can be archived (D24 +
 * anti-objectif §6 vision.md "no frames stored for unrecognized coins").
 *
 * Lifecycle:
 *   - `set(...)` overwrites any prior pending — the most recent fire
 *     wins, older bytes are dropped (GC'd as soon as the caller releases
 *     the reference).
 *   - `consume(eurioId)` returns and clears the pending if it's still
 *     valid; returns null if expired or empty.
 *   - `clear()` releases the buffer explicitly (called from
 *     `returnToIdle` so we don't leak the JPEG into the next scan run).
 *
 * Expiration is checked lazily on each public call — no background
 * sweeper, so the class has no lifecycle of its own. Worst case: a
 * pending archive sits in memory until the next user interaction or
 * `clear()`, which is fine (one frame ≈ 500 KB JPEG).
 *
 * Thread-safe via a single mutex. Calls are suspend so they compose
 * cleanly with `viewModelScope.launch { ... }`.
 */
class PendingArchiveBuffer(
    private val timeoutMs: Long = DEFAULT_TIMEOUT_MS,
    private val nowMs: () -> Long = SystemClock::elapsedRealtime,
) {
    data class Pending(
        val captureId: String,
        val jpegBytes: ByteArray,
        val score: FrameScore,
        val metadata: CaptureMetadata,
        val createdAtMs: Long,
    )

    private val mutex = Mutex()
    private var current: Pending? = null

    suspend fun set(
        captureId: String,
        jpegBytes: ByteArray,
        score: FrameScore,
        metadata: CaptureMetadata,
    ) = mutex.withLock {
        current = Pending(
            captureId = captureId,
            jpegBytes = jpegBytes,
            score = score,
            metadata = metadata,
            createdAtMs = nowMs(),
        )
    }

    /**
     * Pull the pending archive matching the resolved [eurioId]. Returns
     * `null` if no pending exists or it has expired. The caller is
     * responsible for actually invoking the repository — keeps this
     * class free of repo dependencies and easy to unit-test.
     *
     * `eurioId` is accepted but not stored against — the pending is
     * eurioId-agnostic at set() time (the trigger doesn't know yet
     * which coin it is). The caller pairs the bytes with the consensus.
     */
    @Suppress("UNUSED_PARAMETER")
    suspend fun consume(eurioId: String): Pending? = mutex.withLock {
        val p = current ?: return@withLock null
        current = null
        if (nowMs() - p.createdAtMs > timeoutMs) {
            return@withLock null
        }
        p
    }

    suspend fun clear() = mutex.withLock {
        current = null
    }

    /** For tests + debug HUD — non-destructive peek. */
    suspend fun hasPending(): Boolean = mutex.withLock {
        val p = current ?: return@withLock false
        nowMs() - p.createdAtMs <= timeoutMs
    }

    companion object {
        const val DEFAULT_TIMEOUT_MS: Long = 3_000L
    }
}
