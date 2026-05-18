package com.musubi.eurio.domain.scan

import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Table-driven verification of [ScanReducer]. The reducer is a pure
 * function `(state, event, now) → (state, [sideEffect])` so every
 * branch can be asserted directly without coroutines / mocks. Coverage
 * goal : every state's `when` branch hit at least once, plus the
 * invariants from `chunk-6-state-machine.md` (cooldown, consensus
 * shortcut, abort flow, archive flag flip).
 */
class ScanReducerTest {

    private val now = 12_345L
    private val sampleLock = LockResultSnapshot(
        durationMs = 420,
        afConverged = true,
        aeLocked = true,
        awbLocked = true,
    )
    private val sampleTopK = listOf(
        ArcfaceMatch("fr-2002-2eur-standard", 0.91f),
        ArcfaceMatch("de-2002-2eur-standard", 0.74f),
    )

    private fun reduce(state: ScanState, event: ScanEvent) =
        ScanReducer.reduce(state, event, now)

    // --- Idle -------------------------------------------------------

    @Test
    fun `Idle plus FirstDetection moves to Detecting and resets trigger`() {
        val r = reduce(ScanState.Idle, ScanEvent.FirstDetection)
        assertEquals(ScanState.Detecting, r.nextState)
        assertTrue(SideEffect.ResetTrigger in r.sideEffects)
        assertTrue(SideEffect.ScheduleNoDetectionWatcher in r.sideEffects)
    }

    @Test
    fun `Idle ignores most events`() {
        listOf(
            ScanEvent.NoDetectionStreak,
            ScanEvent.TriggerAbort,
            ScanEvent.LockingTimeout,
            ScanEvent.UserDismiss,
            ScanEvent.AbortFlashElapsed,
        ).forEach { e ->
            val r = reduce(ScanState.Idle, e)
            assertEquals("event $e should not leave Idle", ScanState.Idle, r.nextState)
            assertTrue(r.sideEffects.isEmpty())
        }
    }

    // --- Detecting --------------------------------------------------

    @Test
    fun `Detecting plus NoDetectionStreak returns to Idle`() {
        val r = reduce(ScanState.Detecting, ScanEvent.NoDetectionStreak)
        assertEquals(ScanState.Idle, r.nextState)
        assertTrue(r.sideEffects.isEmpty())
    }

    @Test
    fun `Detecting plus TriggerFire moves to Locking and starts lock plus timeout`() {
        val r = reduce(ScanState.Detecting, ScanEvent.TriggerFire("stability_locked"))
        val locking = r.nextState as ScanState.Locking
        assertEquals("stability_locked", locking.triggerReason)
        assertEquals(now, locking.sinceNs)
        assertTrue(SideEffect.StartLock in r.sideEffects)
        assertTrue(r.sideEffects.contains(SideEffect.StartTimeout(ScanReducer.LOCKING_TIMEOUT_MS)))
    }

    @Test
    fun `Detecting plus ConsensusReached jumps straight to Accepted`() {
        val r = reduce(
            ScanState.Detecting,
            ScanEvent.ConsensusReached("fr-2002-2eur-standard", sampleTopK),
        )
        val accepted = r.nextState as ScanState.Accepted
        assertEquals("fr-2002-2eur-standard", accepted.eurioId)
        assertEquals(sampleTopK, accepted.arcfaceTopK)
        assertEquals(false, accepted.captureArchived)
        assertEquals(null, accepted.pendingCaptureId)
        assertTrue(SideEffect.ScheduleAlreadyOwnedCheck in r.sideEffects)
    }

    @Test
    fun `Detecting plus ScreenPaused or UserBack returns to Idle`() {
        assertEquals(ScanState.Idle, reduce(ScanState.Detecting, ScanEvent.ScreenPaused).nextState)
        assertEquals(ScanState.Idle, reduce(ScanState.Detecting, ScanEvent.UserBack).nextState)
    }

    // --- Locking ----------------------------------------------------

    private fun lockingState() = ScanState.Locking("stability_locked", now - 10)

