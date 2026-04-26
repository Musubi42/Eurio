package com.musubi.eurio.features.scan.components

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import kotlin.math.sqrt

private const val CACHE_SUBDIR = "coin-3d-normals"

/**
 * Sobel-derived tangent-space normal map for a coin face photo. Direct port of
 * `buildNormalMapFromImage` from the Three.js proto
 * (docs/design/prototype/scenes/scan-coin-3d.js:460). Strength is baked at 1.0 —
 * runtime intensity is controlled by the material's `normalScale` uniform.
 *
 * Two-tier caching :
 *  - In-memory (callers can hold the returned [Bitmap]).
 *  - On-disk (PNG in [Context.getCacheDir]/coin-3d-normals/<key>.png), survives
 *    process death. Cache key is a stable string supplied by the caller (we use
 *    "<eurioId>-<face>"). First run for a coin pays the Sobel cost (~150-300ms
 *    for a 400 px photo), subsequent loads <50ms.
 */
object NormalMapBuilder {

    /** Returns a normal map bitmap from disk cache if present, else builds + caches. */
    suspend fun loadOrBuild(context: Context, cacheKey: String, source: Bitmap): Bitmap {
        val cacheFile = cacheFileFor(context, cacheKey)
        return readCache(cacheFile) ?: buildAndCache(source, cacheFile)
    }

    /** Bypasses the cache. Useful for tests or when the source bitmap changed identity. */
    suspend fun build(source: Bitmap): Bitmap = withContext(Dispatchers.Default) {
        sobelNormalMap(source)
    }

    private fun cacheFileFor(context: Context, cacheKey: String): File =
        File(File(context.cacheDir, CACHE_SUBDIR).apply { mkdirs() }, "$cacheKey.png")

    private suspend fun readCache(file: File): Bitmap? = withContext(Dispatchers.IO) {
        if (!file.isFile) null
        else runCatching { BitmapFactory.decodeFile(file.absolutePath) }.getOrNull()
    }

    private suspend fun buildAndCache(source: Bitmap, file: File): Bitmap {
        val bitmap = withContext(Dispatchers.Default) { sobelNormalMap(source) }
        withContext(Dispatchers.IO) {
            runCatching {
                FileOutputStream(file).use { stream ->
                    // PNG is lossless — important for normal maps where any colour
                    // shift becomes a visible lighting artefact.
                    bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream)
                }
            }
        }
        return bitmap
    }
}

/**
 * Sobel-derived tangent-space normal map. RGB encodes (nx, ny, nz) ∈ [-1,1]
 * remapped to [0,1]. Read pixels into a packed int buffer once (faster than
 * `getPixel` per call), compute luminance, then apply the 3×3 Sobel kernel.
 */
private fun sobelNormalMap(src: Bitmap): Bitmap {
    val w = src.width
    val h = src.height
    val pixels = IntArray(w * h)
    src.getPixels(pixels, 0, w, 0, 0, w, h)

    val lum = FloatArray(w * h)
    for (i in pixels.indices) {
        val p = pixels[i]
        val r = (p ushr 16) and 0xFF
        val g = (p ushr 8) and 0xFF
        val b = p and 0xFF
        lum[i] = (0.299f * r + 0.587f * g + 0.114f * b) / 255f
    }

    val out = IntArray(w * h)
    for (y in 0 until h) {
        val y0 = if (y == 0) 0 else y - 1
        val y1 = if (y == h - 1) h - 1 else y + 1
        val rowTop = y0 * w
        val rowMid = y * w
        val rowBot = y1 * w
        for (x in 0 until w) {
            val x0 = if (x == 0) 0 else x - 1
            val x1 = if (x == w - 1) w - 1 else x + 1
            val tl = lum[rowTop + x0]; val tc = lum[rowTop + x]; val tr = lum[rowTop + x1]
            val ml = lum[rowMid + x0];                            val mr = lum[rowMid + x1]
            val bl = lum[rowBot + x0]; val bc = lum[rowBot + x]; val br = lum[rowBot + x1]
            val gx = (tr + 2f * mr + br) - (tl + 2f * ml + bl)
            val gy = (bl + 2f * bc + br) - (tl + 2f * tc + tr)
            // Tangent-space normal : (-gx, -gy, 1) normalized.
            var nx = -gx
            var ny = -gy
            val nz = 1f
            val len = sqrt(nx * nx + ny * ny + nz * nz)
            nx /= len; ny /= len
            val nzN = nz / len
            val r = ((nx * 0.5f + 0.5f) * 255f).toInt().coerceIn(0, 255)
            val g = ((ny * 0.5f + 0.5f) * 255f).toInt().coerceIn(0, 255)
            val b = ((nzN * 0.5f + 0.5f) * 255f).toInt().coerceIn(0, 255)
            out[rowMid + x] = (0xFF shl 24) or (r shl 16) or (g shl 8) or b
        }
    }

    val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
    bitmap.setPixels(out, 0, w, 0, 0, w, h)
    return bitmap
}
