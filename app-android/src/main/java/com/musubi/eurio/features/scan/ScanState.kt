package com.musubi.eurio.features.scan

import com.musubi.eurio.data.repository.CoinViewData

/**
 * State machine for the Scan feature.
 *
 * Transitions are driven by [ScanViewModel] as it observes the underlying
 * [com.musubi.eurio.ml.CoinAnalyzer] pipeline:
 *
 *   Idle → Detecting  (first frame with an accepted detection)
 *   Detecting → Accepted  (consensus reached, coin identified)
 *   Detecting → NotIdentified  (6s without accepted consensus)
 *   * → Failure  (pipeline error, permission loss, etc.)
 *   Accepted/NotIdentified/Failure → Idle  (user dismiss or cooldown expires)
 *
 * [CoinViewData] is defined in the data layer ([com.musubi.eurio.data.repository])
 * and re-used here so the scan feature does not own a duplicate view DTO.
 */
sealed class ScanState {
    object Idle : ScanState()

    object Detecting : ScanState()

    data class Accepted(
        val coin: CoinViewData,
        val confidence: Float,
        val alreadyOwned: Boolean,
    ) : ScanState()

    data class NotIdentified(
        val top5: List<CoinViewData>,
    ) : ScanState()

    data class Failure(
        val reason: String,
    ) : ScanState()
}
