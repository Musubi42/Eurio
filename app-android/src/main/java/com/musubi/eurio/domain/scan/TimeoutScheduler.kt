package com.musubi.eurio.domain.scan

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Owns the **single** outstanding state-machine timeout. The reducer
 * emits `SideEffect.StartTimeout` / `CancelTimeout` ; the runtime
 * forwards those calls here. The next firing event is decided by the
 * state at the moment `start` is invoked, so timeout payloads can't
 * desync with the state.
 *
 * Pure I/O wrapper — no transition logic lives here.
 */
class TimeoutScheduler(
    private val scope: CoroutineScope,
    private val emit: (ScanEvent) -> Unit,
) {
    private var job: Job? = null

    /**
     * Schedule the timeout matching [currentState]. States without a
     * timeout (Idle, Detecting, Accepted, Aborted) are no-ops, but the
     * pending timer is still cancelled to avoid stale firings.
     */
    fun start(currentState: ScanState, durationMs: Long) {
        cancel()
        val timeoutEvent = currentState.timeoutEvent() ?: return
        job = scope.launch {
            delay(durationMs)
            emit(timeoutEvent)
        }
    }

    fun cancel() {
        job?.cancel()
        job = null
    }

    /** Single-shot 200 ms abort-flash timer (replaces any pending job). */
    fun scheduleAbortFlashElapsed() {
        cancel()
        job = scope.launch {
            delay(ScanReducer.ABORT_FLASH_MS)
            emit(ScanEvent.AbortFlashElapsed)
        }
    }

    /** Single-shot 2 s already-owned auto-return timer. */
    fun scheduleAlreadyOwnedAutoReturn() {
        cancel()
        job = scope.launch {
            delay(ScanReducer.ALREADY_OWNED_AUTO_RETURN_MS)
            emit(ScanEvent.AlreadyOwnedAutoReturn)
        }
    }
}

private fun ScanState.timeoutEvent(): ScanEvent? = when (this) {
    is ScanState.Locking -> ScanEvent.LockingTimeout
    is ScanState.Capturing -> ScanEvent.CapturingTimeout
    is ScanState.Identifying -> ScanEvent.IdentifyingTimeout
    else -> null
}
