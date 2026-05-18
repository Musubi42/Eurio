package com.musubi.eurio.ml.camera

import android.hardware.camera2.CaptureRequest
import android.os.SystemClock
import androidx.annotation.OptIn
import androidx.camera.camera2.interop.Camera2CameraControl
import androidx.camera.camera2.interop.CaptureRequestOptions
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.Camera
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.SurfaceOrientedMeteringPointFactory
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.guava.await
import kotlinx.coroutines.withTimeout

/**
 * Wraps `Camera.cameraControl` + `Camera2CameraControl` to drive AE/AF/AWB
 * lock when the best-frame trigger fires (chunk-4, D11).
 *
 * Lifecycle: one instance per camera session, instantiated from the
 * `CameraPreview` composable once `bindToLifecycle` returns and discarded on
 * its `DisposableEffect.onDispose`. All `lock(...)` / `release()` calls are
 * idempotent — `release()` can be invoked from `returnToIdle`, the dispose
 * effect, and an Abort event without breaking state.
 *
 * Threading: must be driven from `viewModelScope` (or any scope tied to the
 * UI lifecycle). The CameraX `await()` calls dispatch internally and emit
 * state on the calling context.
 */
@OptIn(markerClass = [ExperimentalCamera2Interop::class])
class CameraLockController(
    camera: Camera,
) {
    private val cameraControl = camera.cameraControl
    private val camera2Control = Camera2CameraControl.from(cameraControl)

    private val _state = MutableStateFlow<LockState>(LockState.Idle)
    val state: StateFlow<LockState> = _state.asStateFlow()

    suspend fun lock(options: LockOptions) {
        if (!options.aeLock && !options.afLock && !options.awbLock) {
            return
        }

        val startedNs = SystemClock.elapsedRealtimeNanos()
        _state.value = LockState.Acquiring

        val afConverged: Boolean = if (options.afLock) {
            // SurfaceOriented coords are normalized 0..1 in the analyzer
            // buffer space — stable across device rotation. `disableAutoCancel`
            // is critical: without it CameraX schedules an auto-cancel after a
            // few seconds and the lock drops on its own. We own the release.
            val factory = SurfaceOrientedMeteringPointFactory(1f, 1f)
            val point = factory.createPoint(options.region.centerX, options.region.centerY)
            val action = FocusMeteringAction.Builder(point, FocusMeteringAction.FLAG_AF)
                .disableAutoCancel()
                .build()

            try {
                withTimeout(options.afTimeoutMs) {
                    cameraControl.startFocusAndMetering(action).await().isFocusSuccessful
                }
            } catch (e: TimeoutCancellationException) {
                false
            } catch (e: Exception) {
                _state.value = LockState.Failed(
                    reason = "AF startFocusAndMetering threw: ${e.message}",
                    durationMs = elapsedMs(startedNs),
                )
                return
            }
        } else {
            true
        }

        if (options.aeLock || options.awbLock) {
            val captureOptions = CaptureRequestOptions.Builder().apply {
                if (options.aeLock) setCaptureRequestOption(CaptureRequest.CONTROL_AE_LOCK, true)
                if (options.awbLock) setCaptureRequestOption(CaptureRequest.CONTROL_AWB_LOCK, true)
            }.build()
            try {
                camera2Control.setCaptureRequestOptions(captureOptions).await()
            } catch (e: Exception) {
                _state.value = LockState.Failed(
                    reason = "setCaptureRequestOptions threw: ${e.message}",
                    durationMs = elapsedMs(startedNs),
                )
                return
            }
        }

        _state.value = LockState.Locked(
            acquiredAtNs = SystemClock.elapsedRealtimeNanos(),
            durationMs = elapsedMs(startedNs),
            afConverged = afConverged,
            aeLocked = options.aeLock,
            awbLocked = options.awbLock,
        )
    }

    suspend fun release() {
        try {
            camera2Control.setCaptureRequestOptions(
                CaptureRequestOptions.Builder()
                    .setCaptureRequestOption(CaptureRequest.CONTROL_AE_LOCK, false)
                    .setCaptureRequestOption(CaptureRequest.CONTROL_AWB_LOCK, false)
                    .build()
            ).await()
            cameraControl.cancelFocusAndMetering().await()
        } catch (_: Exception) {
            // Best-effort release — never propagate. The next bindToLifecycle
            // would reset all CaptureRequest fields anyway.
        }
        _state.value = LockState.Released
        _state.value = LockState.Idle
    }

    private fun elapsedMs(startedNs: Long): Long =
        (SystemClock.elapsedRealtimeNanos() - startedNs) / 1_000_000L
}
