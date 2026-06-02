package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.entities.CoinPriceEntity
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Rareté dérivée du ratio cote/faciale. Port de `RARITY_SCALE`
 * (admin/packages/proto/src/api/market.ts).
 */
enum class CoinRarity(val label: String, val gold: Boolean) {
    COMMUNE("Commune", false),
    PEU_COURANTE("Peu courante", false),
    RARE("Rare", true),
    TRES_RARE("Très rare", true),
}

/** Cotes par état (euros). Port de `Grades` (proto). */
data class CoinGrades(val unc: Double?, val ttb: Double?, val tb: Double?)

/**
 * Vue marché d'une pièce dérivée des **cotes réelles** (`coin_prices`).
 *
 * Port fidèle de `market.marketFromPrices()` du proto : base TTB (sinon 1ʳᵉ
 * cote), p25=pLow / p75=pHigh avec fallbacks ×0.8 / ×1.2, rareté par ratio
 * cote/faciale. On ne fabrique **pas** de série temporelle (le proto laisse
 * history/projection nuls quand les cotes sont réelles) → pas de fausse
 * tendance. `null` = pas de cote exploitable (pièce de circulation à la
 * faciale → état vide, comme côté web).
 *
 * NB : le fallback synthétique seedé du proto (`deriveMarket` sans prix) n'est
 * pas porté — hors périmètre QA (toutes les pièces à cote affichée ont des
 * prix réels) et écarté par doctrine « pas de tendance fabriquée ».
 */
data class CoinMarket(
    val p25: Double,
    val p50: Double,
    val p75: Double,
    val deltaVsFacePct: Double,
    val rarity: CoinRarity,
    val grades: CoinGrades,
)

private fun centsToEur(cents: Int?): Double? = if (cents == null) null else cents.toDouble() / 100.0

private fun round2(v: Double): Double = (v * 100).roundToInt() / 100.0

/** Miroir exact de `marketFromPrices` (proto). `faceValueCents` sert au ratio. */
fun deriveMarketFromPrices(prices: List<CoinPriceEntity>, faceValueCents: Int): CoinMarket? {
    if (prices.isEmpty()) return null
    val byGrade = prices.associateBy { it.grade.uppercase() }
    val ttb = byGrade["TTB"] ?: prices.first()
    val p50 = centsToEur(ttb.pMid ?: ttb.pHigh ?: ttb.pLow) ?: return null
    val p25 = centsToEur(ttb.pLow) ?: (p50 * 0.8)
    val p75 = centsToEur(ttb.pHigh) ?: (p50 * 1.2)
    val faceEur = faceValueCents.toDouble() / 100.0

    val grades = CoinGrades(
        unc = centsToEur(byGrade["UNC"]?.pMid) ?: round2(p50 * 1.8),
        ttb = centsToEur(ttb.pMid) ?: p50,
        tb = centsToEur(byGrade["TB"]?.pMid) ?: round2(max(2.0, p50 * 0.5)),
    )
    val ratio = p50 / max(faceEur, 1.0)
    val rarity = when {
        ratio > 6 -> CoinRarity.TRES_RARE
        ratio > 3.5 -> CoinRarity.RARE
        ratio > 1.8 -> CoinRarity.PEU_COURANTE
        else -> CoinRarity.COMMUNE
    }
    val deltaVsFace = if (faceEur > 0) ((p50 - faceEur) / faceEur) * 100 else 0.0
    return CoinMarket(p25 = p25, p50 = p50, p75 = p75, deltaVsFacePct = deltaVsFace, rarity = rarity, grades = grades)
}
