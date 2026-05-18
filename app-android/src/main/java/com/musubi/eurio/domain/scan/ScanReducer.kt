package com.musubi.eurio.domain.scan

/**
 * Pure reducer for the scan state machine (chunk-6).
 *
 * Contract :
 *   - no I/O, no logging, no clock read inside `reduce` (the caller
 *     provides `nowNs` so tests can pin time)
 *   - all transitions return both the next state **and** the list of
 *     side effects the runtime must apply
 *
 * That keeps `ScanReducerTest` exhaustive and fast — every transition
 * is a table-driven assertion on a single function call.
 */
object ScanReducer {

    /** State-machine timeout for the [ScanState.Locking] phase. */
    const val LOCKING_TIMEOUT_MS: Long = 1_500L

    /** State-machine timeout for the [ScanState.Capturing] phase. */
    const val CAPTURING_TIMEOUT_MS: Long = 1_500L

    /**
     * Aligned with `PendingArchiveBuffer.DEFAULT_TIMEOUT_MS` (chunk-5).
     * If one moves, the other must too.
     */
    const val IDENTIFYING_TIMEOUT_MS: Long = 3_000L

    /** Visual abort flash before returning to [ScanState.Detecting]. */
    const val ABORT_FLASH_MS: Long = 200L

    /** 2 s grace before auto-returning from a "déjà possédée" sheet. */
    const val ALREADY_OWNED_AUTO_RETURN_MS: Long = 2_000L

    fun reduce(state: ScanState, event: ScanEvent, nowNs: Long): ReduceResult =
        when (state) {
            ScanState.Idle -> reduceFromIdle(event)
            ScanState.Detecting -> reduceFromDetecting(event, nowNs)
            is ScanState.Locking -> reduceFromLocking(state, event, nowNs)
            is ScanState.Capturing -> reduceFromCapturing(state, event, nowNs)
            is ScanState.Identifying -> reduceFromIdentifying(state, event)
            is ScanState.Accepted -> reduceFromAccepted(state, event)
            is ScanState.Aborted -> reduceFromAborted(state, event)
        }

    // ----------------------------------------------------------------

    private fun reduceFromIdle(event: ScanEvent): ReduceResult = when (event) {
        ScanEvent.FirstDetection -> transition(
            to = ScanState.Detecting,
            sideEffects = listOf(
                SideEffect.ResetTrigger,
                SideEffect.ScheduleNoDetectionWatcher,
            ),
        )
        else -> stay(ScanState.Idle)
    }

    private fun reduceFromDetecting(event: ScanEvent, nowNs: Long): ReduceResult = when (event) {
        ScanEvent.NoDetectionStreak -> transition(to = ScanState.Idle)
        is ScanEvent.TriggerFire -> transition(
            to = ScanState.Locking(event.reason, nowNs),
            sideEffects = listOf(
                SideEffect.StartLock,
                SideEffect.StartTimeout(LOCKING_TIMEOUT_MS),
            ),
        )
        is ScanEvent.ConsensusReached -> transition(
            to = ScanState.Accepted(event.eurioId, event.topK),
            sideEffects = listOf(SideEffect.ScheduleAlreadyOwnedCheck),
        )
        ScanEvent.ScreenPaused -> transition(to = ScanState.Idle)
        ScanEvent.UserBack -> transition(to = ScanState.Idle)
        else -> stay(ScanState.Detecting)
    }

    private fun reduceFromLocking(
        state: ScanState.Locking,
        event: ScanEvent,
        nowNs: Long,
    ): ReduceResult = when (event) {
        is ScanEvent.LockAcquired -> transition(
            to = ScanState.Capturing(event.result, nowNs),
            sideEffects = listOf(
                SideEffect.StartCapture,
                SideEffect.StartTimeout(CAPTURING_TIMEOUT_MS),
            ),
        )
        is ScanEvent.LockFailed -> abortFromSubState(
            previous = "Locking",
            reason = "lock_failed:${event.reason}",
        )
        ScanEvent.LockingTimeout -> abortFromSubState(
            previous = "Locking",
            reason = "lock_timeout",
        )
        ScanEvent.TriggerAbort -> abortFromSubState(
            previous = "Locking",
            reason = "bbox_lost",
        )
        is ScanEvent.ConsensusReached -> transition(
            // Consensus during locking → snap to Accepted, release lock
            // asynchronously via the side effect.
            to = ScanState.Accepted(event.eurioId, event.topK),
            sideEffects = listOf(
                SideEffect.ReleaseLock,
                SideEffect.CancelTimeout,
                SideEffect.ScheduleAlreadyOwnedCheck,
            ),
        )
        ScanEvent.UserBack, ScanEvent.ScreenPaused -> transition(
            to = ScanState.Idle,
            sideEffects = listOf(
                SideEffect.ReleaseLock,
                SideEffect.CancelTimeout,
                SideEffect.DiscardPendingArchive,
            ),
        )
        else -> stay(state)
    }

