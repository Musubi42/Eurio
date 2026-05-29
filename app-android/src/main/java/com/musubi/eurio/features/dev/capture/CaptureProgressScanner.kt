package com.musubi.eurio.features.dev.capture

/**
 * Pure (Android-free) reconstruction of capture-cohort progress from the set of
 * crops present on disk plus the skipped steps recorded in the manifest.
 *
 * This is the single source of truth for two consumers (cf.
 * docs/operations/debug-data-taxonomy.md §6) :
 *  - [CaptureViewModel.enter] — rebuilds the resume cursor instead of resetting
 *    every index to 0 (the original bug).
 *  - The `/dev/status` screen — renders the per-coin / per-step grid.
 *
 * Kept free of the Android `File` API on purpose so it is unit-testable on the
 * plain JVM ; the Android-side adapter ([CaptureDiskReader]) supplies the
 * `cropExists` predicate and the `skippedSteps` set.
 */
object CaptureProgressScanner {

    enum class StepStatus {
        /** All [photosPerStep] crops present. */
        CAPTURED,

        /** Some but not all photos captured, step not skipped. */
        PARTIAL,

        /** Step explicitly skipped (manifest "event":"skip"). */
        SKIPPED,

        /** Nothing captured and not skipped. */
        PENDING,
    }

    data class StepCell(
        val stepIndex: Int,
        val capturedPhotos: Int,
        val photosPerStep: Int,
        val skipped: Boolean,
    ) {
        val status: StepStatus
            get() = when {
                skipped -> StepStatus.SKIPPED
                capturedPhotos <= 0 -> StepStatus.PENDING
                capturedPhotos >= photosPerStep -> StepStatus.CAPTURED
                else -> StepStatus.PARTIAL
            }
    }

    data class CoinRow(val coinIndex: Int, val steps: List<StepCell>)

    /**
     * Full scan result. [resume*] indices point at the first cell that is
     * neither captured nor skipped (in coin → step → photo order). When every
     * cell is captured or skipped, [isComplete] is true and the resume indices
     * point one past the last coin (matching the existing "complete" state in
     * [CaptureViewModel]).
     */
    data class Scan(
        val coins: List<CoinRow>,
        val captured: Int,
        val total: Int,
        val resumeCoinIndex: Int,
        val resumeStepIndex: Int,
        val resumePhotoIndex: Int,
        val isComplete: Boolean,
    )

    /**
     * @param coinCount     number of coins in the active protocol
     * @param stepCount     number of steps per coin
     * @param photosPerStep photos to shoot per (coin, step) cell
     * @param cropExists    `(coinIndex, stepIndex, photoIndex) -> Boolean` —
     *                      true when that photo's crop is on disk
     * @param isSkipped     `(coinIndex, stepIndex) -> Boolean` — true when that
     *                      step was explicitly skipped
     */
    fun scan(
        coinCount: Int,
        stepCount: Int,
        photosPerStep: Int,
        cropExists: (coinIndex: Int, stepIndex: Int, photoIndex: Int) -> Boolean,
        isSkipped: (coinIndex: Int, stepIndex: Int) -> Boolean,
    ): Scan {
        var captured = 0
        var resume: Triple<Int, Int, Int>? = null
        val coins = ArrayList<CoinRow>(coinCount)

        for (c in 0 until coinCount) {
            val steps = ArrayList<StepCell>(stepCount)
            for (s in 0 until stepCount) {
                val skipped = isSkipped(c, s)
                var capturedInStep = 0
                for (p in 0 until photosPerStep) {
                    if (cropExists(c, s, p)) {
                        captured++
                        capturedInStep++
                    } else if (resume == null && !skipped) {
                        resume = Triple(c, s, p)
                    }
                }
                steps.add(
                    StepCell(
                        stepIndex = s,
                        capturedPhotos = capturedInStep,
                        photosPerStep = photosPerStep,
                        skipped = skipped,
                    ),
                )
            }
            coins.add(CoinRow(coinIndex = c, steps = steps))
        }

        val total = coinCount * stepCount * photosPerStep
        return if (resume == null) {
            // Nothing left to do — point one past the last coin (complete state).
            Scan(
                coins = coins,
                captured = captured,
                total = total,
                resumeCoinIndex = coinCount,
                resumeStepIndex = 0,
                resumePhotoIndex = 0,
                isComplete = true,
            )
        } else {
            val (rc, rs, rp) = resume
            Scan(
                coins = coins,
                captured = captured,
                total = total,
                resumeCoinIndex = rc,
                resumeStepIndex = rs,
                resumePhotoIndex = rp,
                isComplete = false,
            )
        }
    }
}
