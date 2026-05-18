package com.musubi.eurio.data.vault

import android.os.Build
import com.musubi.eurio.domain.scan.ArcfaceMatch
import com.musubi.eurio.domain.scan.LockResultSnapshot
import com.musubi.eurio.domain.scan.SourceMode
import com.musubi.eurio.domain.scan.quality.FrameScore
import com.musubi.eurio.features.scan.debug.TimingBreakdown
import com.musubi.eurio.ml.DetectionSource
import com.musubi.eurio.ml.trigger.BboxF
import org.json.JSONArray
import org.json.JSONObject

/**
 * Per-capture pipeline snapshot persisted as JSON in
 * `coin_captures.capture_metadata_json`.
 *
 * Stored verbatim (not minified): keeps individual files < 4 KB, lets
 * the future bench/replay tooling (chunk-7) reconstruct what the
 * model saw without needing to re-run the live pipeline.
 *
 * `schemaVersion` lets a future reader detect older payloads — bump on
 * any breaking shape change.
 */
data class CaptureMetadata(
    val frameScore: FrameScore,
    val detectionBbox: BboxF?,
    val detectionConfidence: Float?,
    val detectionSource: DetectionSource?,
    val triggerMode: String,
    val triggerFireReason: String?,
    val lockResult: LockResultSnapshot?,
    val arcfaceTop3: List<ArcfaceMatch>,
    val sourceMode: SourceMode,
    val timings: TimingBreakdown,
    val deviceModel: String = Build.MODEL,
    val androidApi: Int = Build.VERSION.SDK_INT,
    val schemaVersion: Int = SCHEMA_VERSION,
) {
    companion object {
        const val SCHEMA_VERSION: Int = 1

        fun encode(metadata: CaptureMetadata): String = JSONObject().apply {
            put("schemaVersion", metadata.schemaVersion)
            put("deviceModel", metadata.deviceModel)
            put("androidApi", metadata.androidApi)
            put("sourceMode", metadata.sourceMode.wire)
            put("triggerMode", metadata.triggerMode)
            put("triggerFireReason", metadata.triggerFireReason ?: JSONObject.NULL)

            put("frameScore", JSONObject().apply {
                val s = metadata.frameScore
                put("sharpness", s.sharpness.toDouble())
                put("sharpnessRaw", s.sharpnessRaw.toDouble())
                put("exposure", s.exposure.toDouble())
                put("meanLuminance", s.meanLuminance.toDouble())
                put("clippingRatio", s.clippingRatio.toDouble())
                put("completeness", s.completeness.toDouble())
                put("motion", s.motion?.toDouble() ?: JSONObject.NULL)
                put("aggregate", s.aggregate.toDouble())
                put("passesAll", s.passes.all)
                put("passesSharpness", s.passes.sharpness)
                put("passesExposure", s.passes.exposure)
                put("passesCompleteness", s.passes.completeness)
                put("passesMotion", s.passes.motion ?: JSONObject.NULL)
            })

            put("detection", JSONObject().apply {
                val b = metadata.detectionBbox
                if (b != null) {
                    put("left", b.left.toDouble())
                    put("top", b.top.toDouble())
                    put("right", b.right.toDouble())
                    put("bottom", b.bottom.toDouble())
                } else {
                    put("bbox", JSONObject.NULL)
                }
                put("confidence", metadata.detectionConfidence?.toDouble() ?: JSONObject.NULL)
                put("source", metadata.detectionSource?.name ?: JSONObject.NULL)
            })

            put("lockResult", metadata.lockResult?.let { lr ->
                JSONObject().apply {
                    put("durationMs", lr.durationMs)
                    put("afConverged", lr.afConverged)
                    put("aeLocked", lr.aeLocked)
                    put("awbLocked", lr.awbLocked)
                }
            } ?: JSONObject.NULL)

            put("arcfaceTop3", JSONArray().apply {
                metadata.arcfaceTop3.forEach { m ->
                    put(JSONObject().apply {
                        put("className", m.className)
                        put("similarity", m.similarity.toDouble())
                    })
                }
            })

            put("timings", JSONObject().apply {
                put("detectMs", metadata.timings.detectMs)
                put("normalizeMs", metadata.timings.normalizeMs)
                put("arcfaceMs", metadata.timings.arcfaceMs)
                put("scoreMs", metadata.timings.scoreMs)
            })
        }.toString(2)
    }
}

