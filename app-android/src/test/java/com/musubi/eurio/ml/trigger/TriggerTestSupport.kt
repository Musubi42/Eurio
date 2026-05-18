package com.musubi.eurio.ml.trigger

import com.musubi.eurio.ml.DetectionSource

/**
 * Builds a minimal [FrameContext] for trigger unit tests. The buffer is
 * always empty here — strategies under test only read `primary…` /
 * `arcfaceTop1` / `consensusLockedClass`, so leaving the buffer empty keeps
 * the fixtures terse. Tests that exercise the bufferSnapshot in `Fire`
 * events still get a non-null (empty) list.
 */
internal fun ctx(
    bbox: BboxF? = null,
    confidence: Float? = null,
    source: DetectionSource? = null,
    consensus: String? = null,
): FrameContext = FrameContext(
    sequenceId = 0,
    buffer = emptyList(),
    primaryBbox = bbox,
    primaryConfidence = confidence,
    primarySource = source,
    arcfaceTop1 = null,
    consensusLockedClass = consensus,
)
