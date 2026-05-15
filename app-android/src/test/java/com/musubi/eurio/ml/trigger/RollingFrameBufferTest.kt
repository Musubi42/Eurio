package com.musubi.eurio.ml.trigger

import com.musubi.eurio.domain.scan.quality.FrameScore
import com.musubi.eurio.domain.scan.quality.GatesResult
import com.musubi.eurio.ml.DetectionSource
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class RollingFrameBufferTest {

    @Test
    fun `push beyond capacity evicts oldest in order`() {
        val evicted = mutableListOf<Int>()
        val buffer = RollingFrameBuffer(initialCapacity = 3, onEvict = { evicted.add(it.sequenceId) })

        (1..5).forEach { buffer.push(makeFrame(it)) }

        // 5 pushed, capacity 3 → frames 1 and 2 evicted in that order.
        assertEquals(listOf(1, 2), evicted)
        assertEquals(3, buffer.size)
        assertEquals(listOf(3, 4, 5), buffer.snapshot().map { it.sequenceId })
    }

    @Test
    fun `setCapacity shrink evicts excess in chronological order`() {
        val evicted = mutableListOf<Int>()
        val buffer = RollingFrameBuffer(initialCapacity = 5, onEvict = { evicted.add(it.sequenceId) })
        (1..5).forEach { buffer.push(makeFrame(it)) }

        buffer.setCapacity(2)

        assertEquals(listOf(1, 2, 3), evicted)
        assertEquals(listOf(4, 5), buffer.snapshot().map { it.sequenceId })
        assertEquals(2, buffer.capacity)
    }

    @Test
    fun `setCapacity grow keeps existing frames intact`() {
        val evicted = mutableListOf<Int>()
        val buffer = RollingFrameBuffer(initialCapacity = 3, onEvict = { evicted.add(it.sequenceId) })
        (1..3).forEach { buffer.push(makeFrame(it)) }

        buffer.setCapacity(8)

        assertTrue(evicted.isEmpty())
        assertEquals(8, buffer.capacity)
        assertEquals(listOf(1, 2, 3), buffer.snapshot().map { it.sequenceId })
    }

    @Test
    fun `setCapacity to same value is a no-op`() {
        val evicted = mutableListOf<Int>()
        val buffer = RollingFrameBuffer(initialCapacity = 5, onEvict = { evicted.add(it.sequenceId) })
        (1..5).forEach { buffer.push(makeFrame(it)) }

        buffer.setCapacity(5)

        assertTrue(evicted.isEmpty())
        assertEquals(5, buffer.size)
    }

    @Test
    fun `clear evicts everything in chronological order`() {
        val evicted = mutableListOf<Int>()
        val buffer = RollingFrameBuffer(initialCapacity = 5, onEvict = { evicted.add(it.sequenceId) })
        (1..4).forEach { buffer.push(makeFrame(it)) }

        buffer.clear()

        assertEquals(listOf(1, 2, 3, 4), evicted)
        assertEquals(0, buffer.size)
    }

    @Test
    fun `initialCapacity out of range throws`() {
        assertThrows(IllegalArgumentException::class.java) { RollingFrameBuffer(initialCapacity = 0) }
        assertThrows(IllegalArgumentException::class.java) { RollingFrameBuffer(initialCapacity = 21) }
    }

    @Test
    fun `setCapacity out of range throws`() {
        val buffer = RollingFrameBuffer(initialCapacity = 5)
        assertThrows(IllegalArgumentException::class.java) { buffer.setCapacity(0) }
        assertThrows(IllegalArgumentException::class.java) { buffer.setCapacity(21) }
    }

    private fun makeFrame(seqId: Int): BufferedFrame = BufferedFrame(
        sequenceId = seqId,
        timestampNs = seqId.toLong(),
        crop = null,
        score = FrameScore.Failed,
        bbox = BboxF(0f, 0f, 0f, 0f),
        detectionConfidence = 0f,
        detectionSource = DetectionSource.YOLO,
        arcfaceTop3 = emptyList(),
    )
}
