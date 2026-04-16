package com.musubi.eurio.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import com.musubi.eurio.data.local.entities.VaultEntryEntity
import com.musubi.eurio.data.local.entities.VaultEntryWithCoin
import kotlinx.coroutines.flow.Flow

@Dao
interface VaultDao {
    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insert(entry: VaultEntryEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(entries: List<VaultEntryEntity>)

    @Query("SELECT COUNT(*) > 0 FROM vault_entries WHERE coin_eurio_id = :eurioId")
    suspend fun containsCoin(eurioId: String): Boolean

    @Query(
        """
        SELECT COUNT(DISTINCT v.coin_eurio_id)
        FROM vault_entries v
        INNER JOIN set_members sm ON sm.coin_eurio_id = v.coin_eurio_id
        WHERE sm.set_id = :setId
        """
    )
    suspend fun countOwnedInSet(setId: String): Int

    @Query("SELECT COUNT(*) FROM vault_entries")
    fun observeTotalCount(): Flow<Int>

    @Query("SELECT COUNT(DISTINCT coin_eurio_id) FROM vault_entries")
    fun observeDistinctCoinCount(): Flow<Int>

    @Query("SELECT * FROM vault_entries ORDER BY scanned_at DESC")
    fun observeAll(): Flow<List<VaultEntryEntity>>

    @Query("DELETE FROM vault_entries WHERE id = :entryId")
    suspend fun deleteById(entryId: Long)

    @Query("DELETE FROM vault_entries")
    suspend fun clearAll()

    @Transaction
    @Query("SELECT * FROM vault_entries ORDER BY scanned_at DESC")
    fun observeAllWithCoin(): Flow<List<VaultEntryWithCoin>>

    @Query("SELECT DISTINCT c.country FROM vault_entries v INNER JOIN coins c ON v.coin_eurio_id = c.eurio_id ORDER BY c.country")
    fun observeAvailableCountries(): Flow<List<String>>

    @Query("SELECT COUNT(*) FROM vault_entries WHERE coin_eurio_id = :eurioId")
    fun countEntriesForCoin(eurioId: String): Int
}
