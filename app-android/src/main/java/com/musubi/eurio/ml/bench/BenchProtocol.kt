package com.musubi.eurio.ml.bench

import com.musubi.eurio.features.scan.CaptureProtocol

/**
 * Guided bench protocol (chunk-7b). Drives the user through every
 * (coin × condition) cell so each [com.musubi.eurio.ml.bench.BenchRecorder]
 * session is auto-tagged with the protocol metadata it belongs to —
 * removing the need for a manual `annotate_session.py` step for the
 * `coin` and `condition` ground-truth axes.
 *
 * The cohort comes from [CaptureProtocol.coins] (same `cohort.csv`
 * loaded by the golden-set capture flow — runtime override pushable
 * via `go-task android:push-capture-csv`).
 *
 * The conditions are the five canonical ones agreed in the chunk-7
 * design (cf. `docs/best-frame-capture/chunk-7-bench-protocol.md`).
 */
object BenchProtocol {

    data class Condition(val id: String, val label: String)

    /** Five standardised conditions, in the order presented to the operator. */
    val conditions: List<Condition> = listOf(
        Condition("bright_plain", "Lumière jour, fond uni"),
        Condition("bright_textured", "Lumière jour, fond bois ou tissu"),
        Condition("dim", "Intérieur soir, lampe loin"),
        Condition("oblique", "Caméra inclinée ~30°"),
        Condition("glare_specular", "Lampe directe au-dessus, reflet central"),
    )

    data class Cell(val coin: CaptureProtocol.Coin, val condition: Condition) {
        val displayLabel: String get() = "${coin.displayName} · ${condition.label}"
    }

    /**
     * All cells in protocol order: outer loop = coin, inner = condition.
     * Ordering is intentional — the operator changes the lighting setup
     * less often than the coin in front of the lens.
     */
    fun cells(): List<Cell> = CaptureProtocol.coins.flatMap { coin ->
        conditions.map { cond -> Cell(coin, cond) }
    }
}
