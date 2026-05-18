package com.musubi.eurio.ml.image

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.max

/**
 * Instrumented tests for [JpegPipeline]. Requires Android runtime
 * because Bitmap/BitmapFactory are not on the JVM classpath.
 */
@RunWith(AndroidJUnit4::class)
class JpegPipelineTest {

    @Test
    fun fromBitmap_downscalesLongSide() {
        val src = Bitmap.createBitmap(3000, 2000, Bitmap.Config.ARGB_8888)
        val jpeg = JpegPipeline.fromBitmap(src, rotationDegrees = 0, longSideMax = 2048)

        val decoded = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
        assertEquals("long side capped at 2048", 2048, max(decoded.width, decoded.height))
        // Aspect ratio preserved (within 1px rounding).
        val expectedShort = (2000.0 * 2048 / 3000.0).toInt()
        assertTrue(
            "short side ≈ $expectedShort, got ${kotlin.math.min(decoded.width, decoded.height)}",
            kotlin.math.abs(kotlin.math.min(decoded.width, decoded.height) - expectedShort) <= 1,
        )
    }

    @Test
    fun fromBitmap_smallerThanLimit_isUntouched() {
        val src = Bitmap.createBitmap(800, 600, Bitmap.Config.ARGB_8888)
        val jpeg = JpegPipeline.fromBitmap(src, rotationDegrees = 0, longSideMax = 2048)

        val decoded = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
        assertEquals(800, decoded.width)
        assertEquals(600, decoded.height)
    }

    @Test
    fun fromBitmap_appliesRotation_swapsWidthAndHeight() {
        val src = Bitmap.createBitmap(1000, 500, Bitmap.Config.ARGB_8888)
        val jpeg = JpegPipeline.fromBitmap(src, rotationDegrees = 90, longSideMax = 4096)

        val decoded = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
        assertEquals(500, decoded.width)
        assertEquals(1000, decoded.height)
    }

    @Test
    fun fromBitmap_rotation0_isIdentitySize() {
        val src = Bitmap.createBitmap(640, 480, Bitmap.Config.ARGB_8888)
        val jpeg = JpegPipeline.fromBitmap(src, rotationDegrees = 0, longSideMax = 4096)

        val decoded = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
        assertEquals(640, decoded.width)
        assertEquals(480, decoded.height)
    }

    @Test(expected = IllegalArgumentException::class)
    fun fromBitmap_rejectsZeroLongSide() {
        val src = Bitmap.createBitmap(10, 10, Bitmap.Config.ARGB_8888)
        JpegPipeline.fromBitmap(src, longSideMax = 0)
    }

    @Test(expected = IllegalArgumentException::class)
    fun fromBitmap_rejectsInvalidQuality() {
        val src = Bitmap.createBitmap(10, 10, Bitmap.Config.ARGB_8888)
        JpegPipeline.fromBitmap(src, quality = 101)
    }
}
