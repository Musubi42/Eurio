package com.musubi.eurio.cohorttest

import android.content.Context
import android.os.Environment
import android.util.Log
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.float
import kotlinx.serialization.json.int
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * JSONL writer for the live-test loop. One file per iteration:
 * `<getExternalFilesDir(Documents)>/eurio_live_tests/<iteration_id>.jsonl`.
 *
 * On Android 11+ this resolves to
 * `/sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/eurio_live_tests/<iteration_id>.jsonl`,
 * which is exactly the path `cohort-test:pull-tests` looks for.
 *
 * Append-only. We DO NOT replace existing lines on re-snap (Sprint 4 forbids
 * re-doing a test, see D-005); the activity only calls [append] when a fresh
 * snap arrives. On app relaunch the activity reads the file via [readAll] to
 * pre-populate the in-memory results list so the user resumes where they
 * left off.
 */
class LiveTestLogger(
    private val context: Context,
    private val iterationId: String,
) {
    private val isoFormat = SimpleDateFormat(
        "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US,
    ).apply { timeZone = TimeZone.getTimeZone("UTC") }

    val outputFile: File by lazy {
        val docs = context.getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS)
            ?: error("getExternalFilesDir(Documents) returned null")
        File(docs, "eurio_live_tests").also { it.mkdirs() }
            .let { File(it, "$iterationId.jsonl") }
    }

    fun isoNow(): String = isoFormat.format(Date())

    /**
     * Read existing JSONL lines (if any). Returns parsed results indexed by
     * test_idx. Errors on a single line don't abort the read — we skip and
     * log; the activity treats unreadable rows as "not yet snapped" so the
     * user can re-do them.
     */
    fun readAll(): Map<Int, TestResult> {
        val file = outputFile
        if (!file.exists()) return emptyMap()
        val out = mutableMapOf<Int, TestResult>()
        file.forEachLine { line ->
            if (line.isBlank()) return@forEachLine
            try {
                val obj = Json.parseToJsonElement(line) as JsonObject
                val idx = (obj["test_idx"] as? JsonPrimitive)?.int
                    ?: return@forEachLine
                val top3 = (obj["predicted_top3"] as? JsonArray)?.map { e ->
                    val m = e as JsonObject
                    TopMatch(
                        eurioId = (m["eurio_id"] as JsonPrimitive).content,
                        similarity = (m["similarity"] as JsonPrimitive).float,
                    )
                } ?: emptyList()
                out[idx] = TestResult(
                    testIdx = idx,
                    expectedEurioId = (obj["expected_eurio_id"] as JsonPrimitive).content,
                    condition = (obj["condition"] as JsonPrimitive).content,
                    predictedTop3 = top3,
                    predictedTop1 = nullableString(obj["predicted_top1"]),
                    similarityTop1 = nullableFloat(obj["similarity_top1"]),
                    isCorrect = (obj["is_correct"] as JsonPrimitive).boolean,
                    error = nullableString(obj["error"]),
                    ts = (obj["ts"] as JsonPrimitive).content,
                )
            } catch (e: Exception) {
                Log.w(TAG, "Skipping malformed line: ${line.take(80)}…", e)
            }
        }
        return out
    }

    private fun nullableString(el: kotlinx.serialization.json.JsonElement?): String? {
        if (el == null || el is JsonNull) return null
        return (el as? JsonPrimitive)?.content
    }

    private fun nullableFloat(el: kotlinx.serialization.json.JsonElement?): Float? {
        if (el == null || el is JsonNull) return null
        return (el as? JsonPrimitive)?.let {
            runCatching { it.float }.getOrNull()
        }
    }

    /**
     * Append one result. The line follows the schema documented in
     * `docs/training-pipeline/sprint-4-live-tests.md` §B step 9.
     */
    fun append(result: TestResult) {
        val line = buildString {
            append('{')
            append("\"schema_version\":1")
            append(",\"test_idx\":${result.testIdx}")
            append(",\"iteration_id\":${esc(iterationId)}")
            append(",\"expected_eurio_id\":${esc(result.expectedEurioId)}")
            append(",\"condition\":${esc(result.condition)}")
            append(",\"predicted_top3\":[")
            result.predictedTop3.forEachIndexed { i, m ->
                if (i > 0) append(',')
                append("{\"eurio_id\":${esc(m.eurioId)},\"similarity\":")
                append(formatFloat(m.similarity))
                append('}')
            }
            append(']')
            append(",\"predicted_top1\":${result.predictedTop1?.let { esc(it) } ?: "null"}")
            append(",\"similarity_top1\":")
            append(result.similarityTop1?.let { formatFloat(it) } ?: "null")
            append(",\"is_correct\":${result.isCorrect}")
            append(",\"error\":${result.error?.let { esc(it) } ?: "null"}")
            append(",\"ts\":${esc(result.ts)}")
            append('}')
        }
        outputFile.appendText(line + "\n")
    }

    private fun esc(s: String): String {
        val sb = StringBuilder(s.length + 2)
        sb.append('"')
        for (c in s) {
            when (c) {
                '\\' -> sb.append("\\\\")
                '"' -> sb.append("\\\"")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                else -> if (c.code < 0x20) sb.append("\\u%04x".format(c.code)) else sb.append(c)
            }
        }
        sb.append('"')
        return sb.toString()
    }

    private fun formatFloat(f: Float): String =
        if (f.isFinite()) "%.4f".format(Locale.US, f) else "null"

    companion object {
        private const val TAG = "LiveTestLogger"
    }
}

