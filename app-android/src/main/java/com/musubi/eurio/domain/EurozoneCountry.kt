package com.musubi.eurio.domain

// Les 21 pays de la zone euro au 2026-01-01 (Bulgarie rejointe cette année).
// Ordre alphabétique par code ISO.
enum class EurozoneCountry(
    val iso2: String,
    val labelFr: String,
) {
    AT("AT", "Autriche"),
    BE("BE", "Belgique"),
    BG("BG", "Bulgarie"),
    CY("CY", "Chypre"),
    DE("DE", "Allemagne"),
    EE("EE", "Estonie"),
    ES("ES", "Espagne"),
    FI("FI", "Finlande"),
    FR("FR", "France"),
    GR("GR", "Grèce"),
    HR("HR", "Croatie"),
    IE("IE", "Irlande"),
    IT("IT", "Italie"),
    LT("LT", "Lituanie"),
    LU("LU", "Luxembourg"),
    LV("LV", "Lettonie"),
    MT("MT", "Malte"),
    NL("NL", "Pays-Bas"),
    PT("PT", "Portugal"),
    SI("SI", "Slovénie"),
    SK("SK", "Slovaquie");

    // Drapeau emoji dérivé à la volée — évite les surrogate pairs hardcodés.
    val flagEmoji: String get() = iso2ToFlagEmoji(iso2)

    companion object {
        fun fromIso2(code: String?): EurozoneCountry? =
            code?.uppercase()?.let { c -> entries.firstOrNull { it.iso2 == c } }
    }
}

// Convertit un code ISO 3166-1 alpha-2 en drapeau emoji via les code points
// Regional Indicator Symbol (U+1F1E6 = 'A'). Ex : "FR" → 🇫🇷.
fun iso2ToFlagEmoji(iso2: String): String {
    if (iso2.length != 2) return ""
    val base = 0x1F1E6 - 'A'.code
    val cp1 = base + iso2[0].uppercaseChar().code
    val cp2 = base + iso2[1].uppercaseChar().code
    return buildString {
        appendCodePoint(cp1)
        appendCodePoint(cp2)
    }
}
