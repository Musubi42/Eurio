package com.musubi.eurio.features.scan

/**
 * Sticky ring-buffer consensus extracted from LegacyScanActivity.
 *
 * Rules (match the legacy logic 1:1):
 *  - Window size: 5 frames.
 *  - A "miss" (no accepted detection) is recorded as null and ages out with the window.
 *  - A class that appears ≥ 3 times in the window becomes the active consensus.
 *  - Once a consensus exists, it is STICKY — it is never cleared to null. A
 *    new consensus only replaces it when another class reaches the threshold.
 *
 * The buffer owns no UI state — it just exposes [push] and the current
 * consensus via [consensus] / [missStreak].
 */
class ConsensusBuffer(
    private val window: Int = DEFAULT_WINDOW,
    private val threshold: Int = DEFAULT_THRESHOLD,
) {
    companion object {
        const val DEFAULT_WINDOW = 5
        const val DEFAULT_THRESHOLD = 3
    }

    private val recent = ArrayDeque<String?>()

    private var stickyConsensus: String? = null

    /** Number of consecutive trailing misses. Useful for the "give up" timer. */
    var missStreak: Int = 0
        private set

    /** The currently-locked consensus class, or null if none has been reached yet. */
    val consensus: String? get() = stickyConsensus

    /**
     * Push a frame's top class (null = frame had no accepted detection).
     * Returns true when a NEW consensus was just reached on this push.
     */
    fun push(topClass: String?): Boolean {
        recent.addLast(topClass)
        while (recent.size > window) recent.removeFirst()

        missStreak = if (topClass == null) missStreak + 1 else 0

        val counts = recent.filterNotNull().groupingBy { it }.eachCount()
        val newConsensus = counts.entries
            .filter { it.value >= threshold }
            .maxByOrNull { it.value }
            ?.key

        if (newConsensus != null && newConsensus != stickyConsensus) {
            stickyConsensus = newConsensus
            return true
        }
        return false
    }

    /** Wipe the buffer and the sticky consensus. Used on cooldown / dismiss. */
    fun reset() {
        recent.clear()
        stickyConsensus = null
        missStreak = 0
    }
}
