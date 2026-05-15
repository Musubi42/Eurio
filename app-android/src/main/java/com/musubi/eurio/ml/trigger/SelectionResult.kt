package com.musubi.eurio.ml.trigger

/**
 * Output of [BestFrameSelector]. Per `feedback_no_debt`, the selector never
 * silently returns null — empty input maps to [SelectionResult.Empty] so the
 * HUD / record JSONL can surface the case as a first-class signal.
 */
sealed class SelectionResult {
    data class Best(
        val frame: BufferedFrame,
        val indexInSnapshot: Int,
        val reason: SelectionReason,
    ) : SelectionResult()

    object Empty : SelectionResult()
}

enum class SelectionReason {
    /** At least one frame passed every active gate — selector returns the oldest qualifier. */
    PASSED_ALL_GATES,

    /** No frame passed the gates — selector falls back to max aggregate. */
    BEST_AGGREGATE_FALLBACK,
}
