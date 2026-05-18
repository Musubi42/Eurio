package com.musubi.eurio.features.scan

/**
 * Transient feedback emitted by [ScanViewModel] for the Scan-screen
 * snackbar host. Replay = 0 because each event is a "show this now"
 * signal — collecting late shouldn't replay an old promotion.
 */
sealed class ScanSnackbarEvent {
    /**
     * D17 — fired by the archive flow when a newly written capture has
     * a higher aggregate quality than the existing primary on a coin
     * the user already owns. The action "Annuler" restores
     * [previousPrimaryId] without deleting the freshly archived capture.
     */
    data class PrimaryPromoted(
        val eurioId: String,
        val newPrimaryId: String,
        val previousPrimaryId: String,
    ) : ScanSnackbarEvent()
}
