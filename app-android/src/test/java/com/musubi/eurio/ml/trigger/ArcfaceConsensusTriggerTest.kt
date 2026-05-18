package com.musubi.eurio.ml.trigger

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ArcfaceConsensusTriggerTest {

    @Test
    fun `does not fire when consensus is null`() {
        val trigger = ArcfaceConsensusTrigger()
        repeat(5) { assertNull(trigger.observe(ctx(consensus = null))) }
    }

    @Test
    fun `fires once when consensus first locks`() {
        val trigger = ArcfaceConsensusTrigger()
        val event = trigger.observe(ctx(consensus = "2_EUR_FRA_2002"))
        assertTrue(event is TriggerEvent.Fire)
        assertEquals("consensus 2_EUR_FRA_2002", (event as TriggerEvent.Fire).reason)
    }

    @Test
    fun `does not re-fire while locked on the same class`() {
        val trigger = ArcfaceConsensusTrigger()
        assertTrue(trigger.observe(ctx(consensus = "2_EUR_FRA_2002")) is TriggerEvent.Fire)
        repeat(5) {
            assertNull(trigger.observe(ctx(consensus = "2_EUR_FRA_2002")))
        }
    }

    @Test
    fun `fires again when consensus class changes`() {
        val trigger = ArcfaceConsensusTrigger()
        assertTrue(trigger.observe(ctx(consensus = "2_EUR_FRA_2002")) is TriggerEvent.Fire)
        assertNull(trigger.observe(ctx(consensus = "2_EUR_FRA_2002")))
        assertTrue(trigger.observe(ctx(consensus = "2_EUR_DEU_2007")) is TriggerEvent.Fire)
    }

    @Test
    fun `reset clears the fired marker`() {
        val trigger = ArcfaceConsensusTrigger()
        trigger.observe(ctx(consensus = "X"))
        trigger.reset()
        assertTrue(trigger.observe(ctx(consensus = "X")) is TriggerEvent.Fire)
    }

    @Test
    fun `name is stable identifier`() {
        assertEquals("arcface_consensus", ArcfaceConsensusTrigger().name)
    }
}
