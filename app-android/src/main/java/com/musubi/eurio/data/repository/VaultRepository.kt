package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.dao.VaultDao
import com.musubi.eurio.data.local.entities.VaultEntryEntity
import com.musubi.eurio.data.local.entities.VaultEntryWithCoin
import com.musubi.eurio.domain.IssueType
import com.musubi.eurio.domain.ScanSource
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * Combined vault entry + coin info for grid/list display.
 * Deduped by eurioId — [count] reflects how many times the coin was scanned.
 */
data class VaultCoinItem(
    val entryId: Long,
    val coin: CoinViewData,
    val scannedAt: Long,
    val confidence: Float?,
    val count: Int,
)

data class VaultFilter(
    val countries: Set<String> = emptySet(),
    val issueTypes: Set<String> = emptySet(),
    val faceValues: Set<Int> = emptySet(),
    val yearRange: IntRange? = null,
    val searchQuery: String = "",
)

enum class VaultSort { COUNTRY, FACE_VALUE, SCAN_DATE, YEAR }

interface VaultRepository {
    suspend fun containsCoin(eurioId: String): Boolean
    suspend fun addCoin(eurioId: String, confidence: Float): Long
    fun observeTotalCount(): Flow<Int>
    fun observeDistinctCoinCount(): Flow<Int>
    fun observeVaultCoins(filter: VaultFilter, sort: VaultSort): Flow<List<VaultCoinItem>>
    suspend fun removeEntry(entryId: Long)
    fun observeAvailableCountries(): Flow<List<String>>
}

class RoomVaultRepository(
    private val dao: VaultDao,
) : VaultRepository {

    override suspend fun containsCoin(eurioId: String): Boolean =
        dao.containsCoin(eurioId)

    override suspend fun addCoin(eurioId: String, confidence: Float): Long {
        val entry = VaultEntryEntity(
            coinEurioId = eurioId,
            scannedAt = System.currentTimeMillis(),
            source = ScanSource.SCAN,
            confidence = confidence,
        )
        return dao.insert(entry)
    }

    override fun observeTotalCount(): Flow<Int> = dao.observeTotalCount()
    override fun observeDistinctCoinCount(): Flow<Int> = dao.observeDistinctCoinCount()

    override fun observeVaultCoins(
        filter: VaultFilter,
        sort: VaultSort,
    ): Flow<List<VaultCoinItem>> {
        return dao.observeAllWithCoin().map { entries ->
            val filtered = entries.filter { matchesFilter(it, filter) }
            val grouped = filtered.groupBy { it.coin.eurioId }
            val items = grouped.map { (_, group) ->
                val representative = group.maxBy { it.entry.scannedAt }
                val coin = representative.coin
                VaultCoinItem(
                    entryId = representative.entry.id,
                    coin = CoinViewData(
                        eurioId = coin.eurioId,
                        nameFr = coin.nameFr ?: coin.nameEn ?: coin.eurioId,
                        country = coin.country,
                        year = coin.year ?: 0,
                        faceValueCents = ((coin.faceValue ?: 0.0) * 100).toInt(),
                        imageObverseUrl = coin.imageObverseUrl,
                        issueType = mapIssueType(coin.issueType),
                        designDescription = coin.designDescription,
                    ),
                    scannedAt = representative.entry.scannedAt,
                    confidence = representative.entry.confidence,
                    count = group.size,
                )
            }
            sortItems(items, sort)
        }
    }

    override suspend fun removeEntry(entryId: Long) {
        dao.deleteById(entryId)
    }

    override fun observeAvailableCountries(): Flow<List<String>> =
        dao.observeAvailableCountries()

    private fun matchesFilter(ewc: VaultEntryWithCoin, filter: VaultFilter): Boolean {
        val coin = ewc.coin
        if (filter.countries.isNotEmpty() && coin.country !in filter.countries) return false
        if (filter.issueTypes.isNotEmpty() && mapIssueType(coin.issueType) !in filter.issueTypes) return false
        if (filter.faceValues.isNotEmpty()) {
            val cents = ((coin.faceValue ?: 0.0) * 100).toInt()
            if (cents !in filter.faceValues) return false
        }
        if (filter.yearRange != null) {
            val year = coin.year ?: 0
            if (year !in filter.yearRange) return false
        }
        if (filter.searchQuery.isNotBlank()) {
            val q = filter.searchQuery.lowercase()
            val matches = listOfNotNull(
                coin.nameFr, coin.nameEn, coin.country,
                coin.year?.toString(),
            ).any { it.lowercase().contains(q) }
            if (!matches) return false
        }
        return true
    }

    private fun sortItems(items: List<VaultCoinItem>, sort: VaultSort): List<VaultCoinItem> {
        return when (sort) {
            VaultSort.COUNTRY -> items.sortedWith(
                compareBy<VaultCoinItem> { it.coin.country }
                    .thenBy { it.coin.year }
                    .thenBy { it.coin.faceValueCents }
            )
            VaultSort.FACE_VALUE -> items.sortedByDescending { it.coin.faceValueCents }
            VaultSort.SCAN_DATE -> items.sortedByDescending { it.scannedAt }
            VaultSort.YEAR -> items.sortedByDescending { it.coin.year }
        }
    }

    private fun mapIssueType(type: IssueType?): String = when (type) {
        IssueType.CIRCULATION, IssueType.STARTER_KIT -> "circulation"
        IssueType.COMMEMO_NATIONAL, IssueType.COMMEMO_COMMON -> "commemo"
        IssueType.BU_SET, IssueType.PROOF -> "circulation"
        null -> "circulation"
    }
}
