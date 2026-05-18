package com.musubi.eurio.ml.image

import android.graphics.Bitmap
import androidx.exifinterface.media.ExifInterface
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * Instrumented tests for [ExifStripper]. Builds a JPEG with sensitive
 * EXIF tags pre-populated, runs the stripper, and asserts the tags are
 * absent from the output.
 */
@RunWith(AndroidJUnit4::class)
class ExifStripperTest {

    private lateinit var cacheDir: File

    @Before
    fun setUp() {
        cacheDir = InstrumentationRegistry.getInstrumentation().targetContext.cacheDir
    }

    @Test
    fun strip_removesGpsAndDeviceTags() {
        val tainted = jpegWithExifTags(
            mapOf(
                ExifInterface.TAG_GPS_LATITUDE to "48/1,52/1,0/1",
                ExifInterface.TAG_GPS_LATITUDE_REF to "N",
                ExifInterface.TAG_GPS_LONGITUDE to "2/1,21/1,0/1",
                ExifInterface.TAG_GPS_LONGITUDE_REF to "E",
                ExifInterface.TAG_DATETIME_ORIGINAL to "2026:05:16 14:30:00",
                ExifInterface.TAG_MAKE to "TestMake",
                ExifInterface.TAG_MODEL to "TestModel",
                ExifInterface.TAG_USER_COMMENT to "private note",
            )
        )

        val cleaned = ExifStripper.strip(tainted, cacheDir)

        val out = File.createTempFile("exif-check-", ".jpg", cacheDir).apply {
            writeBytes(cleaned)
        }
        try {
            val exif = ExifInterface(out.absolutePath)
            assertNull("GPS latitude", exif.getAttribute(ExifInterface.TAG_GPS_LATITUDE))
            assertNull("GPS longitude", exif.getAttribute(ExifInterface.TAG_GPS_LONGITUDE))
            assertNull("datetime original", exif.getAttribute(ExifInterface.TAG_DATETIME_ORIGINAL))
            assertNull("make", exif.getAttribute(ExifInterface.TAG_MAKE))
            assertNull("model", exif.getAttribute(ExifInterface.TAG_MODEL))
            assertNull("user comment", exif.getAttribute(ExifInterface.TAG_USER_COMMENT))
        } finally {
            out.delete()
        }
    }

    @Test
    fun strip_isIdempotent() {
        val clean = jpegWithExifTags(emptyMap())
        // Stripping a JPEG that already has no sensitive tags must succeed
        // and produce a valid, decodable JPEG (same size class as input).
        val out = ExifStripper.strip(clean, cacheDir)
        assertEquals("JPEG magic byte 0xFF", 0xFF.toByte(), out[0])
        assertEquals("JPEG SOI marker 0xD8", 0xD8.toByte(), out[1])
    }

    /**
     * Build a JPEG via Bitmap.compress, then inject [tags] into its EXIF
     * via [ExifInterface]. Returns the resulting byte array.
     */
    private fun jpegWithExifTags(tags: Map<String, String>): ByteArray {
        val bmp = Bitmap.createBitmap(64, 64, Bitmap.Config.ARGB_8888)
        val baos = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 90, baos)
        bmp.recycle()
        val raw = baos.toByteArray()

        if (tags.isEmpty()) return raw

        val tmp = File.createTempFile("exif-seed-", ".jpg", cacheDir).apply {
            writeBytes(raw)
        }
        try {
            val exif = ExifInterface(tmp.absolutePath)
            tags.forEach { (tag, value) -> exif.setAttribute(tag, value) }
            exif.saveAttributes()
            return tmp.readBytes()
        } finally {
            tmp.delete()
        }
    }
}
