package com.musubi.eurio.data.vault

import com.musubi.eurio.domain.scan.SourceMode
import com.musubi.eurio.domain.scan.quality.FrameScore
import com.musubi.eurio.ml.DetectionSource
import com.musubi.eurio.features.scan.debug.TimingBreakdown
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PendingArchiveBufferTest {

    private var fakeNow = 0L
    private val buffer = PendingArchiveBuffer(timeoutMs = 3_000L, nowMs = { fakeNow })

    private val sampleScore = FrameScore.Failed
    private val sampleMetadata = CaptureMetadata(
        frameScore = sampleScore,
        detectionBbox = null,
        detectionConfidence = null,
        detectionSource = null,
        triggerMode = "OFF",
        triggerFireReason = null,
        lockResult = null,
        arcfaceTop3 = emptyList(),
        sourceMode = SourceMode.IMAGE_CAPTURE_FULL,
        timings = TimingBreakdown(),
        deviceModel = "test",
        androidApi = 34,
    )

    @Test
    fun set_thenConsume_returnsPending() = runBlocking {
        buffer.set("cap-1", byteArrayOf(1, 2), sampleScore, sampleMetadata)
        val p = buffer.consume("fr-2eur-2024")
        assertTrue(p != null && p.captureId == "cap-1")
    }

    @Test
    fun consume_emptiesBuffer() = runBlocking {
        buffer.set("cap-1", byteArrayOf(1), sampleScore, sampleMetadata)
        assertTrue(buffer.hasPending())
        buffer.consume("any")
        assertFalse(buffer.hasPending())
    }

    @Test
    fun consume_returnsNull_whenEmpty() = runBlocking {
        assertNull(buffer.consume("any"))
    }

    @Test
    fun set_overwritesPrevious() = runBlocking {
        buffer.set("cap-1", byteArrayOf(1), sampleScore, sampleMetadata)
        buffer.set("cap-2", byteArrayOf(2, 2), sampleScore, sampleMetadata)
        val p = buffer.consume("any")!!
        assertEquals("cap-2", p.captureId)
        assertEquals(2, p.jpegBytes.size)
    }

    @Test
    fun consume_returnsNull_whenExpired() = runBlocking {
        fakeNow = 1_000L
        buffer.set("cap-1", byteArrayOf(1), sampleScore, sampleMetadata)
        fakeNow = 1_000L + 3_001L  // 1 ms past the 3 s timeout
        assertNull(buffer.consume("any"))
        // expired consume still clears the slot
        assertFalse(buffer.hasPending())
    }

    @Test
    fun consume_succeeds_atExactTimeout() = runBlocking {
        fakeNow = 0L
        buffer.set("cap-1", byteArrayOf(1), sampleScore, sampleMetadata)
        fakeNow = 3_000L  // exactly at the boundary — still valid
        assertTrue(buffer.consume("any") != null)
    }

    @Test
    fun clear_dropsPending() = runBlocking {
        buffer.set("cap-1", byteArrayOf(1), sampleScore, sampleMetadata)
        buffer.clear()
        assertFalse(buffer.hasPending())
        assertNull(buffer.consume("any"))
    }

    @Test
    fun hasPending_reflectsExpiration() = runBlocking {
        fakeNow = 0L
        buffer.set("cap-1", byteArrayOf(1), sampleScore, sampleMetadata)
        assertTrue(buffer.hasPending())
        fakeNow = 3_001L
        assertFalse(buffer.hasPending())
    }

    @Suppress("UNUSED")
    private fun ignoreUnusedDetectionSourceImport() = DetectionSource.YOLO
}
