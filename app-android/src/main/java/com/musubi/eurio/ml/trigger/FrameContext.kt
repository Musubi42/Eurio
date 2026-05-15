package com.musubi.eurio.ml.trigger

import com.musubi.eurio.ml.CoinMatch
import com.musubi.eurio.ml.DetectionSource

/**
 * Snapshot passed to [TriggerStrategy.observe] every analyzed frame.
 *
 * `primary…` fields describe the current frame's selected detection (may be
 * null if nothing was detected). `buffer` is a chronological lecture-seule
 * snapshot of the rolling buffer, oldest first.
 *
 * `consensusLockedClass` mirrors [com.musubi.eurio.features.scan.ConsensusBuffer.consensus]
 * at the moment the trigger is observing — populated post-`consensus.push` in
 * the ViewModel so the [ml/trigger/ArcfaceConsensusTrigger] (chunk-3b) sees
 * the same value as the rest of the scan pipeline.
 */
data class FrameContext(
    val sequenceId: Int,
    val buffer: List<BufferedFrame>,
    val primaryBbox: BboxF?,
    val primaryConfidence: Float?,
    val primarySource: DetectionSource?,
    val arcfaceTop1: CoinMatch?,
    val consensusLockedClass: String?,
)
