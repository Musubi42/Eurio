package com.musubi.eurio.domain.scan.quality

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM-pure tests covering the deterministic parts of the frame scorer:
 * completeness geometry, motion delta, exposure score from precomputed
 * mean/clipping, and the weighted aggregation. The Laplacian variance
 * branch is OpenCV-bound and not covered here; chunk-7 bench tooling will
 * validate it end-to-end on real frames.
 */
class QualityMathTest {

    private val eps = 1e-4f

    // ── Completeness ─────────────────────────────────────────────────────

    @Test
    fun `completeness is 1 when disc has 10 percent margin on every edge`() {
        // Frame 200×200, disc r=50 centered at (100,100): margin = 50/50 = 1.0 → score capped at 1.0.
        val score = QualityMath.completeness(cx = 100, cy = 100, r = 50, frameW = 200, frameH = 200)
        assertEquals(1f, score, eps)
    }

    @Test
    fun `completeness is around 0_5 when disc touches a frame edge`() {
        // Disc r=80 centered at (80,100) in a 200×200 frame: left margin = 0 → score ≈ 0.5.
        val score = QualityMath.completeness(cx = 80, cy = 100, r = 80, frameW = 200, frameH = 200)
        assertEquals(0.5f, score, eps)
    }

    @Test
    fun `completeness is 0 when disc is cropped past 5 percent of radius`() {
        // Disc r=100 centered at (90,100): left margin = -0.1 → clamped to 0.
        val score = QualityMath.completeness(cx = 90, cy = 100, r = 100, frameW = 300, frameH = 300)
        assertEquals(0f, score, eps)
    }

    @Test
    fun `completeness returns 0 for degenerate radius`() {
        val score = QualityMath.completeness(cx = 100, cy = 100, r = 0, frameW = 200, frameH = 200)
        assertEquals(0f, score, eps)
    }

    // ── Motion ───────────────────────────────────────────────────────────

    @Test
    fun `motion is 1 when previous center is null`() {
        val score = QualityMath.motion(
            previousCenter = null, currentCx = 100, currentCy = 100, radius = 50, motionMax = 0.05f,
        )
        assertEquals(1f, score, eps)
        assertTrue(QualityMath.motionPasses(null, 100, 100, 50, 0.05f))
    }

    @Test
    fun `motion delta of 0_04 vs cap 0_05 yields score around 0_2`() {
        // delta = 2/50 = 0.04, motion_score = 1 - 0.04/0.05 = 0.2.
        val score = QualityMath.motion(
            previousCenter = 100f to 100f, currentCx = 102, currentCy = 100, radius = 50, motionMax = 0.05f,
        )
        assertEquals(0.2f, score, eps)
        assertTrue(
            QualityMath.motionPasses(100f to 100f, 102, 100, 50, 0.05f),
        )
    }

    @Test
    fun `motion delta beyond motionMax clamps to 0 and fails the gate`() {
        // delta = 10/50 = 0.2 > 0.05 cap.
        val score = QualityMath.motion(
            previousCenter = 100f to 100f, currentCx = 110, currentCy = 100, radius = 50, motionMax = 0.05f,
        )
        assertEquals(0f, score, eps)
        assertFalse(
            QualityMath.motionPasses(100f to 100f, 110, 100, 50, 0.05f),
        )
    }

    // ── Exposure ─────────────────────────────────────────────────────────

    @Test
    fun `exposure peaks when mean is 0_5 and clipping is 0`() {
        val score = QualityMath.exposureScore(
            meanLuminance = 0.5f, clippingRatio = 0f, bandHalfWidth = 0.2f, clippingMax = 0.01f,
        )
        assertEquals(1f, score, eps)
        assertTrue(QualityMath.exposurePasses(0.5f, 0f, 0.2f, 0.01f))
    }

    @Test
    fun `exposure at band edge yields half of the band subscore`() {
        // mean = 0.7, band half-width = 0.2 → bandDistance = 1 → bandSubScore = 0.
        // clipping = 0 → clippingSubScore = 1. Average = 0.5.
        val score = QualityMath.exposureScore(
            meanLuminance = 0.7f, clippingRatio = 0f, bandHalfWidth = 0.2f, clippingMax = 0.01f,
        )
        assertEquals(0.5f, score, eps)
        // Pass requires both band AND clipping under their caps; band ≤ 1 is OK (boundary).
        assertTrue(QualityMath.exposurePasses(0.7f, 0f, 0.2f, 0.01f))
    }

    @Test
    fun `exposure fails when clipping exceeds clippingMax`() {
        val score = QualityMath.exposureScore(
            meanLuminance = 0.5f, clippingRatio = 0.05f, bandHalfWidth = 0.2f, clippingMax = 0.01f,
        )
        // band perfect (1), clipping ratio 0.05 vs cap 0.01 → clippingSubScore clamped to 0. Avg = 0.5.
        assertEquals(0.5f, score, eps)
        assertFalse(QualityMath.exposurePasses(0.5f, 0.05f, 0.2f, 0.01f))
    }

    @Test
    fun `exposure fails when mean is far outside the band`() {
        // mean = 0.95 → bandDistance = 0.45/0.2 = 2.25 → bandSubScore = 0.
        val score = QualityMath.exposureScore(
            meanLuminance = 0.95f, clippingRatio = 0f, bandHalfWidth = 0.2f, clippingMax = 0.01f,
        )
        assertEquals(0.5f, score, eps) // (0 + 1) / 2
        assertFalse(QualityMath.exposurePasses(0.95f, 0f, 0.2f, 0.01f))
    }

    // ── Sharpness normalization ──────────────────────────────────────────

    @Test
    fun `sharpness normalization clamps and scales linearly`() {
        assertEquals(0f, QualityMath.normalizeSharpness(0f, 400f), eps)
        assertEquals(0.5f, QualityMath.normalizeSharpness(200f, 400f), eps)
        assertEquals(1f, QualityMath.normalizeSharpness(400f, 400f), eps)
        assertEquals(1f, QualityMath.normalizeSharpness(800f, 400f), eps) // clamped
    }

    // ── Aggregate ────────────────────────────────────────────────────────

    @Test
    fun `aggregate excludes motion when motionEnabled is false`() {
        val policy = ScoringPolicy() // motionEnabled = false by default
        val agg = QualityMath.aggregate(
            sharpness = 1f, exposure = 0f, completeness = 0f, motion = 0.5f, policy = policy,
        )
        // weights without motion: 0.5/0.2/0.2 → sum 0.9. Score = (1*0.5)/0.9 ≈ 0.5556.
        assertEquals(0.5555f, agg, 1e-3f)
    }

    @Test
    fun `aggregate includes motion when motionEnabled is true`() {
        val policy = ScoringPolicy(motionEnabled = true)
        val agg = QualityMath.aggregate(
            sharpness = 1f, exposure = 1f, completeness = 1f, motion = 1f, policy = policy,
        )
        assertEquals(1f, agg, eps)
    }

    @Test
    fun `aggregate falls back to 0 when all weights are zero`() {
        val policy = ScoringPolicy(wSharpness = 0f, wExposure = 0f, wCompleteness = 0f, wMotion = 0f)
        val agg = QualityMath.aggregate(1f, 1f, 1f, null, policy)
        assertEquals(0f, agg, eps)
    }
}
