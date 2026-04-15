package com.musubi.eurio.ui.nav

// Routes top-level de l'app. Phase 0 : 3 destinations (Scan, Coffre, Profil).
// Les sous-routes (coin detail, set detail, country drill-down) arrivent en
// Phase 1+.
object EurioDestinations {
    const val SCAN = "scan"
    const val COFFRE = "coffre"
    const val PROFIL = "profil"

    // Futur :
    // const val COIN_DETAIL = "coin/{eurioId}"
    // const val SET_DETAIL = "set/{setId}"
    // const val COUNTRY_DRILLDOWN = "catalog/country/{countryCode}"
}

enum class BottomNavTab(val route: String, val labelFr: String) {
    COFFRE(EurioDestinations.COFFRE, "Coffre"),
    PROFIL(EurioDestinations.PROFIL, "Profil"),
}
