package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.dao.CoinDao
import com.musubi.eurio.data.local.dao.SetDao
import com.musubi.eurio.data.local.dao.VaultDao
import com.musubi.eurio.data.local.entities.SetEntity
import com.musubi.eurio.domain.IssueType
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine

/**
 * Progress view of a set — owned count vs total members.
 */
data class SetWithProgress(
    val id: String,
    val nameFr: String,
    val owned: Int,
    val total: Int,
    val category: String = "",
    val kind: String = "",
    val descriptionFr: String? = null,
    val displayOrder: Int = 1000,
    val completedAt: Long? = null,
    val rewardJson: String? = null,
) {
    val isComplete: Boolean get() = total > 0 && owned >= total
    val percent: Float get() = if (total > 0) owned.toFloat() / total else 0f
}

/**
 * Event payload emitted when a set transitions from incomplete to complete.
 */
data class SetCompletion(
    val setId: String,
    val nameFr: String,
    val completedAt: Long,
)

/**
 * Coin slot in a set detail planche — either owned or missing.
 */
data class SetCoinSlot(
    val eurioId: String,
    val nameFr: String,
    val country: String,
    val year: Int,
    val faceValueCents: Int,
    val imageObverseUrl: String?,
    val issueType: String,
    val owned: Boolean,
)

interface SetRepository {
    suspend fun findSetsContaining(eurioId: String): List<SetWithProgress>
    suspend fun checkCompletion(setId: String): SetCompletion?
    fun observeAllWithProgress(): Flow<List<SetWithProgress>>
    suspend fun getSetDetail(setId: String): SetWithProgress?
    suspend fun getSetSlots(setId: String): List<SetCoinSlot>
    suspend fun markCompleted(setId: String, completedAt: Long)
}

class RoomSetRepository(
    private val setDao: SetDao,
    private val vaultDao: VaultDao,
    private val coinDao: CoinDao? = null,
) : SetRepository {

    override suspend fun findSetsContaining(eurioId: String): List<SetWithProgress> {
        val setIds = setDao.findSetIdsContainingCoin(eurioId)
        return setIds.mapNotNull { setId ->
            val set = setDao.findById(setId) ?: return@mapNotNull null
            val total = setDao.countMembersInSet(setId)
            val owned = vaultDao.countOwnedInSet(setId)
            set.toWithProgress(owned, total)
        }
    }

    override suspend fun checkCompletion(setId: String): SetCompletion? {
        val set = setDao.findById(setId) ?: return null
        val total = setDao.countMembersInSet(setId)
        if (total == 0) return null
        val owned = vaultDao.countOwnedInSet(setId)
        if (owned < total) return null
        return SetCompletion(
            setId = set.id,
            nameFr = set.nameFr,
            completedAt = System.currentTimeMillis(),
        )
    }

    override fun observeAllWithProgress(): Flow<List<SetWithProgress>> {
        return combine(
            setDao.observeActive(),
            vaultDao.observeTotalCount(), // trigger recompute on vault changes
        ) { sets, _ ->
            sets.map { set ->
                val total = setDao.countMembersInSet(set.id)
                val owned = vaultDao.countOwnedInSet(set.id)
                set.toWithProgress(owned, total)
            }
        }
    }

    override suspend fun getSetDetail(setId: String): SetWithProgress? {
        val set = setDao.findById(setId) ?: return null
        val total = setDao.countMembersInSet(setId)
        val owned = vaultDao.countOwnedInSet(setId)
        return set.toWithProgress(owned, total)
    }

    override suspend fun getSetSlots(setId: String): List<SetCoinSlot> {
        val dao = coinDao ?: return emptyList()
        val memberIds = setDao.getMemberEurioIds(setId)
        val ownedIds = setDao.getOwnedMemberEurioIds(setId).toSet()
        return memberIds.mapNotNull { eurioId ->
            val coin = dao.findByEurioId(eurioId) ?: return@mapNotNull null
            SetCoinSlot(
                eurioId = coin.eurioId,
                nameFr = coin.nameFr ?: coin.nameEn ?: coin.eurioId,
                country = coin.country,
                year = coin.year ?: 0,
                faceValueCents = ((coin.faceValue ?: 0.0) * 100).toInt(),
                imageObverseUrl = coin.imageObverseUrl,
                issueType = when (coin.issueType) {
                    IssueType.CIRCULATION, IssueType.STARTER_KIT -> "circulation"
                    IssueType.COMMEMO_NATIONAL, IssueType.COMMEMO_COMMON -> "commemo"
                    IssueType.BU_SET, IssueType.PROOF -> "circulation"
                    null -> "circulation"
                },
                owned = eurioId in ownedIds,
            )
        }
    }

    override suspend fun markCompleted(setId: String, completedAt: Long) {
        setDao.updateCompletedAt(setId, completedAt)
    }

    private fun SetEntity.toWithProgress(owned: Int, total: Int) = SetWithProgress(
        id = id,
        nameFr = nameFr,
        owned = owned,
        total = total,
        category = category,
        kind = kind.wireValue,
        descriptionFr = descriptionFr,
        displayOrder = displayOrder,
        completedAt = completedAt,
        rewardJson = rewardJson,
    )
}
