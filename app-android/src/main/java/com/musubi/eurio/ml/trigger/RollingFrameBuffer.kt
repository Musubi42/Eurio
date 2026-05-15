package com.musubi.eurio.ml.trigger

/**
 * Bounded ring of [BufferedFrame] used as the pre-trigger memory (P2). At
 * each push the oldest frame is evicted when the buffer exceeds [capacity];
 * the optional [onEvict] callback lets the caller recycle the bitmap (or any
 * other resource owned by the frame) deterministically — so long-running
 * sessions don't bleed `~196 KB` per evicted frame onto the GC.
 *
 * Thread-safety: [push] runs on the camera analyzer thread; [capacity]
 * mutations come from the main thread (debug-bar slider). All public ops
 * synchronize on a single intrinsic lock — cheap enough for an N≤20 buffer.
 *
 * Per `feedback_no_debt`, capacity is bounded to `1..20` at runtime; anything
 * outside throws so we surface misconfigured callers loudly rather than
 * silently clamping.
 */
class RollingFrameBuffer(
    initialCapacity: Int = 5,
    private val onEvict: (BufferedFrame) -> Unit = {},
) {
    init {
        require(initialCapacity in CAPACITY_RANGE) {
            "initialCapacity $initialCapacity out of $CAPACITY_RANGE"
        }
    }

    private val lock = Any()
    private val buffer = ArrayDeque<BufferedFrame>()

    @Volatile
    var capacity: Int = initialCapacity
        private set

    val size: Int
        get() = synchronized(lock) { buffer.size }

    fun push(frame: BufferedFrame) {
        synchronized(lock) {
            buffer.addLast(frame)
            evictExcessLocked()
        }
    }

    fun setCapacity(value: Int) {
        require(value in CAPACITY_RANGE) { "capacity $value out of $CAPACITY_RANGE" }
        synchronized(lock) {
            if (value == capacity) return
            capacity = value
            evictExcessLocked()
        }
    }

    /**
     * Lecture-seule snapshot, oldest first. The frames inside are still owned
     * by the buffer — callers must not call `crop.recycle()` and should not
     * hold a reference past their immediate use, since an eviction may occur
     * concurrently on the analyzer thread.
     */
    fun snapshot(): List<BufferedFrame> = synchronized(lock) { buffer.toList() }

    fun clear() {
        synchronized(lock) {
            while (buffer.isNotEmpty()) onEvict(buffer.removeFirst())
        }
    }

    private fun evictExcessLocked() {
        while (buffer.size > capacity) onEvict(buffer.removeFirst())
    }

    companion object {
        val CAPACITY_RANGE = 1..20
    }
}
