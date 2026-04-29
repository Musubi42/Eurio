package com.musubi.eurio.features.scan

import android.content.Context
import android.os.Environment
import android.util.Log
import java.io.File

/**
 * Capture protocol — drives the debug "capture" walkthrough that produces
 * golden eval snaps (the data we copy into ml/datasets/eval_real for the
 * train↔inference gap measurement).
 *
 * The coin list is loaded at app startup. Two sources, in priority order:
 *  1. Runtime override — ``getExternalFilesDir(DIRECTORY_DOCUMENTS)/eurio_capture/cohort.csv``.
 *     Pushed by the admin web (cohort capture flow) via ``adb push``. App-scoped
 *     external storage: writable by adb, readable by the app, no permission needed.
 *  2. Bundled asset — ``app-android/src/main/assets/capture_coins.csv``.
 *     Default debug capture set, ships with the APK. Used when no runtime
 *     override is present (demo mode).
 *
 * The step list stays hardcoded: it's the protocol itself (lighting +
 * background + tilt conditions), not a per-coin payload.
 *
 * See docs/scan-normalization/phase-0-capture.md and
 * docs/admin/cohort-capture-flow/design.md.
 */
object CaptureProtocol {

    private const val TAG = "CaptureProtocol"
    private const val ASSET_PATH = "capture_coins.csv"
    private const val OVERRIDE_RELATIVE_PATH = "eurio_capture/cohort.csv"

    data class Step(val id: String, val label: String)

    data class Coin(val eurioId: String, val displayName: String)

    /**
     * Coin list — loaded from assets at app startup via [init]. Reading
     * before [init] returns an empty list; the capture button is only
     * visible after the bootstrap so the timing is safe in practice, but
     * we don't crash if the contract is violated.
     */
    @Volatile
    private var _coins: List<Coin> = emptyList()
    val coins: List<Coin> get() = _coins

    val steps: List<Step> = listOf(
        Step("bright_plain", "Intérieur lumineux, fond uni clair, centré"),
        Step("dim_plain", "Lumière tamisée / chaude, fond uni, centré"),
        Step("daylight_plain", "Plein jour ou proche fenêtre, fond uni"),
        Step("bright_textured", "Intérieur lumineux, fond texturé (tissu/bois)"),
        Step("tilt_plain", "Pièce inclinée ~10°, fond uni"),
        Step("close_plain", "Distance proche, pièce remplit le mask"),
    )

    val totalSnaps: Int get() = _coins.size * steps.size

    /**
     * Load the coin list from the bundled CSV. Called once from
     * [com.musubi.eurio.EurioApp.onCreate]. Idempotent — re-calling
     * just re-reads the file (useful for dev hot-reload, though we
     * don't currently rely on that).
     *
     * CSV format (semicolon-separated, header row): ``eurio_id;numista_id;display_name``.
     * Numista id is optional (kept for cross-reference with ml/ scripts);
     * empty lines and ``#``-prefixed comment lines are tolerated.
     */
    fun init(context: Context) {
        val override = runCatching { readRuntimeOverride(context) }
            .onFailure { Log.w(TAG, "Runtime override read failed", it) }
            .getOrNull()
        if (override != null && override.isNotEmpty()) {
            _coins = override
            Log.i(TAG, "Loaded ${_coins.size} coin(s) from runtime override $OVERRIDE_RELATIVE_PATH")
            return
        }
        _coins = runCatching { readAsset(context) }
            .onFailure { Log.e(TAG, "Failed to load $ASSET_PATH", it) }
            .getOrDefault(emptyList())
        Log.i(TAG, "Loaded ${_coins.size} coin(s) from asset $ASSET_PATH")
    }

    private fun readRuntimeOverride(context: Context): List<Coin>? {
        val docs = context.getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS) ?: return null
        val file = File(docs, OVERRIDE_RELATIVE_PATH)
        if (!file.isFile) return null
        return parseCsv(file.readLines(), source = file.absolutePath)
    }

    private fun readAsset(context: Context): List<Coin> {
        val lines = context.assets.open(ASSET_PATH).bufferedReader().use { it.readLines() }
        return parseCsv(lines, source = ASSET_PATH)
    }

    private fun parseCsv(lines: List<String>, source: String): List<Coin> {
        val out = mutableListOf<Coin>()
        var sawHeader = false
        for ((idx, raw) in lines.withIndex()) {
            val line = raw.trim()
            if (line.isEmpty() || line.startsWith("#")) continue
            val parts = line.split(';').map { it.trim() }
            if (parts.size < 3) {
                Log.w(TAG, "$source:${idx + 1} expects 3+ columns, got ${parts.size} → skipped")
                continue
            }
            // Skip the header row (first non-empty, non-comment line whose
            // first cell isn't an eurio-id pattern). We use a permissive
            // heuristic: header has "eurio_id" literally as its first cell.
            if (!sawHeader && parts[0].equals("eurio_id", ignoreCase = true)) {
                sawHeader = true
                continue
            }
            val eurioId = parts[0]
            val displayName = parts[2]
            if (eurioId.isEmpty() || displayName.isEmpty()) {
                Log.w(TAG, "$source:${idx + 1} empty eurio_id or display_name → skipped")
                continue
            }
            out.add(Coin(eurioId = eurioId, displayName = displayName))
        }
        return out
    }
}
