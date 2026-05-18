package com.musubi.eurio.ml.bench

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonClassDiscriminator

/**
 * Polymorphic JSONL event written by [BenchRecorder] into a session's
 * `events.jsonl`. Each subclass maps to one `"evt":"<name>"` line ; the
 * `t` field is a unix timestamp in seconds (double) for easy correlation
 * with replay tooling on the Python side.
 *
 * Schema versioned via [BenchRecorder.SCHEMA_VERSION] — bump on any
 * breaking shape change.
 *
 * For chunk-7a we cover the structural events (session, config, state
 * machine, lock, capture, consensus, archive, user). FrameAnalyzed
 * (highest-volume) is included so the buffer/drain is stress-tested
 * early. Additional fine-grained events (best_frame_selected, etc.)
 * land at 7b alongside the guided protocol screen.
 */
@OptIn(kotlinx.serialization.ExperimentalSerializationApi::class)
@Serializable
@JsonClassDiscriminator("evt")
sealed class BenchEvent {
    abstract val t: Double

    @Serializable
    @SerialName("session_start")
    data class SessionStart(
        override val t: Double,
        @SerialName("session_id") val sessionId: String,
        @SerialName("schema_version") val schemaVersion: Int = BenchRecorder.SCHEMA_VERSION,
        val coin: String? = null,
        val condition: String? = null,
    ) : BenchEvent()

    @Serializable
    @SerialName("session_end")
    data class SessionEnd(
        override val t: Double,
        @SerialName("duration_ms") val durationMs: Long,
        @SerialName("dropped_lines") val droppedLines: Long,
    ) : BenchEvent()

    @Serializable
    @SerialName("device_info")
    data class DeviceInfo(
        override val t: Double,
        val model: String,
        val api: Int,
        val manufacturer: String? = null,
        val sensor: String? = null,
    ) : BenchEvent()

    @Serializable
    @SerialName("config_snapshot")
    data class ConfigSnapshot(
        override val t: Double,
        val config: ConfigPayload,
    ) : BenchEvent()

    @Serializable
    @SerialName("state_transition")
    data class StateTransition(
        override val t: Double,
        val from: String,
        val to: String,
        @SerialName("via_event") val viaEvent: String,
    ) : BenchEvent()

    @Serializable
    @SerialName("trigger_fire")
    data class TriggerFire(
        override val t: Double,
        val strategy: String,
        val reason: String,
    ) : BenchEvent()

    @Serializable
    @SerialName("trigger_abort")
    data class TriggerAbort(
        override val t: Double,
        val reason: String,
    ) : BenchEvent()

    @Serializable
    @SerialName("lock_state")
    data class LockStateEvent(
        override val t: Double,
        val state: String,
        @SerialName("af_converged") val afConverged: Boolean? = null,
        @SerialName("ae_locked") val aeLocked: Boolean? = null,
        @SerialName("awb_locked") val awbLocked: Boolean? = null,
        @SerialName("duration_ms") val durationMs: Long? = null,
        val reason: String? = null,
    ) : BenchEvent()

    @Serializable
    @SerialName("capture_completed")
    data class CaptureCompleted(
        override val t: Double,
        @SerialName("capture_id") val captureId: String,
        @SerialName("source_mode") val sourceMode: String,
    ) : BenchEvent()

    @Serializable
    @SerialName("capture_error")
    data class CaptureError(
        override val t: Double,
        val cause: String,
    ) : BenchEvent()

    @Serializable
    @SerialName("consensus_reached")
    data class ConsensusReached(
        override val t: Double,
        @SerialName("eurio_id") val eurioId: String,
        @SerialName("top_k") val topK: List<ArcfacePayload>,
    ) : BenchEvent()

    @Serializable
    @SerialName("archive_completed")
    data class ArchiveCompleted(
        override val t: Double,
        @SerialName("capture_id") val captureId: String,
    ) : BenchEvent()

    @Serializable
    @SerialName("archive_discarded")
    data class ArchiveDiscarded(
        override val t: Double,
        val reason: String,
    ) : BenchEvent()

    @Serializable
    @SerialName("user_action")
    data class UserAction(
        override val t: Double,
        val action: String,
    ) : BenchEvent()

    @Serializable
    @SerialName("frame_analyzed")
    data class FrameAnalyzed(
        override val t: Double,
        /**
         * Frame timestamp in unix milliseconds (`ScanResult.timestamp`).
         * Not a sequence counter — the analyzer doesn't currently
         * expose one. Monotonic per session, so still safe as an order
         * key for replay tooling.
         */
        @SerialName("frame_ts_ms") val frameTsMs: Long,
        val detection: DetectionPayload?,
        val score: ScorePayload?,
        @SerialName("arcface_top3") val arcfaceTop3: List<ArcfacePayload>,
        @SerialName("timings_ms") val timingsMs: TimingsPayload,
    ) : BenchEvent()
}

@Serializable
data class ConfigPayload(
    @SerialName("trigger_mode") val triggerMode: String,
    @SerialName("stability_iou_min") val stabilityIouMin: Float,
    @SerialName("stability_n_frames") val stabilityNFrames: Int,
    @SerialName("yolo_conf_min") val yoloConfMin: Float,
    @SerialName("burst_size") val burstSize: Int,
    @SerialName("rolling_buffer_enabled") val rollingBufferEnabled: Boolean,
    @SerialName("ae_lock_enabled") val aeLockEnabled: Boolean,
    @SerialName("af_lock_enabled") val afLockEnabled: Boolean,
    @SerialName("awb_lock_enabled") val awbLockEnabled: Boolean,
    @SerialName("sharpness_min") val sharpnessMin: Float,
    @SerialName("exposure_band_half_width") val exposureBandHalfWidth: Float,
    @SerialName("completeness_min") val completenessMin: Float,
    @SerialName("motion_enabled") val motionEnabled: Boolean,
    @SerialName("capture_mode") val captureMode: String,
)

@Serializable
data class DetectionPayload(
    val method: String,
    val bbox: List<Float>?,
    @SerialName("yolo_conf") val yoloConf: Float? = null,
)

@Serializable
data class ScorePayload(
    val sharpness: Float,
    @SerialName("sharpness_raw") val sharpnessRaw: Float,
    val exposure: Float,
    @SerialName("mean_luminance") val meanLuminance: Float,
    @SerialName("clipping_ratio") val clippingRatio: Float,
    val completeness: Float,
    val motion: Float? = null,
    val aggregate: Float,
    val passes: PassesPayload,
)

@Serializable
data class PassesPayload(
    val sharpness: Boolean,
    val exposure: Boolean,
    val completeness: Boolean,
    val motion: Boolean? = null,
    val all: Boolean,
)

/**
 * One ArcFace top-K entry. `class_name` is the **model output label**
 * (today : Numista numeric ID — the classifier was trained on those).
 * Resolution to canonical `eurio_id` happens at
 * `CoinRepository.resolveByClassifierName(...)`, and only the
 * `consensus_reached` event carries that resolved id. Bench tooling
 * must not confuse the two : top-K = raw model output, consensus =
 * resolved truth.
 */
@Serializable
data class ArcfacePayload(
    @SerialName("class_name") val className: String,
    val cos: Float,
)

@Serializable
data class TimingsPayload(
    val detect: Long,
    val normalize: Long,
    val arcface: Long,
    val score: Long,
)