    @Test
    fun `Locking plus LockAcquired moves to Capturing with capture plus timeout`() {
        val r = reduce(lockingState(), ScanEvent.LockAcquired(sampleLock))
        val capturing = r.nextState as ScanState.Capturing
        assertEquals(sampleLock, capturing.lockResult)
        assertEquals(now, capturing.sinceNs)
        assertTrue(SideEffect.StartCapture in r.sideEffects)
        assertTrue(r.sideEffects.contains(SideEffect.StartTimeout(ScanReducer.CAPTURING_TIMEOUT_MS)))
    }

    @Test
    fun `Locking plus LockFailed aborts with release plus flash`() {
        val r = reduce(lockingState(), ScanEvent.LockFailed("af_never_converged"))
        val aborted = r.nextState as ScanState.Aborted
        assertEquals("Locking", aborted.previousStateName)
        assertEquals("lock_failed:af_never_converged", aborted.reason)
        assertAbortCleanup(r.sideEffects)
    }

    @Test
    fun `Locking plus LockingTimeout aborts`() {
        val r = reduce(lockingState(), ScanEvent.LockingTimeout)
        val aborted = r.nextState as ScanState.Aborted
        assertEquals("lock_timeout", aborted.reason)
        assertEquals("Locking", aborted.previousStateName)
        assertAbortCleanup(r.sideEffects)
    }

    @Test
    fun `Locking plus TriggerAbort aborts with bbox_lost reason`() {
        val r = reduce(lockingState(), ScanEvent.TriggerAbort)
        val aborted = r.nextState as ScanState.Aborted
        assertEquals("bbox_lost", aborted.reason)
        assertEquals("Locking", aborted.previousStateName)
    }

    @Test
    fun `Locking plus ConsensusReached jumps to Accepted and releases lock`() {
        val r = reduce(lockingState(), ScanEvent.ConsensusReached("fr-id", sampleTopK))
        val accepted = r.nextState as ScanState.Accepted
        assertEquals("fr-id", accepted.eurioId)
        assertTrue(SideEffect.ReleaseLock in r.sideEffects)
        assertTrue(SideEffect.CancelTimeout in r.sideEffects)
        assertTrue(SideEffect.ScheduleAlreadyOwnedCheck in r.sideEffects)
    }

    @Test
    fun `Locking plus UserBack drops to Idle with full cleanup`() {
        val r = reduce(lockingState(), ScanEvent.UserBack)
        assertEquals(ScanState.Idle, r.nextState)
        assertTrue(SideEffect.ReleaseLock in r.sideEffects)
        assertTrue(SideEffect.CancelTimeout in r.sideEffects)
        assertTrue(SideEffect.DiscardPendingArchive in r.sideEffects)
    }

    @Test
    fun `Locking ignores irrelevant events`() {
        val s = lockingState()
        val r = reduce(s, ScanEvent.NoDetectionStreak)
        assertSame(s, r.nextState)
        assertTrue(r.sideEffects.isEmpty())
    }

    // --- Capturing --------------------------------------------------

    private fun capturingState() = ScanState.Capturing(sampleLock, now - 50)

    @Test
    fun `Capturing plus CaptureCompleted moves to Identifying with timeout`() {
        val r = reduce(
            capturingState(),
            ScanEvent.CaptureCompleted("cap-1", SourceMode.IMAGE_CAPTURE_FULL),
        )
        val identifying = r.nextState as ScanState.Identifying
        assertEquals("cap-1", identifying.pendingCaptureId)
        assertEquals(SourceMode.IMAGE_CAPTURE_FULL, identifying.sourceMode)
        assertEquals(now, identifying.sinceNs)
        assertTrue(SideEffect.ReleaseLock in r.sideEffects)
        assertTrue(r.sideEffects.contains(SideEffect.StartTimeout(ScanReducer.IDENTIFYING_TIMEOUT_MS)))
    }

