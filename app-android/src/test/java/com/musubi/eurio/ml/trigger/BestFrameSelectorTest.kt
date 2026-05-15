package com.musubi.eurio.ml.trigger

import com.musubi.eurio.domain.scan.quality.FrameScore
import com.musubi.eurio.domain.scan.quality.GatesResult
import com.musubi.eurio.ml.DetectionSource
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BestFrameSelectorTest {

    private val selector = BestFrameSelector()

    @Test
    fun `empty snapshot returns Empty`() {
        val result = selector.select(emptyList())
        assertTrue(result is SelectionResult.Empty)
    }

    @Test
    fun `oldest frame passing all gates is selected with PASSED_ALL_GATES`() {
        // seq 1: fails, 2: passes, 3: passes (higher aggregate) — selector
        // picks 2 because it's the oldest qualifier, not the highest aggregate.
        val snapshot = listOf(
            frame(seqId = 1, aggregate = 0.3f, passesAll = false),
            frame(seqId = 2, aggregate = 0.7f, passesAll = true),
            frame(seqId = 3, aggregate = 0.95f, passesAll = true),
        )
        val result = selector.select(snapshot) as SelectionResult.Best
        assertEquals(SelectionReason.PASSED_ALL_GATES, result.reason)
        assertEquals(2, result.frame.sequenceId)
        assertEquals(1, result.indexInSnapshot)
    }

    @Test
    fun `no qualifying frame falls back to best aggregate`() {
        val snapshot = listOf(
            frame(seqId = 1, aggregate = 0.3f, passesAll = false),
            frame(seqId = 2, aggregate = 0.7f, passesAll = false),
            frame(seqId = 3, aggregate = 0.5f, passesAll = false),
        )
        val result = selector.select(snapshot) as SelectionResult.Best
        assertEquals(SelectionReason.BEST_AGGREGATE_FALLBACK, result.reason)
        assertEquals(2, result.frame.sequenceId)
        assertEquals(1, result.indexInSnapshot)
    }

    @Test
    fun `single frame all-pass returns PASSED_ALL_GATES`() {
        val snapshot = listOf(frame(seqId = 1, aggregate = 0.4f, passesAll = true))
        val result = selector.select(snapshot) as SelectionResult.Best
        assertEquals(SelectionReason.PASSED_ALL_GATES, result.reason)
        assertEquals(0, result.indexInSnapshot)
    }

    @Test
    fun `single frame failing returns BEST_AGGREGATE_FALLBACK`() {
        val snapshot = listOf(frame(seqId = 1, aggregate = 0.1f, passesAll = false))
        val result = selector.select(snapshot) as SelectionResult.Best
        assertEquals(SelectionReason.BEST_AGGREGATE_FALLBACK, result.reason)
        assertEquals(0, result.indexInSnapshot)
    }

    private fun frame(seqId: Int, aggregate: Float, passesAll: Boolean): BufferedFrame =
        BufferedFrame(
            sequenceId = seqId,
            timestampNs = seqId.toLong(),
            crop = null,
            score = FrameScore(
                sharpness = 0f,
                sharpnessRaw = 0f,
                exposure = 0f,
                meanLuminance = 0f,
                clippingRatio = 0f,
                completeness = 0f,
                motion = null,
                aggregate = aggregate,
                passes = GatesResult(
                    sharpness = passesAll,
                    exposure = passesAll,
                    completeness = passesAll,
                    motion = null,
                    all = passesAll,
                ),
            ),
            bbox = BboxF(0f, 0f, 0f, 0f),
            detectionConfidence = 0f,
            detectionSource = DetectionSource.YOLO,
            arcfaceTop3 = emptyList(),
        )
}
