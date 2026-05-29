package com.musubi.eurio.features.dev.capture

import android.util.Log
import com.musubi.eurio.features.scan.CaptureProtocol
import com.musubi.eurio.ml.CapturePaths
import org.json.JSONObject
import java.io.File

/**
 * Android-side adapter that turns the on-device `eval_real/` directory into a
 * [CaptureProgressScanner.Scan]. It is the single disk reader shared by the
 * resume logic ([CaptureViewModel.enter]) and the `/dev/status` screen, so both
 * agree on what is captured / skipped (cf. docs/operations/debug-data-taxonomy.md).
 *
 * Sources of truth :
 *  - **captured** = presence of the crop file on disk (authoritative even if the
 *    manifest disagrees).
 *  - **skipped** = a `{"event":"skip", ...}` line in `manifest.jsonl` for a
 *    `(eurio_id, step_id)` that has no crop.
 */
object CaptureDiskReader {

    private const val TAG = "CaptureDiskReader"

    /**
     * @param debugRootDir the app debug root (`…/eurio_debug`), or null when the
     *   analyzer has not been initialised — yields an empty scan.
     */
    fun read(debugRootDir: File?): CaptureProgressScanner.Scan {
        val coins = CaptureProtocol.coins
        val steps = CaptureProtocol.steps
        val photosPerStep = CaptureProtocol.photosPerStep

        val evalRealDir = debugRootDir?.let { File(it, CapturePaths.EVAL_REAL_DIR) }
        val skipped = readSkippedSteps(evalRealDir)

        return CaptureProgressScanner.scan(
            coinCount = coins.size,
            stepCount = steps.size,
            photosPerStep = photosPerStep,
            cropExists = { c, s, p ->
                val eurioId = coins.getOrNull(c)?.eurioId
                val stepId = steps.getOrNull(s)?.id
                if (eurioId != null && stepId != null && evalRealDir != null) {
                    File(File(evalRealDir, eurioId), CapturePaths.cropFileName(stepId, p)).isFile
                } else {
                    false
                }
            },
            isSkipped = { c, s ->
                val eurioId = coins.getOrNull(c)?.eurioId
                val stepId = steps.getOrNull(s)?.id
                eurioId != null && stepId != null && SkippedKey(eurioId, stepId) in skipped
            },
        )
    }

    private data class SkippedKey(val eurioId: String, val stepId: String)

    private fun readSkippedSteps(evalRealDir: File?): Set<SkippedKey> {
        val manifest = evalRealDir?.let { File(it, CapturePaths.MANIFEST_FILE) } ?: return emptySet()
        if (!manifest.isFile) return emptySet()
        val out = HashSet<SkippedKey>()
        try {
            manifest.forEachLine { raw ->
                val line = raw.trim()
                if (line.isEmpty() || !line.contains("\"event\"")) return@forEachLine
                try {
                    val obj = JSONObject(line)
                    if (obj.optString("event") != "skip") return@forEachLine
                    val eurioId = obj.optString("eurio_id")
                    val stepId = obj.optString("step_id")
                    if (eurioId.isNotEmpty() && stepId.isNotEmpty()) {
                        out.add(SkippedKey(eurioId, stepId))
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "skipping malformed manifest line", e)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "failed to read manifest", e)
        }
        return out
    }
}