    private fun reduceFromCapturing(
        state: ScanState.Capturing,
        event: ScanEvent,
        nowNs: Long,
    ): ReduceResult = when (event) {
        is ScanEvent.CaptureCompleted -> transition(
            to = ScanState.Identifying(
                pendingCaptureId = event.captureId,
                sourceMode = event.sourceMode,
                sinceNs = nowNs,
            ),
            sideEffects = listOf(
                SideEffect.ReleaseLock,
                SideEffect.StartTimeout(IDENTIFYING_TIMEOUT_MS),
            ),
        )
        is ScanEvent.CaptureError -> transition(
            // Fallback YUV path keeps the pipeline alive — bench replay
            // can distinguish via sourceMode in metadata.
            to = ScanState.Identifying(
                pendingCaptureId = "yuv_fallback",
                sourceMode = SourceMode.YUV_PREVIEW_FALLBACK,
                sinceNs = nowNs,
            ),
            sideEffects = listOf(
                SideEffect.ReleaseLock,
                SideEffect.StartTimeout(IDENTIFYING_TIMEOUT_MS),
            ),
        )
        ScanEvent.CapturingTimeout -> abortFromSubState(
            previous = "Capturing",
            reason = "capture_timeout",
        )
        ScanEvent.TriggerAbort -> abortFromSubState(
            previous = "Capturing",
            reason = "bbox_lost",
        )
        is ScanEvent.ConsensusReached -> transition(
            to = ScanState.Accepted(event.eurioId, event.topK),
            sideEffects = listOf(
                SideEffect.ReleaseLock,
                SideEffect.CancelTimeout,
                SideEffect.ScheduleAlreadyOwnedCheck,
            ),
        )
        ScanEvent.UserBack, ScanEvent.ScreenPaused -> transition(
            to = ScanState.Idle,
            sideEffects = listOf(
                SideEffect.ReleaseLock,
                SideEffect.CancelTimeout,
                SideEffect.DiscardPendingArchive,
            ),
        )
        else -> stay(state)
    }

    private fun reduceFromIdentifying(
        state: ScanState.Identifying,
        event: ScanEvent,
    ): ReduceResult = when (event) {
        is ScanEvent.ConsensusReached -> transition(
            to = ScanState.Accepted(
                eurioId = event.eurioId,
                arcfaceTopK = event.topK,
                pendingCaptureId = state.pendingCaptureId,
            ),
            sideEffects = listOf(
                SideEffect.CancelTimeout,
                SideEffect.ScheduleAlreadyOwnedCheck,
            ),
        )
        ScanEvent.IdentifyingTimeout -> transition(
            to = ScanState.Detecting,
            sideEffects = listOf(SideEffect.DiscardPendingArchive),
        )
        ScanEvent.UserBack, ScanEvent.ScreenPaused -> transition(
            to = ScanState.Idle,
            sideEffects = listOf(
                SideEffect.CancelTimeout,
                SideEffect.DiscardPendingArchive,
            ),
        )
        else -> stay(state)
    }

