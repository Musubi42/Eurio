package com.musubi.eurio.ml.trigger

/**
 * D8 selection logic: pick the **oldest** frame that already passes every
 * active gate (early-stop, minimal latency), or fall back to the highest
 * aggregate score when no frame qualifies.
 *
 * "Oldest qualifier" instead of "newest qualifier" is a deliberate latency
 * trade-off (cf. chunk-3 doc §BestFrameSelector). It assumes that the moment
 * the user *first* held the coin steady is more representative than the
 * latest frame, which may be the start of the user pulling away. To revisit
 * at chunk-7 if empirical data argues the other way.
 */
class BestFrameSelector {

    fun select(snapshot: List<BufferedFrame>): SelectionResult {
        if (snapshot.isEmpty()) return SelectionResult.Empty

        snapshot.forEachIndexed { idx, frame ->
            if (frame.score.passes.all) {
                return SelectionResult.Best(
                    frame = frame,
                    indexInSnapshot = idx,
                    reason = SelectionReason.PASSED_ALL_GATES,
                )
            }
        }

        var bestIdx = 0
        var bestAgg = snapshot[0].score.aggregate
        for (i in 1 until snapshot.size) {
            val agg = snapshot[i].score.aggregate
            if (agg > bestAgg) {
                bestAgg = agg
                bestIdx = i
            }
        }
        return SelectionResult.Best(
            frame = snapshot[bestIdx],
            indexInSnapshot = bestIdx,
            reason = SelectionReason.BEST_AGGREGATE_FALLBACK,
        )
    }
}
