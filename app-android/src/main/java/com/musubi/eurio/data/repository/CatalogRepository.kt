package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.dao.CoinDao
import com.musubi.eurio.data.local.dao.VaultDao
import com.musubi.eurio.domain.IssueType
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine

data class CountryProgress(
    val country: String,
    val owned: Int,
    val total: Int,
) {
    val percent: Float get() = if (total > 0) owned.toFloat() / total else 0f
}

data class CoinWithOwnership(
    val eurioId: String,
    val nameFr: String,
    val country: String,
    val year: Int,
    val faceValueCents: Int,
    val imageObverseUrl: String?,
    val issueType: String,
    val owned: Boolean,
)

interface CatalogRepository {
    fun observeCountryProgress(): Flow<List<CountryProgress>>
    fun observeCoinsForCountry(country: String, typeFilter: String?): Flow<List<CoinWithOwnership>>
}

class RoomCatalogRepository(
    private val coinDao: CoinDao,
    private val vaultDao: VaultDao,
) : CatalogRepository {

    override fun observeCountryProgress(): Flow<List<CountryProgress>> {
        return combine(
            coinDao.observeAll(),
            vaultDao.observeAll(),
        ) { coins, vaultEntries ->
            val ownedIds = vaultEntries.map { it.coinEurioId }.toSet()
            val eurozoneCodes = EUROZONE_COUNTRIES.keys
            coins
                .filter { it.country.lowercase() in eurozoneCodes.map { c -> c.lowercase() } }
                .groupBy { it.country.lowercase() }
                .map { (country, countryCoinList) ->
                    val owned = countryCoinList.count { it.eurioId in ownedIds }
                    CountryProgress(
                        country = country,
                        owned = owned,
                        total = countryCoinList.size,
                    )
                }
                .sortedBy { it.country }
        }
    }

    override fun observeCoinsForCountry(
        country: String,
        typeFilter: String?,
    ): Flow<List<CoinWithOwnership>> {
        return combine(
            coinDao.observeAll(),
            vaultDao.observeAll(),
        ) { coins, vaultEntries ->
            val ownedIds = vaultEntries.map { it.coinEurioId }.toSet()
            coins
                .filter { it.country.equals(country, ignoreCase = true) }
                .let { list ->
                    if (typeFilter == null) list
                    else list.filter { mapIssueType(it.issueType) == typeFilter }
                }
                .sortedWith(compareBy({ it.year }, { it.faceValue }))
                .map { coin ->
                    CoinWithOwnership(
                        eurioId = coin.eurioId,
                        nameFr = coin.nameFr ?: coin.nameEn ?: coin.eurioId,
                        country = coin.country,
                        year = coin.year ?: 0,
                        faceValueCents = ((coin.faceValue ?: 0.0) * 100).toInt(),
                        imageObverseUrl = coin.imageObverseUrl,
                        issueType = mapIssueType(coin.issueType),
                        owned = coin.eurioId in ownedIds,
                    )
                }
        }
    }

    private fun mapIssueType(type: IssueType?): String = when (type) {
        IssueType.CIRCULATION, IssueType.STARTER_KIT -> "circulation"
        IssueType.COMMEMO_NATIONAL, IssueType.COMMEMO_COMMON -> "commemo"
        IssueType.BU_SET, IssueType.PROOF -> "circulation"
        null -> "circulation"
    }

    companion object {
        val EUROZONE_COUNTRIES = mapOf(
            "at" to Pair("Autriche", "🇦🇹"),
            "be" to Pair("Belgique", "🇧🇪"),
            "bg" to Pair("Bulgarie", "🇧🇬"),
            "cy" to Pair("Chypre", "🇨🇾"),
            "de" to Pair("Allemagne", "🇩🇪"),
            "ee" to Pair("Estonie", "🇪🇪"),
            "es" to Pair("Espagne", "🇪🇸"),
            "fi" to Pair("Finlande", "🇫🇮"),
            "fr" to Pair("France", "🇫🇷"),
            "gr" to Pair("Grèce", "🇬🇷"),
            "hr" to Pair("Croatie", "🇭🇷"),
            "ie" to Pair("Irlande", "🇮🇪"),
            "it" to Pair("Italie", "🇮🇹"),
            "lt" to Pair("Lituanie", "🇱🇹"),
            "lu" to Pair("Luxembourg", "🇱🇺"),
            "lv" to Pair("Lettonie", "🇱🇻"),
            "mt" to Pair("Malte", "🇲🇹"),
            "nl" to Pair("Pays-Bas", "🇳🇱"),
            "pt" to Pair("Portugal", "🇵🇹"),
            "si" to Pair("Slovénie", "🇸🇮"),
            "sk" to Pair("Slovaquie", "🇸🇰"),
        )

        fun countryName(iso: String): String =
            EUROZONE_COUNTRIES[iso.lowercase()]?.first ?: iso.uppercase()

        fun countryFlag(iso: String): String =
            EUROZONE_COUNTRIES[iso.lowercase()]?.second ?: "🏳️"
    }
}
