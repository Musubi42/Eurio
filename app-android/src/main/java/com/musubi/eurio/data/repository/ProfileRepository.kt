package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.dao.CoinDao
import com.musubi.eurio.data.local.dao.MetaDao
import com.musubi.eurio.data.local.dao.VaultDao
import com.musubi.eurio.domain.AppEvent
import com.musubi.eurio.domain.Grade
import com.musubi.eurio.domain.badges.BADGE_DEFINITIONS
import com.musubi.eurio.domain.badges.BadgeDefinition
import com.musubi.eurio.domain.badges.VaultSnapshot
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine

data class BadgeState(
    val definition: BadgeDefinition,
    val unlocked: Boolean,
    val unlockedAt: Long? = null,
    val progressCurrent: Int? = null,
    val progressTarget: Int? = null,
)

data class ProfileState(
    val grade: Grade,
    val nextGrade: Grade?,
    val gradeProgressPercent: Float,
    val coinCount: Int,
    val distinctCoinCount: Int,
    val countryCount: Int,
    val completedSets: Int,
    val totalFaceValueCents: Long,
    val currentStreak: Int,
    val bestStreak: Int,
    val badges: List<BadgeState>,
)

interface ProfileRepository {
    fun observeProfileState(): Flow<ProfileState>
}

class RoomProfileRepository(
    private val vaultDao: VaultDao,
    private val coinDao: CoinDao,
    private val metaDao: MetaDao,
    private val setRepository: SetRepository,
    private val onAppEvent: ((AppEvent) -> Unit)? = null,
) : ProfileRepository {

    override fun observeProfileState(): Flow<ProfileState> {
        return combine(
            vaultDao.observeTotalCount(),
            vaultDao.observeDistinctCoinCount(),
            vaultDao.observeAllWithCoin(),
            setRepository.observeAllWithProgress(),
        ) { totalCount, distinctCount, entriesWithCoin, sets ->
            val countries = entriesWithCoin.map { it.coin.country }.distinct()
            val completedSets = sets.count { it.isComplete }
            val totalCents = entriesWithCoin.sumOf {
                ((it.coin.faceValue ?: 0.0) * 100).toLong()
            }

            val currentStreak = metaDao.getInt(KEY_STREAK_COUNT) ?: 0
            val bestStreak = metaDao.getInt(KEY_STREAK_BEST) ?: 0

            val grade = Grade.forCoinCount(distinctCount)
            val next = Grade.nextGrade(grade)
            val gradeProgress = if (next != null) {
                val range = next.threshold - grade.threshold
                if (range > 0) (distinctCount - grade.threshold).toFloat() / range
                else 1f
            } else 1f

            val snapshot = VaultSnapshot(
                totalCoins = totalCount,
                distinctCoins = distinctCount,
                countryCount = countries.size,
                completedSets = completedSets,
                bestStreak = bestStreak,
                currentStreak = currentStreak,
            )

            val unlockedKeys = BADGE_DEFINITIONS.map { it.id }.associateWith {
                metaDao.getLong("badge_${it}_unlocked_at")
            }

            val badges = BADGE_DEFINITIONS.map { def ->
                val wasUnlocked = unlockedKeys[def.id] != null
                val isNowUnlocked = def.predicate(snapshot)
                if (isNowUnlocked && !wasUnlocked) {
                    metaDao.putLong("badge_${def.id}_unlocked_at", System.currentTimeMillis())
                    onAppEvent?.invoke(AppEvent.BadgeUnlocked(def.nameFr, def.icon))
                }
                val progress = def.progressExtractor?.invoke(snapshot)
                BadgeState(
                    definition = def,
                    unlocked = isNowUnlocked || wasUnlocked,
                    unlockedAt = unlockedKeys[def.id]
                        ?: if (isNowUnlocked) System.currentTimeMillis() else null,
                    progressCurrent = progress?.first,
                    progressTarget = progress?.second,
                )
            }

            ProfileState(
                grade = grade,
                nextGrade = next,
                gradeProgressPercent = gradeProgress,
                coinCount = totalCount,
                distinctCoinCount = distinctCount,
                countryCount = countries.size,
                completedSets = completedSets,
                totalFaceValueCents = totalCents,
                currentStreak = currentStreak,
                bestStreak = bestStreak,
                badges = badges,
            )
        }
    }

    companion object {
        private const val KEY_STREAK_COUNT = "streak_count"
        private const val KEY_STREAK_BEST = "streak_best"
    }
}
