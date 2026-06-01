package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.dao.VaultDao
import com.musubi.eurio.data.local.entities.CoinInVaultEntity
import com.musubi.eurio.data.local.entities.VaultCoinWithCoin
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * One possessed coin in the user's vault, joined with display metadata.
 *
 * Post-D24 the key is `eurioId` (the coin_in_vault PK) — no more autogen
 * Long. [declaredCount] is the user-facing multiplicity badge: equals the
 * old `count` of `vault_entries` post-migration, and is bumped only via the
 * coffre UI (Phase 2 manual control, D14).
 */
data class VaultCoinItem(
    val eurioId: String,
    val coin: CoinViewData,
    val firstCapturedAt: Long,
    val declaredCount: Int,
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

    /**
     * Acte de possession (D24) — crée [CoinInVaultEntity] si absente. No-op
     * si la pièce est déjà possédée (declared_count inchangé per D14 ;
     * l'incrément manuel passera par la fiche coffre Phase 2).
     *
     * `captureId` peut être non-null quand l'archive vient de réussir et
     * que ce scan a produit un JPEG ; il devient alors la primary capture
     * de la nouvelle row. NULL en chemin sans capture (catalog browse,
     * fallback YUV échoué, manual_add Phase 2).
     */
    suspend fun confirmPossession(eurioId: String, captureId: String? = null)

    fun observeTotalCount(): Flow<Int>
    fun observeDistinctCoinCount(): Flow<Int>
    fun observeVaultCoins(filter: VaultFilter, sort: VaultSort): Flow<List<VaultCoinItem>>
    suspend fun removeCoin(eurioId: String)
    fun observeAvailableCountries(): Flow<List<String>>
}

class RoomVaultRepository(
    private val dao: VaultDao,
) : VaultRepository {

    override suspend fun containsCoin(eurioId: String): Boolean =
        dao.containsCoin(eurioId)

    override suspend fun confirmPossession(eurioId: String, captureId: String?) {
        if (dao.getVault(eurioId) != null) return  // D14 — no-op if already possessed
        dao.upsertVault(
            CoinInVaultEntity(
                eurioId = eurioId,
                firstCapturedAt = System.currentTimeMillis(),
                primaryCaptureId = captureId,
                declaredCount = 1,
            )
        )
        if (captureId != null) {
            dao.setPrimary(eurioId, captureId)
        }
    }

    override fun observeTotalCount(): Flow<Int> = dao.observeTotalCount()
    override fun observeDistinctCoinCount(): Flow<Int> = dao.observeDistinctCoinCount()

    override fun observeVaultCoins(
        filter: VaultFilter,
        sort: VaultSort,
    ): Flow<List<VaultCoinItem>> {
        return dao.observeAllWithCoin().map { rows ->
            val items = rows
                .filter { matchesFilter(it, filter) }
                .map { it.toItem() }
            sortItems(items, sort)
        }
    }

    override suspend fun removeCoin(eurioId: String) {
        dao.removeCoin(eurioId)
    }

    override fun observeAvailableCountries(): Flow<List<String>> =
        dao.observeAvailableCountries()

    private fun VaultCoinWithCoin.toItem(): VaultCoinItem {
        val coinEntity = coin
        val issueType = if (coinEntity.isCommemorative) "commemo" else "circulation"
        return VaultCoinItem(
            eurioId = vault.eurioId,
            coin = CoinViewData(
                eurioId = coinEntity.eurioId,
                nameFr = coinEntity.nameFr ?: coinEntity.nameEn ?: coinEntity.eurioId,
                country = coinEntity.country,
                year = coinEntity.year ?: 0,
                faceValueCents = coinEntity.faceValueCents,
                imageObverseUrl = obverseStorageUrl(coinEntity.eurioId),
                issueType = issueType,
                designDescription = coinEntity.designDescription,
            ),
            firstCapturedAt = vault.firstCapturedAt,
            declaredCount = vault.declaredCount,
        )
    }

    private fun matchesFilter(row: VaultCoinWithCoin, filter: VaultFilter): Boolean {
        val coin = row.coin
        if (filter.countries.isNotEmpty() && coin.country !in filter.countries) return false
        val issueType = if (coin.isCommemorative) "commemo" else "circulation"
        if (filter.issueTypes.isNotEmpty() && issueType !in filter.issueTypes) return false
        if (filter.faceValues.isNotEmpty() && coin.faceValueCents !in filter.faceValues) return false
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
            VaultSort.SCAN_DATE -> items.sortedByDescending { it.firstCapturedAt }
            VaultSort.YEAR -> items.sortedByDescending { it.coin.year }
        }
    }
}
