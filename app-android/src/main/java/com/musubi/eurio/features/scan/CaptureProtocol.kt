package com.musubi.eurio.features.scan

/**
 * Phase 0 capture protocol: 4 coins × 6 steps = 24 snaps.
 *
 * Drives the debug "capture" mode. Each step has an [id] used as filename prefix
 * and a [label] shown on screen as the instruction to the user.
 *
 * See docs/scan-normalization/phase-0-capture.md.
 */
object CaptureProtocol {

    data class Step(val id: String, val label: String)

    data class Coin(val eurioId: String, val displayName: String)

    val coins: List<Coin> = listOf(
        Coin("ad-2014-2eur-standard", "Andorre 2014 — standard"),
        Coin(
            "de-2007-2eur-schwerin-castle-mecklenburg-vorpommern",
            "Allemagne 2007 — Schwerin",
        ),
        Coin(
            "de-2020-2eur-50-years-since-the-kniefall-von-warschau",
            "Allemagne 2020 — Kniefall",
        ),
        Coin("fr-2007-2eur-standard", "France 2007 — standard"),
    )

    val steps: List<Step> = listOf(
        Step("bright_plain", "Intérieur lumineux, fond uni clair, centré"),
        Step("dim_plain", "Lumière tamisée / chaude, fond uni, centré"),
        Step("daylight_plain", "Plein jour ou proche fenêtre, fond uni"),
        Step("bright_textured", "Intérieur lumineux, fond texturé (tissu/bois)"),
        Step("tilt_plain", "Pièce inclinée ~10°, fond uni"),
        Step("close_plain", "Distance proche, pièce remplit le mask"),
    )

    val totalSnaps: Int get() = coins.size * steps.size
}
