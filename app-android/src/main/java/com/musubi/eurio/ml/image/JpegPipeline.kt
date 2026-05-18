package com.musubi.eurio.ml.image

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Matrix
import androidx.camera.core.ImageProxy
import java.io.ByteArrayOutputStream
import kotlin.math.roundToInt

/**
 * JPEG post-processing applied to the full-res snapshot produced by
 * `ImageCapture.takePicture` (chunk-5c) before it's archived to disk.
 *
 * Pipeline:
 *   1. Decode the raw JPEG bytes to a Bitmap (BitmapFactory).
 *   2. Apply the EXIF rotation from `ImageInfo.rotationDegrees` so the
 *      saved file is physically oriented — no reader needs to read the
 *      EXIF orientation tag.
 *   3. Downscale so the long side ≤ [DEFAULT_LONG_SIDE] (D15).
 *   4. Re-encode JPEG at quality [DEFAULT_QUALITY].
 *
 * Side benefit: `Bitmap.compress(JPEG)` does not propagate EXIF from the
 * source, so the archived file is already GPS-clean. The dedicated
 * [ExifStripper] is only needed when archiving a raw JPEG that did not
 * go through this pipeline (e.g. future imports).
 *
 * All intermediate Bitmaps are recycled before returning to keep the
 * peak footprint at one frame (~16 MB for a 4080×3072 sensor on Pixel 9a).
 */
object JpegPipeline {

    const val DEFAULT_LONG_SIDE: Int = 2048
    const val DEFAULT_QUALITY: Int = 92

    /**
     * Process a JPEG [ImageProxy] from `ImageCapture.OnImageCapturedCallback`.
     * Caller owns closing the [ImageProxy] — we only read its planes.
     */
    fun process(
        imageProxy: ImageProxy,
        rotationDegrees: Int,
        longSideMax: Int = DEFAULT_LONG_SIDE,
        quality: Int = DEFAULT_QUALITY,
    ): ByteArray {
        require(imageProxy.format == ImageFormat.JPEG) {
            "expected ImageFormat.JPEG, got ${imageProxy.format}"
        }
        val plane = imageProxy.planes[0]
        val buf = plane.buffer
        val rawBytes = ByteArray(buf.remaining()).also { buf.get(it) }
        val bitmap = BitmapFactory.decodeByteArray(rawBytes, 0, rawBytes.size)
            ?: error("JPEG decode returned null (corrupt frame?)")
        return processBitmap(bitmap, rotationDegrees, longSideMax, quality, recycleSource = true)
    }

    /**
     * Process an in-memory Bitmap. Used by the YUV fallback path
     * (chunk-5c) when `ImageCapture` could not be bound alongside
     * `ImageAnalysis` on the device.
     *
     * The source bitmap is **not** recycled — caller decides its
     * lifetime, since the YUV fallback re-uses it from a SoftReference.
     */
    fun fromBitmap(
        bitmap: Bitmap,
        rotationDegrees: Int = 0,
        longSideMax: Int = DEFAULT_LONG_SIDE,
        quality: Int = DEFAULT_QUALITY,
    ): ByteArray = processBitmap(bitmap, rotationDegrees, longSideMax, quality, recycleSource = false)

    private fun processBitmap(
        source: Bitmap,
        rotationDegrees: Int,
        longSideMax: Int,
        quality: Int,
        recycleSource: Boolean,
    ): ByteArray {
        require(longSideMax > 0) { "longSideMax must be > 0" }
        require(quality in 1..100) { "quality must be in 1..100" }

        val rotated = if (rotationDegrees % 360 != 0) {
            val m = Matrix().apply { postRotate(rotationDegrees.toFloat()) }
            Bitmap.createBitmap(source, 0, 0, source.width, source.height, m, true).also {
                if (recycleSource && it !== source) source.recycle()
            }
        } else {
            source
        }

        val longSide = maxOf(rotated.width, rotated.height)
        val resized = if (longSide > longSideMax) {
            val scale = longSideMax.toFloat() / longSide
            val newW = (rotated.width * scale).roundToInt().coerceAtLeast(1)
            val newH = (rotated.height * scale).roundToInt().coerceAtLeast(1)
            Bitmap.createScaledBitmap(rotated, newW, newH, true).also {
                if (it !== rotated) rotated.recycle()
            }
        } else {
            rotated
        }

        val out = ByteArrayOutputStream(resized.byteCount / 8)
        resized.compress(Bitmap.CompressFormat.JPEG, quality, out)
        if (resized !== source || recycleSource) resized.recycle()
        return out.toByteArray()
    }
}
