package com.musubi.eurio.ml.bench

import java.io.File

/**
 * Lightweight holder for one active bench session.
 *
 * `dir` is `context.filesDir/bench/sessions/<id>/` and contains
 * `events.jsonl`, optionally `frames/<seq>.jpg`. The recorder owns the
 * lifecycle ; this is just a value bundle.
 */
data class BenchSession(
    val id: String,
    val dir: File,
    val eventsFile: File,
    val startedAtMs: Long,
    val coin: String?,
    val condition: String?,
)
