package com.musubi.eurio.ml.image

import androidx.exifinterface.media.ExifInterface
import java.io.File

/**
 * Guard for raw JPEG paths that did **not** go through [JpegPipeline].
 *
 * The pipeline's `Bitmap.compress(JPEG)` step already drops EXIF — so
 * for any frame produced by `ImageCapture` → `JpegPipeline.process(...)`
 * this stripper is redundant. It exists for future flows that ingest
 * JPEG bytes from external sources (manual import, restore-from-backup,
 * etc.) where we cannot trust the source.
 *
 * Strategy: write the bytes to a tmp file, open with ExifInterface,
 * null out the sensitive tags, save, read back. ExifInterface does not
 * expose a byte-array API in the AndroidX edition, so the tmp dance is
 * unavoidable.
 *
 * The set of tags below is the union of:
 *  - GPS family (location).
 *  - Datetime family (privacy: leaks when the photo was taken).
 *  - Device/sensor identifiers (Make, Model, Software, SerialNumber).
 *  - Free-form text fields a third-party could have used as a sidecar
 *    (UserComment, Artist, ImageDescription).
 */
object ExifStripper {

    /**
     * Strip sensitive EXIF tags from [jpegBytes]. Returns a fresh byte
     * array — original input is not mutated. Tmp file is created in
     * [tmpDir] (caller supplies; typically `Context.cacheDir`) and
     * deleted before return.
     */
    fun strip(jpegBytes: ByteArray, tmpDir: File): ByteArray {
        tmpDir.mkdirs()
        val tmp = File.createTempFile("exif-strip-", ".jpg", tmpDir)
        try {
            tmp.writeBytes(jpegBytes)
            val exif = ExifInterface(tmp.absolutePath)
            SENSITIVE_TAGS.forEach { tag -> exif.setAttribute(tag, null) }
            exif.saveAttributes()
            return tmp.readBytes()
        } finally {
            tmp.delete()
        }
    }

    private val SENSITIVE_TAGS = listOf(
        // GPS
        ExifInterface.TAG_GPS_LATITUDE,
        ExifInterface.TAG_GPS_LATITUDE_REF,
        ExifInterface.TAG_GPS_LONGITUDE,
        ExifInterface.TAG_GPS_LONGITUDE_REF,
        ExifInterface.TAG_GPS_ALTITUDE,
        ExifInterface.TAG_GPS_ALTITUDE_REF,
        ExifInterface.TAG_GPS_TIMESTAMP,
        ExifInterface.TAG_GPS_DATESTAMP,
        ExifInterface.TAG_GPS_PROCESSING_METHOD,
        ExifInterface.TAG_GPS_AREA_INFORMATION,
        // Datetime
        ExifInterface.TAG_DATETIME,
        ExifInterface.TAG_DATETIME_ORIGINAL,
        ExifInterface.TAG_DATETIME_DIGITIZED,
        ExifInterface.TAG_OFFSET_TIME,
        ExifInterface.TAG_OFFSET_TIME_ORIGINAL,
        ExifInterface.TAG_OFFSET_TIME_DIGITIZED,
        // Device fingerprint
        ExifInterface.TAG_MAKE,
        ExifInterface.TAG_MODEL,
        ExifInterface.TAG_SOFTWARE,
        ExifInterface.TAG_BODY_SERIAL_NUMBER,
        ExifInterface.TAG_LENS_MAKE,
        ExifInterface.TAG_LENS_MODEL,
        ExifInterface.TAG_LENS_SERIAL_NUMBER,
        // Free-form
        ExifInterface.TAG_USER_COMMENT,
        ExifInterface.TAG_ARTIST,
        ExifInterface.TAG_IMAGE_DESCRIPTION,
        ExifInterface.TAG_COPYRIGHT,
        // Range info that hints at sensor / focus distance
        ExifInterface.TAG_SUBJECT_DISTANCE,
        ExifInterface.TAG_SUBJECT_DISTANCE_RANGE,
    )
}
