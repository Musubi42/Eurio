package com.musubi.eurio.ml.bench

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import com.musubi.eurio.features.scan.debug.CaptureMode
import com.musubi.eurio.features.scan.debug.DebugScanConfig
import com.musubi.eurio.features.scan.debug.TriggerMode
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json

/**
 * Streams [BenchEvent]s to `context.filesDir/bench/sessions/<id>/events.jsonl`
 * during a scan session. One line = one event ; the writer flushes per
 * line so a crash mid-session leaves a partially-readable trail
 * ([[feedback_no_debt]] : no silent corruption).
 *
 * Threading :
 *  - [log] serialises the event and offers it to a [Channel] of size
 *    1024. Channel full → the line is dropped and a `droppedLines`
 *    counter ticks ; reported in [BenchEvent.SessionEnd] so replay
 *    tooling can flag truncated sessions.
 *  - A single drain coroutine on [Dispatchers.IO] writes the channel
 *    to disk. Closed when the session stops, which lets `for (line in
 *    channel)` exit cleanly.
 *
 * The class is **inactive** unless a session is started. All log calls
 * are no-ops when [session] is null, so wiring it everywhere on the
 * pipeline has zero cost outside bench mode.
 */
class BenchRecorder(
    private val context: Context,
    private val scope: CoroutineScope,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    companion object {
        private const val TAG = "BenchRecorder"
        /**
         * Bumped on any breaking shape change. v2 renamed
         * `ArcfacePayload.eurio_id`→`class_name` (top-K carries the
         * model label, not a canonical id) and
         * `FrameAnalyzed.seq`→`frame_ts_ms` (it's a timestamp, not a
         * sequence counter).
         */
        const val SCHEMA_VERSION: Int = 2
        const val CHANNEL_CAPACITY: Int = 1024
        const val FRAMES_DIR: String = "frames"
        const val EVENTS_FILE: String = "events.jsonl"
    }

    private val json = Json {
        encodeDefaults = true
        classDiscriminator = "evt"
        ignoreUnknownKeys = true
    }

    @Volatile private var session: BenchSession? = null
    @Volatile private var channel: Channel<String>? = null
    @Volatile private var drainJob: Job? = null
    private val droppedLines = AtomicLong(0)

    val activeSessionId: String? get() = session?.id
    val isActive: Boolean get() = session != null

    /**
     * Open a new session. Returns the generated `session_id`, or the
     * already-active one (and warns) if a session is in progress —
     * callers must [stop] before starting a fresh one.
     *
     * Writes `session_start`, `device_info` and `config_snapshot` in
     * that order so the replay tooling can reconstruct context from
     * the first three lines without scanning the whole file.
     */
    @Synchronized
    fun start(
        config: DebugScanConfig,
        deviceInfo: BenchEvent.DeviceInfo,
        coin: String? = null,
        condition: String? = null,
    ): String {
        val existing = session
        if (existing != null) {
            Log.w(TAG, "start() called while ${existing.id} is active — ignoring")
            return existing.id
        }
        val id = generateSessionId(clock())
        // External app-scoped storage: directly `adb pull`-able without
        // root or run-as wrapping. Falls back to internal filesDir if
        // external is unavailable (rare on modern Android).
        val root = context.getExternalFilesDir(null) ?: context.filesDir
        val dir = File(root, "bench/sessions/$id").apply { mkdirs() }
        val eventsFile = File(dir, EVENTS_FILE)
        val s = BenchSession(
            id = id,
            dir = dir,
            eventsFile = eventsFile,
            startedAtMs = clock(),
            coin = coin,
            condition = condition,
        )
        val ch = Channel<String>(capacity = CHANNEL_CAPACITY)
        session = s
        channel = ch
        droppedLines.set(0)
        drainJob = scope.launch(Dispatchers.IO) {
            eventsFile.bufferedWriter().use { writer ->
                for (line in ch) {
                    writer.appendLine(line)
                    writer.flush()
                }
            }
        }
        Log.d(TAG, "bench session started: id=$id coin=$coin condition=$condition dir=${dir.absolutePath}")
        log(
            BenchEvent.SessionStart(
                t = nowSeconds(),
                sessionId = id,
                coin = coin,
                condition = condition,
            )
        )
        log(deviceInfo.copy(t = nowSeconds()))
        log(
            BenchEvent.ConfigSnapshot(
                t = nowSeconds(),
                config = config.toPayload(),
            )
        )
        return id
    }

    /**
     * Close the active session. Writes `session_end` (with droppedLines
     * total), then closes the channel so the drain coroutine flushes
     * remaining lines and exits.
     */
    @Synchronized
    fun stop() {
        val s = session ?: return
        log(
            BenchEvent.SessionEnd(
                t = nowSeconds(),
                durationMs = clock() - s.startedAtMs,
                droppedLines = droppedLines.get(),
            )
        )
        channel?.close()
        channel = null
        session = null
        Log.d(TAG, "bench session stopped: id=${s.id} dropped=${droppedLines.get()}")
    }

    /** Append a structured event. No-op when no session is active. */
    fun log(event: BenchEvent) {
        val ch = channel ?: return
        val line = try {
            json.encodeToString(BenchEvent.serializer(), event)
        } catch (e: Throwable) {
            Log.e(TAG, "encode failed for ${event::class.simpleName}", e)
            return
        }
        val result = ch.trySend(line)
        if (result.isFailure || result.isClosed) {
            droppedLines.incrementAndGet()
            if (droppedLines.get() % 32 == 1L) {
                Log.w(TAG, "bench channel full, dropping events (total=${droppedLines.get()})")
            }
        }
    }

    /**
     * Persist a JPEG frame keyed by its [seq] (matches the rolling
     * buffer's `sequenceId`). No-op outside a session or when
     * `frames/` recording is disabled (toggle gated at the caller).
     */
    fun recordFrame(seq: Long, bitmap: Bitmap, quality: Int = 85) {
        val s = session ?: return
        scope.launch(Dispatchers.IO) {
            try {
                val framesDir = File(s.dir, FRAMES_DIR).apply { mkdirs() }
                val out = File(framesDir, "%04d.jpg".format(seq))
                FileOutputStream(out).use { bitmap.compress(Bitmap.CompressFormat.JPEG, quality, it) }
            } catch (e: Throwable) {
                Log.e(TAG, "frame write failed seq=$seq", e)
            }
        }
    }

    /** Convenience timestamp helper used by emitters. */
    fun nowSeconds(): Double = clock() / 1000.0

    private fun generateSessionId(nowMs: Long): String {
        val ts = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date(nowMs))
        val rnd = (Math.random() * 0xFFFF).toInt().toString(16).padStart(4, '0')
        return "${ts}_$rnd"
    }
}

/**
 * Wire-format mapper for [DebugScanConfig]. Lives next to the recorder
 * so the JSONL schema stays in lockstep with the in-app knob set —
 * adding a slider to [DebugScanConfig] flags an unresolved reference
 * here at compile time.
 */
fun DebugScanConfig.toPayload(): ConfigPayload = ConfigPayload(
    triggerMode = triggerMode.name,
    stabilityIouMin = stabilityIouMin,
    stabilityNFrames = stabilityNFrames,
    yoloConfMin = yoloConfMin,
    burstSize = burstSize,
    rollingBufferEnabled = rollingBufferEnabled,
    aeLockEnabled = aeLockEnabled,
    afLockEnabled = afLockEnabled,
    awbLockEnabled = awbLockEnabled,
    sharpnessMin = sharpnessMin,
    exposureBandHalfWidth = exposureBandHalfWidth,
    completenessMin = completenessMin,
    motionEnabled = motionEnabled,
    captureMode = captureMode.name,
)

@Suppress("unused")
private fun stableEnums(): Pair<TriggerMode, CaptureMode> =
    TriggerMode.OFF to CaptureMode.PREVIEW_ONLY
