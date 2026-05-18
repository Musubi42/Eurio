package com.musubi.eurio.domain.scan

/**
 * State machine for the scan feature (chunk-6 refonte). Seven explicit
 * states drive every transition through [ScanReducer]; auxiliary
 * booleans on the ViewModel are forbidden — they desync from the flags
 * and are exactly the kind of latent debt the reducer eliminates
 * ([[feedback_no_debt]]).
 *
 *   Idle → Detecting → Locking → Capturing → Identifying → Accepted
 *                                                          ↘ Idle
 *
 * Sub-states between [Detecting] and [Accepted] are invisible to the
 * user in release builds — they render the continuous viewfinder ; the
 * debug overlay (chunk-4) colors them differently to make the pipeline
 * legible during dev.
 *
 * Three transient escapes:
 *  - [Aborted] : 200 ms flash before falling back to [Detecting] when
 *    the lock/capture pipeline gives up on the current bbox.
 *  - timeouts on [Locking] / [Capturing] / [Identifying] → [Aborted].
 *  - [Accepted] returns to [Idle] on user dismiss / confirm-add / 2 s
 *    auto-return when the coin is already in the vault.
 *
 * `ConsensusReached` can fire from any state between [Detecting] and
 * [Identifying] and jumps straight to [Accepted] — display is
 * decoupled from archive (D3, vision.md §6).
 */
sealed class ScanState {

    /** No bbox in the frame — viewfinder idle, no pipeline work. */
    object Idle : ScanState()

    /** At least one bbox detected, not yet stable / identified. */
    object Detecting : ScanState()

    /** Trigger fired ; AE/AF/AWB lock acquisition in flight. */
    data class Locking(
        val triggerReason: String,
        val sinceNs: Long,
    ) : ScanState()

    /** Lock acquired ; full-resolution `ImageCapture` in flight. */
    data class Capturing(
        val lockResult: LockResultSnapshot,
        val sinceNs: Long,
    ) : ScanState()

    /**
     * Capture obtained ; awaiting ArcFace consensus before the archive
     * can be claimed by an eurioId.
     */
    data class Identifying(
        val pendingCaptureId: String,
        val sourceMode: SourceMode,
        val sinceNs: Long,
    ) : ScanState()

    /**
     * Consensus reached ; coin sheet visible. `captureArchived` flips
     * to `true` when the pending archive lands ; the state stays
     * `Accepted` either way (display is decoupled from archive).
     *
     * `pendingCaptureId` is `null` when no capture is in flight (eg.
     * trigger=OFF path) — `confirmPossession` then creates a
     * `coin_in_vault` without primary, falling back to the catalog
     * image (cf. chunk-5 §Possession).
     */
    data class Accepted(
        val eurioId: String,
        val arcfaceTopK: List<ArcfaceMatch>,
        val captureArchived: Boolean = false,
        val pendingCaptureId: String? = null,
    ) : ScanState()

    /**
     * Transient (200 ms) flash before returning to [Detecting] when a
     * sub-state gives up (lock failed, bbox lost, timeout).
     * `previousStateName` is kept for logs / debug only.
     */
    data class Aborted(
        val reason: String,
        val previousStateName: String,
    ) : ScanState()
}
