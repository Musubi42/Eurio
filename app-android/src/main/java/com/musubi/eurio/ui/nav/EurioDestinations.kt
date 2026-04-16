package com.musubi.eurio.ui.nav

// Routes top-level de l'app. Phase 0 : 3 destinations (Scan, Coffre, Profil).
// Phase 1 : ajout de la route coin detail (drill-down depuis le scan + futures
// planches). Phase 3+ ajoutera set detail + catalogue country drilldown.
object EurioDestinations {
    const val SCAN = "scan"
    const val COFFRE = "coffre"
    const val PROFIL = "profil"

    // Coin detail : eurioId est le path arg, fromScan est un query arg optionnel
    // indiquant si l'écran est arrivé depuis un post-scan card (pour afficher
    // "Ajouter au coffre" en CTA persistant).
    const val COIN_DETAIL_ROUTE = "coin/{eurioId}?fromScan={fromScan}"
    const val COIN_DETAIL_ARG_EURIO_ID = "eurioId"
    const val COIN_DETAIL_ARG_FROM_SCAN = "fromScan"

    fun coinDetail(eurioId: String, fromScan: Boolean = false): String =
        "coin/$eurioId?fromScan=$fromScan"

    // Set detail drill-down from the Sets list
    const val SET_DETAIL_ROUTE = "set/{setId}"
    const val SET_DETAIL_ARG_SET_ID = "setId"

    fun setDetail(setId: String): String = "set/$setId"

    // Catalog country drill-down
    const val CATALOG_COUNTRY_ROUTE = "catalog/country/{countryCode}"
    const val CATALOG_COUNTRY_ARG = "countryCode"

    fun catalogCountry(countryCode: String): String = "catalog/country/$countryCode"
}

enum class BottomNavTab(val route: String, val labelFr: String) {
    COFFRE(EurioDestinations.COFFRE, "Coffre"),
    PROFIL(EurioDestinations.PROFIL, "Profil"),
}
