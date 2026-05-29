package com.musubi.eurio.features.dev.capture

import com.musubi.eurio.features.dev.capture.CaptureProgressScanner.StepStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureProgressScannerTest {

    /** Convenience: no crops, no skips. */
    private val noCrops: (Int, Int, Int) -> Boolean = { _, _, _ -> false }
    private val noSkips: (Int, Int) -> Boolean = { _, _ -> false }

    @Test
    fun `empty disk resumes at the very first cell`() {
        val scan = CaptureProgressScanner.scan(
            coinCount = 2,
            stepCount = 3,
            photosPerStep = 1,
            cropExists = noCrops,
            isSkipped = noSkips,
        )
        assertEquals(0, scan.captured)
        assertEquals(6, scan.total)
        assertFalse(scan.isComplete)
        assertEquals(0, scan.resumeCoinIndex)
        assertEquals(0, scan.resumeStepIndex)
        assertEquals(0, scan.resumePhotoIndex)
    }

    @Test
    fun `resume lands on first missing crop within a partially captured coin`() {
        // coin 0 : steps 0 and 1 captured, step 2 missing.
        val present = setOf(Triple(0, 0, 0), Triple(0, 1, 0))
        val scan = CaptureProgressScanner.scan(
            coinCount = 2,
            stepCount = 3,
            photosPerStep = 1,
            cropExists = { c, s, p -> Triple(c, s, p) in present },
            isSkipped = noSkips,
        )
        assertEquals(2, scan.captured)
        assertEquals(0, scan.resumeCoinIndex)
        assertEquals(2, scan.resumeStepIndex)
        assertEquals(0, scan.resumePhotoIndex)
        assertFalse(scan.isComplete)
    }

    @Test
    fun `resume lands on next missing photo within an ablation step`() {
        // ABLATION : 4 photos/step. coin 0 step 0 has photos 0 and 1, missing 2.
        val present = setOf(Triple(0, 0, 0), Triple(0, 0, 1))
        val scan = CaptureProgressScanner.scan(
            coinCount = 1,
            stepCount = 1,
            photosPerStep = 4,
            cropExists = { c, s, p -> Triple(c, s, p) in present },
            isSkipped = noSkips,
        )
        assertEquals(2, scan.captured)
        assertEquals(0, scan.resumeCoinIndex)
        assertEquals(0, scan.resumeStepIndex)
        assertEquals(2, scan.resumePhotoIndex)
    }

    @Test
    fun `a skipped step is jumped over when computing the resume cursor`() {
        // coin 0 : step 0 skipped (no crop), step 1 pending → resume at step 1.
        val scan = CaptureProgressScanner.scan(
            coinCount = 1,
            stepCount = 2,
            photosPerStep = 1,
            cropExists = noCrops,
            isSkipped = { c, s -> c == 0 && s == 0 },
        )
        assertEquals(0, scan.captured)
        assertEquals(0, scan.resumeCoinIndex)
        assertEquals(1, scan.resumeStepIndex)
        assertEquals(StepStatus.SKIPPED, scan.coins[0].steps[0].status)
        assertEquals(StepStatus.PENDING, scan.coins[0].steps[1].status)
    }

    @Test
    fun `disk is authority - a crop in a skipped step is still counted and marked skipped`() {
        // Edge: photo 0 captured, then the step was skipped. captured counts the
        // crop (disk = authority) but the cell renders as SKIPPED and resume does
        // not return to it.
        val present = setOf(Triple(0, 0, 0))
        val scan = CaptureProgressScanner.scan(
            coinCount = 1,
            stepCount = 2,
            photosPerStep = 4,
            cropExists = { c, s, p -> Triple(c, s, p) in present },
            isSkipped = { c, s -> c == 0 && s == 0 },
        )
        assertEquals(1, scan.captured)
        // resume skips the skipped step entirely → step 1, photo 0.
        assertEquals(0, scan.resumeCoinIndex)
        assertEquals(1, scan.resumeStepIndex)
        assertEquals(0, scan.resumePhotoIndex)
        assertEquals(StepStatus.SKIPPED, scan.coins[0].steps[0].status)
    }

    @Test
    fun `everything captured marks the scan complete and points past the last coin`() {
        val scan = CaptureProgressScanner.scan(
            coinCount = 2,
            stepCount = 2,
            photosPerStep = 1,
            cropExists = { _, _, _ -> true },
            isSkipped = noSkips,
        )
        assertEquals(4, scan.captured)
        assertTrue(scan.isComplete)
        assertEquals(2, scan.resumeCoinIndex) // one past the last coin
        assertEquals(StepStatus.CAPTURED, scan.coins[1].steps[1].status)
    }

    @Test
    fun `every cell captured or skipped also completes the scan`() {
        // coin 0 fully captured, coin 1 fully skipped → complete.
        val scan = CaptureProgressScanner.scan(
            coinCount = 2,
            stepCount = 2,
            photosPerStep = 1,
            cropExists = { c, _, _ -> c == 0 },
            isSkipped = { c, _ -> c == 1 },
        )
        assertTrue(scan.isComplete)
        assertEquals(2, scan.captured)
    }

    @Test
    fun `partial step is reported as PARTIAL`() {
        val present = setOf(Triple(0, 0, 0), Triple(0, 0, 1))
        val scan = CaptureProgressScanner.scan(
            coinCount = 1,
            stepCount = 1,
            photosPerStep = 4,
            cropExists = { c, s, p -> Triple(c, s, p) in present },
            isSkipped = noSkips,
        )
        assertEquals(StepStatus.PARTIAL, scan.coins[0].steps[0].status)
    }

    @Test
    fun `empty protocol is complete with zero total`() {
        val scan = CaptureProgressScanner.scan(
            coinCount = 0,
            stepCount = 0,
            photosPerStep = 1,
            cropExists = noCrops,
            isSkipped = noSkips,
        )
        assertEquals(0, scan.total)
        assertEquals(0, scan.captured)
        assertTrue(scan.isComplete)
        assertEquals(0, scan.resumeCoinIndex)
    }
}
