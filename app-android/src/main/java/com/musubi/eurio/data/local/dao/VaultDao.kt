package com.musubi.eurio.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.musubi.eurio.data.local.entities.VaultEntryEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface VaultDao {
    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insert(entry: VaultEntryEntity): Long

    @Query("SELECT COUNT(*) > 0 FROM vault_entries WHERE coin_eurio_id = :eurioId")
    suspend fun containsCoin(eurioId: String): Boolean

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
}
