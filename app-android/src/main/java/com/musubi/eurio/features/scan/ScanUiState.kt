package com.musubi.eurio.features.scan

import com.musubi.eurio.data.repository.CoinViewData

/**
 * Presentation state consumed by [ScanScreen]. The actual state machine
 * lives in [com.musubi.eurio.domain.scan.ScanState] (chunk-6) — this
 * type is a thin UI projection that carries the resolved coin payload
 * needed to render the Accepted sheet.
 *
 *   shadow.Idle                              → ui.Idle
 *   shadow.Detecting / Locking / Capturing
 *           / Identifying / Aborted          → ui.Detecting
 *   shadow.Accepted (+ coin resolved)        → ui.Accepted(...)
 *
 * Two presentation-only cases — [NotIdentified] and [Failure] — are
 * kept solely so the QA parity flows can inject them for screenshots
 * (`eurio://scene/...?scan_state=not-identified`). The live pipeline
 * never produces them today.
 *
 * [CoinViewData] is defined in the data layer and re-used here so the
 * scan feature does not own a duplicate view DTO.
 */
sealed class ScanUiState {
    object Idle : ScanUiState()

    object Detecting : ScanUiState()

    data class Accepted(
        val coin: CoinViewData,
        val confidence: Float,
        val alreadyOwned: Boolean,
        /**
         * Capture id (chunk-5c) of the JPEG archived for this scan.
         * Non-null when the best-frame pipeline produced a file matching
         * this consensus within the
         * [com.musubi.eurio.data.vault.PendingArchiveBuffer] window.
         * Used by [ScanViewModel.onAddToVault] to attach the most recent
         * capture as the primary on confirmPossession.
         */
        val captureId: String? = null,
    ) : ScanUiState()

    /** QA-parity injection only. */
    data class NotIdentified(
        val top5: List<CoinViewData>,
    ) : ScanUiState()

    /** QA-parity injection only. */
    data class Failure(
        val reason: String,
    ) : ScanUiState()
}
