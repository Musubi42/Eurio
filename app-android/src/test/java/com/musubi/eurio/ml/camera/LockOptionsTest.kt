package com.musubi.eurio.ml.camera

import com.musubi.eurio.features.scan.debug.DebugScanConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LockOptionsTest {

    private val region = MeteringRect(0.3f, 0.4f, 0.7f, 0.8f)

    @Test
    fun fromDebugConfig_mapsAllThreeToggles() {
        val cfg = DebugScanConfig(
            aeLockEnabled = true,
            afLockEnabled = false,
            awbLockEnabled = true,
        )
        val opts = LockOptions.fromDebugConfig(cfg, region)
        assertTrue(opts.aeLock)
        assertFalse(opts.afLock)
        assertTrue(opts.awbLock)
        assertEquals(region, opts.region)
    }

    @Test
    fun fromDebugConfig_keepsBenchDefaults() {
        val opts = LockOptions.fromDebugConfig(DebugScanConfig(), region)
        assertEquals(800L, opts.afTimeoutMs)
        assertEquals(0.12f, opts.regionExpansion, 1e-6f)
    }

    @Test
    fun meteringRect_centerIsBboxCenter() {
        val r = MeteringRect(0.2f, 0.4f, 0.6f, 0.8f)
        assertEquals(0.4f, r.centerX, 1e-6f)
        assertEquals(0.6f, r.centerY, 1e-6f)
    }
}