    @Test
    fun `Capturing plus CaptureError falls back to YUV identifying`() {
        val r = reduce(capturingState(), ScanEvent.CaptureError("hal_busy"))
        val identifying = r.nextState as ScanState.Identifying
        assertEquals(SourceMode.YUV_PREVIEW_FALLBACK, identifying.sourceMode)
    }

    @Test
    fun `Capturing plus CapturingTimeout aborts`() {
        val r = reduce(capturingState(), ScanEvent.CapturingTimeout)
        val aborted = r.nextState as ScanState.Aborted
        assertEquals("capture_timeout", aborted.reason)
        assertEquals("Capturing", aborted.previousStateName)
        assertAbortCleanup(r.sideEffects)
    }

    @Test
    fun `Capturing plus TriggerAbort aborts as bbox_lost`() {
        val r = reduce(capturingState(), ScanEvent.TriggerAbort)
        val aborted = r.nextState as ScanState.Aborted
        assertEquals("bbox_lost", aborted.reason)
        assertEquals("Capturing", aborted.previousStateName)
    }

    @Test
    fun `Capturing plus ConsensusReached jumps to Accepted`() {
        val r = reduce(capturingState(), ScanEvent.ConsensusReached("fr-id", sampleTopK))
        val accepted = r.nextState as ScanState.Accepted
        assertEquals("fr-id", accepted.eurioId)
        assertTrue(SideEffect.ReleaseLock in r.sideEffects)
    }

    // --- Identifying ------------------------------------------------

    private fun identifyingState() = ScanState.Identifying(
        pendingCaptureId = "cap-42",
        sourceMode = SourceMode.IMAGE_CAPTURE_FULL,
        sinceNs = now - 100,
    )

    @Test
    fun `Identifying plus ConsensusReached carries pendingCaptureId forward`() {
        val r = reduce(identifyingState(), ScanEvent.ConsensusReached("fr-id", sampleTopK))
        val accepted = r.nextState as ScanState.Accepted
        assertEquals("cap-42", accepted.pendingCaptureId)
        assertTrue(SideEffect.CancelTimeout in r.sideEffects)
    }

    @Test
    fun `Identifying plus IdentifyingTimeout drops back to Detecting`() {
        val r = reduce(identifyingState(), ScanEvent.IdentifyingTimeout)
        assertEquals(ScanState.Detecting, r.nextState)
        assertTrue(SideEffect.DiscardPendingArchive in r.sideEffects)
    }

    @Test
    fun `Identifying plus UserBack drops to Idle with cleanup`() {
        val r = reduce(identifyingState(), ScanEvent.UserBack)
        assertEquals(ScanState.Idle, r.nextState)
        assertTrue(SideEffect.CancelTimeout in r.sideEffects)
        assertTrue(SideEffect.DiscardPendingArchive in r.sideEffects)
    }

    // --- Accepted ---------------------------------------------------

    private fun acceptedState(captureId: String? = "cap-42") = ScanState.Accepted(
        eurioId = "fr-2002-2eur-standard",
        arcfaceTopK = sampleTopK,
        captureArchived = false,
        pendingCaptureId = captureId,
    )

    @Test
    fun `Accepted plus ArchiveCompleted flips captureArchived flag when ids match`() {
        val r = reduce(acceptedState(), ScanEvent.ArchiveCompleted("cap-42"))
        val accepted = r.nextState as ScanState.Accepted
        assertEquals(true, accepted.captureArchived)
        assertTrue(r.sideEffects.isEmpty())
    }

    @Test
    fun `Accepted plus ArchiveCompleted ignores stale captureId`() {
        val r = reduce(acceptedState(), ScanEvent.ArchiveCompleted("other"))
        val accepted = r.nextState as ScanState.Accepted
        assertEquals(false, accepted.captureArchived)
    }

