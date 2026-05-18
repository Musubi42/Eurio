package com.musubi.eurio.domain.scan

/**
 * Single ArcFace match exposed across the scan domain: HUD, capture
 * metadata, state machine. Kept here (not in a feature/data layer) so
 * the reducer and persisted metadata share one canonical shape.
 */
data class ArcfaceMatch(
    val className: String,
    val similarity: Float,
)