    private fun reduceFromAccepted(
        state: ScanState.Accepted,
        event: ScanEvent,
    ): ReduceResult = when (event) {
        is ScanEvent.ArchiveCompleted -> {
            // Stay Accepted, just flip the flag. The sheet keeps showing.
            // When the consensus jumped straight to Accepted from
            // Detecting/Locking/Capturing (fast path, bypassing
            // Identifying), `pendingCaptureId` is still null at this
            // point — adopt the just-archived id so a subsequent
            // `UserConfirmAdd` can attach it to `coin_in_vault` via the
            // ConfirmPossession side effect.
            val expectedId = state.pendingCaptureId
            val next = when {
                expectedId == null -> state.copy(
                    captureArchived = true,
                    pendingCaptureId = event.captureId,
                )
                expectedId == event.captureId -> state.copy(captureArchived = true)
                else -> state  // stale id, ignore
            }
            stay(next)
        }
        is ScanEvent.ArchiveDiscarded -> stay(state)
        ScanEvent.UserDismiss -> transition(
            to = ScanState.Idle,
            sideEffects = listOf(SideEffect.DiscardPendingArchive),
        )
        ScanEvent.UserConfirmAdd -> transition(
            to = ScanState.Idle,
            sideEffects = listOf(
                SideEffect.ConfirmPossession(state.eurioId, state.pendingCaptureId),
            ),
        )
        ScanEvent.AlreadyOwnedAutoReturn -> transition(
            to = ScanState.Idle,
            sideEffects = listOf(SideEffect.DiscardPendingArchive),
        )
        ScanEvent.UserBack, ScanEvent.ScreenPaused -> transition(
            to = ScanState.Idle,
            sideEffects = listOf(SideEffect.DiscardPendingArchive),
        )
        else -> stay(state)
    }

    private fun reduceFromAborted(
        state: ScanState.Aborted,
        event: ScanEvent,
    ): ReduceResult = when (event) {
        ScanEvent.AbortFlashElapsed -> transition(to = ScanState.Detecting)
        ScanEvent.UserBack, ScanEvent.ScreenPaused -> transition(to = ScanState.Idle)
        else -> stay(state)
    }

    // --- helpers -----------------------------------------------------

    private fun abortFromSubState(previous: String, reason: String): ReduceResult =
        transition(
            to = ScanState.Aborted(reason = reason, previousStateName = previous),
            sideEffects = listOf(
                SideEffect.ReleaseLock,
                SideEffect.CancelTimeout,
                SideEffect.DiscardPendingArchive,
                SideEffect.StartAbortFlashTimer,
            ),
        )

    private fun transition(
        to: ScanState,
        sideEffects: List<SideEffect> = emptyList(),
    ): ReduceResult = ReduceResult(to, sideEffects)

    private fun stay(state: ScanState): ReduceResult = ReduceResult(state, emptyList())
}

/**
 * Side effects the runtime must apply after the reducer returns. The
 * order in the list is the apply order.
 */
sealed class SideEffect {
    /** Reset the active `TriggerStrategy` — only at `Idle → Detecting` (cooldown). */
    object ResetTrigger : SideEffect()

    /** Start the AE/AF/AWB lock via `CameraLockController.lock(...)`. */
    object StartLock : SideEffect()

    /** Release any AE/AF/AWB lock currently held. */
    object ReleaseLock : SideEffect()

    /** Start full-resolution capture via `ImageCapture.takePicture(...)`. */
    object StartCapture : SideEffect()

    /** Drop the staged JPEG in `PendingArchiveBuffer` — abort/back/dismiss. */
    object DiscardPendingArchive : SideEffect()

    /** Schedule a single state-machine timeout — cancels any pending one. */
    data class StartTimeout(val durationMs: Long) : SideEffect()

    /** Cancel any pending timeout — used when leaving a timeable state early. */
    object CancelTimeout : SideEffect()

    /** Schedule the 200 ms abort-flash timer. */
    object StartAbortFlashTimer : SideEffect()

    /** Watch for `NoDetectionStreak` while in [ScanState.Detecting]. */
    object ScheduleNoDetectionWatcher : SideEffect()

    /** Resolve already-owned status and schedule auto-return if needed. */
    object ScheduleAlreadyOwnedCheck : SideEffect()

    /**
     * User confirmed possession on the accepted sheet (D24). Delegates
     * to `VaultCaptureRepository.confirmPossession(eurioId, captureId?)`.
     * `captureId` may be null (archive failed or trigger=OFF path) —
     * `confirmPossession` then creates a `coin_in_vault` without
     * primary, the vault UI falls back to the catalog image.
     */
    data class ConfirmPossession(val eurioId: String, val captureId: String?) : SideEffect()
}

data class ReduceResult(
    val nextState: ScanState,
    val sideEffects: List<SideEffect>,
)
