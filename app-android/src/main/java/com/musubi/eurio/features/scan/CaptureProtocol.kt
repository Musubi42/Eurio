package com.musubi.eurio.features.scan

import android.content.Context
import android.util.Log

/**
 * Capture protocol — drives the debug "capture" walkthrough that produces
 * golden eval snaps (the data we copy into ml/datasets/eval_real for the
 * train↔inference gap measurement).
 *
 * The coin list is loaded at app startup from
 * ``app-android/src/main/assets/capture_coins.csv`` so it can be edited
 * by hand and bundled into the APK on install — no code change needed
 * to grow the eval set from 4 → 24 → N classes.
 *
 * The step list stays hardcoded: it's the protocol itself (lighting +
 * background + tilt conditions), not a per-coin payload.
 *
 * See docs/scan-normalization/phase-0-capture.md.
 */
object CaptureProtocol {

    private const val TAG = "CaptureProtocol"
    private const val ASSET_PATH = "capture_coins.csv"

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
        _coins = runCatching { readAsset(context) }
            .onFailure { Log.e(TAG, "Failed to load $ASSET_PATH", it) }
            .getOrDefault(emptyList())
        Log.i(TAG, "Loaded ${_coins.size} coin(s) from $ASSET_PATH")
    }

    private fun readAsset(context: Context): List<Coin> {
        val lines = context.assets.open(ASSET_PATH).bufferedReader().use { it.readLines() }
        val out = mutableListOf<Coin>()
        var sawHeader = false
        for ((idx, raw) in lines.withIndex()) {
            val line = raw.trim()
            if (line.isEmpty() || line.startsWith("#")) continue
            val parts = line.split(';').map { it.trim() }
            if (parts.size < 3) {
                Log.w(TAG, "$ASSET_PATH:${idx + 1} expects 3+ columns, got ${parts.size} → skipped")
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
                Log.w(TAG, "$ASSET_PATH:${idx + 1} empty eurio_id or display_name → skipped")
                continue
            }
            out.add(Coin(eurioId = eurioId, displayName = displayName))
        }
        return out
    }
}
