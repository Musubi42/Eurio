package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.dao.MetaDao
import com.musubi.eurio.data.local.entities.CatalogMetaEntity
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/**
 * Daily scan streak, persisted via the [CatalogMetaEntity] key-value store.
 *
 * The rule (Phase 1 v1 — see phase-1-scan.md §Streak logic):
 *   - first accepted scan of the day → increment streak
 *   - subsequent scans same day → no-op
 *   - one-day grace period : if the user missed exactly one day AND hasn't
 *     already used the grace window, the next scan still increments the
 *     streak (and marks grace used)
 *   - beyond that → reset to 1
 *
 * The in-memory [currentStreak] is the single source of truth for the top bar.
 * Room is the persistence backing store only. [initializeFromDb] must be
 * called once at app startup to hydrate the in-memory state.
 */
interface StreakRepository {
    val currentStreak: StateFlow<Int>
    suspend fun onScanAccepted(): Int
    suspend fun initializeFromDb()
}

class MetaStreakRepository(
    private val metaDao: MetaDao,
) : StreakRepository {

    private val _currentStreak = MutableStateFlow(0)
    override val currentStreak: StateFlow<Int> = _currentStreak.asStateFlow()

    private val mutex = Mutex()

    override suspend fun initializeFromDb() {
        val count = metaDao.getInt(CatalogMetaEntity.KEY_STREAK_COUNT) ?: 0
        _currentStreak.value = count
    }

    override suspend fun onScanAccepted(): Int = mutex.withLock {
        val today = LocalDate.now()
        val lastDayStr = metaDao.getString(CatalogMetaEntity.KEY_STREAK_LAST_DAY)
        val lastDay = lastDayStr?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
        val graceUsed = metaDao.getBoolean(CatalogMetaEntity.KEY_STREAK_GRACE_USED) ?: false
        val currentCount = metaDao.getInt(CatalogMetaEntity.KEY_STREAK_COUNT) ?: 0

        val (newCount, newGraceUsed) = when {
            lastDay == null -> 1 to false
            lastDay == today -> return@withLock currentCount.also { _currentStreak.value = it }
            lastDay.plusDays(1) == today -> (currentCount + 1) to false
            lastDay.plusDays(2) == today && !graceUsed -> (currentCount + 1) to true
            ChronoUnit.DAYS.between(lastDay, today) >= 2 -> 1 to false
            else -> 1 to false
        }

        metaDao.putInt(CatalogMetaEntity.KEY_STREAK_COUNT, newCount)
        metaDao.putString(CatalogMetaEntity.KEY_STREAK_LAST_DAY, today.toString())
        metaDao.putBoolean(CatalogMetaEntity.KEY_STREAK_GRACE_USED, newGraceUsed)

        val best = metaDao.getInt(CatalogMetaEntity.KEY_STREAK_BEST) ?: 0
        if (newCount > best) {
            metaDao.putInt(CatalogMetaEntity.KEY_STREAK_BEST, newCount)
        }

        _currentStreak.value = newCount
        newCount
    }
}