    @Test
    fun `Accepted plus ArchiveCompleted flips and adopts captureId when pendingCaptureId is null`() {
        // ConsensusReached from Detecting/Locking/Capturing path: no pending
        // capture id yet but a later capture/archive may still complete.
        // The reducer must adopt the just-archived id so UserConfirmAdd can
        // attach it via ConfirmPossession (cleanup post-6.2c).
        val r = reduce(acceptedState(captureId = null), ScanEvent.ArchiveCompleted("late-cap"))
        val accepted = r.nextState as ScanState.Accepted
        assertEquals(true, accepted.captureArchived)
        assertEquals("late-cap", accepted.pendingCaptureId)
    }

    @Test
    fun `Accepted plus UserConfirmAdd emits ConfirmPossession and returns to Idle`() {
        val r = reduce(acceptedState(), ScanEvent.UserConfirmAdd)
        assertEquals(ScanState.Idle, r.nextState)
        val confirm = r.sideEffects.filterIsInstance<SideEffect.ConfirmPossession>().single()
        assertEquals("fr-2002-2eur-standard", confirm.eurioId)
        assertEquals("cap-42", confirm.captureId)
    }

    @Test
    fun `Accepted plus UserDismiss discards pending archive`() {
        val r = reduce(acceptedState(), ScanEvent.UserDismiss)
        assertEquals(ScanState.Idle, r.nextState)
        assertTrue(SideEffect.DiscardPendingArchive in r.sideEffects)
    }

    @Test
    fun `Accepted plus AlreadyOwnedAutoReturn returns to Idle`() {
        val r = reduce(acceptedState(), ScanEvent.AlreadyOwnedAutoReturn)
        assertEquals(ScanState.Idle, r.nextState)
    }

    // --- Aborted ----------------------------------------------------

    private fun abortedState() = ScanState.Aborted(
        reason = "lock_timeout",
        previousStateName = "Locking",
    )

    @Test
    fun `Aborted plus AbortFlashElapsed returns to Detecting`() {
        val r = reduce(abortedState(), ScanEvent.AbortFlashElapsed)
        assertEquals(ScanState.Detecting, r.nextState)
    }

    @Test
    fun `Aborted plus UserBack returns directly to Idle`() {
        val r = reduce(abortedState(), ScanEvent.UserBack)
        assertEquals(ScanState.Idle, r.nextState)
    }

    @Test
    fun `Aborted ignores stale lock or capture events`() {
        val s = abortedState()
        assertSame(s, reduce(s, ScanEvent.LockAcquired(sampleLock)).nextState)
        assertSame(s, reduce(s, ScanEvent.CaptureCompleted("cap", SourceMode.IMAGE_CAPTURE_FULL)).nextState)
    }

    // --- Invariants -------------------------------------------------

    @Test
    fun `ResetTrigger fires exactly on Idle to Detecting transition`() {
        val toDetecting = reduce(ScanState.Idle, ScanEvent.FirstDetection)
        assertTrue(SideEffect.ResetTrigger in toDetecting.sideEffects)

        // Sub-state to Detecting (IdentifyingTimeout) must NOT reset trigger —
        // we don't want the strategy to forget its cooldown mid-scan.
        val timeoutDrop = reduce(identifyingState(), ScanEvent.IdentifyingTimeout)
        assertEquals(ScanState.Detecting, timeoutDrop.nextState)
        assertTrue(SideEffect.ResetTrigger !in timeoutDrop.sideEffects)

        // Aborted to Detecting (AbortFlashElapsed) must NOT reset trigger.
        val flashElapsed = reduce(abortedState(), ScanEvent.AbortFlashElapsed)
        assertEquals(ScanState.Detecting, flashElapsed.nextState)
        assertTrue(SideEffect.ResetTrigger !in flashElapsed.sideEffects)
    }

    private fun assertAbortCleanup(effects: List<SideEffect>) {
        assertTrue("ReleaseLock missing", SideEffect.ReleaseLock in effects)
        assertTrue("CancelTimeout missing", SideEffect.CancelTimeout in effects)
        assertTrue("DiscardPendingArchive missing", SideEffect.DiscardPendingArchive in effects)
        assertTrue("StartAbortFlashTimer missing", SideEffect.StartAbortFlashTimer in effects)
    }
}
