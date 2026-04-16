package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.dao.CoinDao
import com.musubi.eurio.data.local.entities.CoinEntity
import com.musubi.eurio.domain.IssueType

/**
 * UI-layer view of a coin. Stable DTO surface exposed by the repository to
 * features (scan, vault, coindetail) so they have zero knowledge of Room.
 */
data class CoinViewData(
    val eurioId: String,
    val nameFr: String,
    val country: String,
    val year: Int,
    val faceValueCents: Int,
    val imageObverseUrl: String?,
    val issueType: String,
    val designDescription: String? = null,
)

interface CoinRepository {
    suspend fun findByEurioId(eurioId: String): CoinViewData?
    suspend fun resolveByClassifierName(className: String): CoinViewData?
}

class RoomCoinRepository(
    private val dao: CoinDao,
) : CoinRepository {

    override suspend fun findByEurioId(eurioId: String): CoinViewData? {
        return dao.findByEurioId(eurioId)?.toViewData()
    }

    override suspend fun resolveByClassifierName(className: String): CoinViewData? {
        dao.findByEurioId(className)?.let { return it.toViewData() }
        className.toIntOrNull()?.let { numistaId ->
            dao.findByNumistaId(numistaId)?.let { return it.toViewData() }
        }
        return null
    }

    private fun CoinEntity.toViewData(): CoinViewData = CoinViewData(
        eurioId = eurioId,
        nameFr = nameFr ?: nameEn ?: eurioId,
        country = country,
        year = year ?: 0,
        faceValueCents = ((faceValue ?: 0.0) * 100).toInt(),
        imageObverseUrl = imageObverseUrl,
        issueType = when (issueType) {
            IssueType.CIRCULATION, IssueType.STARTER_KIT -> "circulation"
            IssueType.COMMEMO_NATIONAL, IssueType.COMMEMO_COMMON -> "commemo"
            IssueType.BU_SET, IssueType.PROOF -> "circulation"
            null -> "circulation"
        },
        designDescription = designDescription,
    )
}
