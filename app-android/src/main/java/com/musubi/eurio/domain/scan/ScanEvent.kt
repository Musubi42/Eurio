package com.musubi.eurio.domain.scan

/**
 * Every input the scan state machine can react to. The reducer
 * ([ScanReducer]) is pure on `(state, event) → result` ; sub-systems
 * (analyzer, lock controller, consensus buffer, archive buffer,
 * timeout scheduler, UI) push these into a single SharedFlow that the
 * ViewModel collects.
 *
 * Keep this sealed class flat — no nested hierarchies — so the
 * reducer's `when` exhausts cleanly.
 */
sealed class ScanEvent {

    // --- pipeline events ----------------------------------------

    /** First frame with an accepted detection after [ScanState.Idle]. */
    object FirstDetection : ScanEvent()

    /** N consecutive frames without an accepted detection — drops back to idle. */
    object NoDetectionStreak : ScanEvent()

    data class TriggerFire(val reason: String) : ScanEvent()

    /** Bbox lost / stability collapsed while locking or capturing (D22). */
    object TriggerAbort : ScanEvent()

    data class LockAcquired(val result: LockResultSnapshot) : ScanEvent()
    data class LockFailed(val reason: String) : ScanEvent()

    data class CaptureCompleted(
        val captureId: String,
        val sourceMode: SourceMode,
    ) : ScanEvent()

    /** `ImageCapture.takePicture` failed — fallback to YUV preview path. */
    data class CaptureError(val cause: String) : ScanEvent()

    /** ArcFace sticky-consensus locked on a class (5/3 buffer). */
    data class ConsensusReached(
        val eurioId: String,
        val topK: List<ArcfaceMatch>,
    ) : ScanEvent()

    /** The pending JPEG was claimed by the consensus and persisted. */
    data class ArchiveCompleted(val captureId: String) : ScanEvent()

    /** Pending archive expired without consensus claim. */
    data class ArchiveDiscarded(val reason: String) : ScanEvent()

    // --- timeouts -----------------------------------------------

    object LockingTimeout : ScanEvent()
    object CapturingTimeout : ScanEvent()
    object IdentifyingTimeout : ScanEvent()

    /** 200 ms abort-flash elapsed → return to [ScanState.Detecting]. */
    object AbortFlashElapsed : ScanEvent()

    // --- user events --------------------------------------------

    /** Tap "dismiss" on the coin sheet — return to viewfinder. */
    object UserDismiss : ScanEvent()

    /** Back gesture during any scan sub-state. */
    object UserBack : ScanEvent()

    /**
     * Tap "Ajouter au coffre" on [ScanState.Accepted] — triggers
     * `confirmPossession` (D24) then returns to [ScanState.Idle].
     */
    object UserConfirmAdd : ScanEvent()

    /** 2 s auto-return timer post-Accepted when the coin is already owned. */
    object AlreadyOwnedAutoReturn : ScanEvent()

    // --- lifecycle ----------------------------------------------

    object ScreenResumed : ScanEvent()
    object ScreenPaused : ScanEvent()
}
