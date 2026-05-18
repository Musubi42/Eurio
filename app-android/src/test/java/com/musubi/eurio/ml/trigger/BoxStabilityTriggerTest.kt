package com.musubi.eurio.ml.trigger

import com.musubi.eurio.ml.DetectionSource
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BoxStabilityTriggerTest {

    @Test
    fun `fires on third stable frame at default thresholds`() {
        val trigger = BoxStabilityTrigger(iouMin = 0.7f, nFramesRequired = 3)
        val bbox = BboxF(100f, 100f, 200f, 200f)

        assertNull(trigger.observe(ctx(bbox, source = DetectionSource.YOLO))) // consecutive=1
        assertNull(trigger.observe(ctx(bbox, source = DetectionSource.YOLO))) // consecutive=2
        val event = trigger.observe(ctx(bbox, source = DetectionSource.YOLO)) // consecutive=3 → fire
        assertTrue(event is TriggerEvent.Fire)
    }

    @Test
    fun `does not re-fire after a fire until reset`() {
        val trigger = BoxStabilityTrigger(iouMin = 0.7f, nFramesRequired = 2)
        val bbox = BboxF(0f, 0f, 100f, 100f)

        assertNull(trigger.observe(ctx(bbox))) // 1
        assertTrue(trigger.observe(ctx(bbox)) is TriggerEvent.Fire) // 2 → fire
        // Further observations stay null even with stable bbox.
        repeat(5) { assertNull(trigger.observe(ctx(bbox))) }

        trigger.reset()
        // After reset, runs from scratch — needs 2 frames again.
        assertNull(trigger.observe(ctx(bbox)))
        assertTrue(trigger.observe(ctx(bbox)) is TriggerEvent.Fire)
    }

    @Test
    fun `low IoU resets consecutive counter back to 1`() {
        val trigger = BoxStabilityTrigger(iouMin = 0.7f, nFramesRequired = 3)
        // Frame 1: (0,0)-(100,100). Frame 2: same. Frame 3: shifted far → IoU < 0.7.
        // Frame 4: same as frame 3. Frame 5: same → only on frame 5 do we have 3 consecutive.
        val a = BboxF(0f, 0f, 100f, 100f)
        val b = BboxF(80f, 80f, 180f, 180f)

        assertNull(trigger.observe(ctx(a))) // c=1
        assertNull(trigger.observe(ctx(a))) // c=2
        assertNull(trigger.observe(ctx(b))) // IoU low → c=1
        assertNull(trigger.observe(ctx(b))) // c=2
        assertTrue(trigger.observe(ctx(b)) is TriggerEvent.Fire) // c=3 → fire
    }

    @Test
    fun `null bbox resets counter and lastBbox`() {
        val trigger = BoxStabilityTrigger(iouMin = 0.7f, nFramesRequired = 3)
        val bbox = BboxF(0f, 0f, 100f, 100f)

        assertNull(trigger.observe(ctx(bbox))) // c=1
        assertNull(trigger.observe(ctx(bbox))) // c=2
        assertNull(trigger.observe(ctx(null))) // reset → c=0
        assertNull(trigger.observe(ctx(bbox))) // c=1 again
        assertNull(trigger.observe(ctx(bbox))) // c=2
        assertTrue(trigger.observe(ctx(bbox)) is TriggerEvent.Fire) // c=3 → fire
    }

    @Test
    fun `fire reason carries frame count and threshold`() {
        val trigger = BoxStabilityTrigger(iouMin = 0.7f, nFramesRequired = 2)
        val bbox = BboxF(0f, 0f, 100f, 100f)

        trigger.observe(ctx(bbox))
        val event = trigger.observe(ctx(bbox)) as TriggerEvent.Fire
        assertEquals("stable 2f IoU≥0.70", event.reason)
    }

    @Test
    fun `name is stable identifier`() {
        assertEquals("box_stability", BoxStabilityTrigger(0.7f, 3).name)
    }

    @Test
    fun `buffer snapshot is forwarded as-is in the Fire event`() {
        val trigger = BoxStabilityTrigger(iouMin = 0.7f, nFramesRequired = 1)
        val snap = listOf<BufferedFrame>()
        val ctx = FrameContext(
            sequenceId = 0,
            buffer = snap,
            primaryBbox = BboxF(0f, 0f, 10f, 10f),
            primaryConfidence = 0.9f,
            primarySource = DetectionSource.YOLO,
            arcfaceTop1 = null,
            consensusLockedClass = null,
        )
        val event = trigger.observe(ctx)
        assertNotNull(event)
        assertTrue((event as TriggerEvent.Fire).bufferSnapshot === snap)
    }
}
