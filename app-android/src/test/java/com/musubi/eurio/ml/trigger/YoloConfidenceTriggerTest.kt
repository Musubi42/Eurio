package com.musubi.eurio.ml.trigger

import com.musubi.eurio.ml.DetectionSource
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class YoloConfidenceTriggerTest {

    @Test
    fun `fires on third frame above threshold`() {
        val trigger = YoloConfidenceTrigger(confMin = 0.5f, nFramesRequired = 3)
        repeat(2) {
            assertNull(
                trigger.observe(
                    ctx(bbox = BboxF(0f, 0f, 10f, 10f), confidence = 0.6f, source = DetectionSource.YOLO),
                ),
            )
        }
        val event = trigger.observe(
            ctx(bbox = BboxF(0f, 0f, 10f, 10f), confidence = 0.6f, source = DetectionSource.YOLO),
        )
        assertTrue(event is TriggerEvent.Fire)
    }

    @Test
    fun `below threshold resets the counter`() {
        val trigger = YoloConfidenceTrigger(confMin = 0.5f, nFramesRequired = 3)
        trigger.observe(ctx(confidence = 0.6f, source = DetectionSource.YOLO)) // c=1
        trigger.observe(ctx(confidence = 0.6f, source = DetectionSource.YOLO)) // c=2
        trigger.observe(ctx(confidence = 0.3f, source = DetectionSource.YOLO)) // c=0
        assertNull(trigger.observe(ctx(confidence = 0.6f, source = DetectionSource.YOLO))) // c=1
        assertNull(trigger.observe(ctx(confidence = 0.6f, source = DetectionSource.YOLO))) // c=2
        assertTrue(
            trigger.observe(ctx(confidence = 0.6f, source = DetectionSource.YOLO)) is TriggerEvent.Fire,
        )
    }

    @Test
    fun `hough-source detections never accumulate`() {
        val trigger = YoloConfidenceTrigger(confMin = 0.5f, nFramesRequired = 2)
        // Even with high conf, HOUGH source skips counting.
        repeat(5) {
            assertNull(
                trigger.observe(ctx(confidence = 0.99f, source = DetectionSource.HOUGH)),
            )
        }
    }

    @Test
    fun `null confidence is treated as below threshold`() {
        val trigger = YoloConfidenceTrigger(confMin = 0.5f, nFramesRequired = 1)
        assertNull(trigger.observe(ctx(confidence = null, source = null)))
    }

    @Test
    fun `does not re-fire until reset`() {
        val trigger = YoloConfidenceTrigger(confMin = 0.5f, nFramesRequired = 1)
        val ev1 = trigger.observe(ctx(confidence = 0.9f, source = DetectionSource.YOLO))
        assertTrue(ev1 is TriggerEvent.Fire)
        repeat(3) {
            assertNull(trigger.observe(ctx(confidence = 0.9f, source = DetectionSource.YOLO)))
        }
        trigger.reset()
        assertTrue(
            trigger.observe(ctx(confidence = 0.9f, source = DetectionSource.YOLO)) is TriggerEvent.Fire,
        )
    }

    @Test
    fun `name and fire reason are correctly formatted`() {
        val trigger = YoloConfidenceTrigger(confMin = 0.50f, nFramesRequired = 2)
        trigger.observe(ctx(confidence = 0.7f, source = DetectionSource.YOLO))
        val event = trigger.observe(ctx(confidence = 0.7f, source = DetectionSource.YOLO)) as TriggerEvent.Fire
        assertEquals("yolo 2f conf≥0.50", event.reason)
        assertEquals("yolo_confidence", trigger.name)
    }
}
