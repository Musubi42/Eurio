package com.musubi.eurio.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.musubi.eurio.data.local.entities.SetEntity
import com.musubi.eurio.data.local.entities.SetMemberEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface SetDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAllSets(sets: List<SetEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAllMembers(members: List<SetMemberEntity>)

    @Query("SELECT COUNT(*) FROM sets")
    suspend fun countSets(): Int

    @Query("SELECT COUNT(*) FROM set_members")
    suspend fun countMembers(): Int

    @Query("SELECT COUNT(*) FROM set_members WHERE set_id = :setId")
    suspend fun countMembersInSet(setId: String): Int

    @Query("SELECT set_id FROM set_members WHERE coin_eurio_id = :eurioId")
    suspend fun findSetIdsContainingCoin(eurioId: String): List<String>

    @Query("SELECT * FROM sets WHERE active = 1 ORDER BY display_order, name_fr")
    fun observeActive(): Flow<List<SetEntity>>

    @Query("SELECT * FROM sets WHERE id = :id LIMIT 1")
    suspend fun findById(id: String): SetEntity?

    @Query("DELETE FROM sets")
    suspend fun clearSets()

    @Query("DELETE FROM set_members")
    suspend fun clearMembers()

    // Phase 3 additions

    @Query(
        """
        SELECT sm.coin_eurio_id FROM set_members sm
        WHERE sm.set_id = :setId
        ORDER BY sm.position ASC, sm.coin_eurio_id ASC
        """
    )
    suspend fun getMemberEurioIds(setId: String): List<String>

    @Query(
        """
        SELECT sm.coin_eurio_id FROM set_members sm
        INNER JOIN vault_entries v ON v.coin_eurio_id = sm.coin_eurio_id
        WHERE sm.set_id = :setId
        GROUP BY sm.coin_eurio_id
        """
    )
    suspend fun getOwnedMemberEurioIds(setId: String): List<String>

    @Query("UPDATE sets SET completed_at = :completedAt WHERE id = :setId")
    suspend fun updateCompletedAt(setId: String, completedAt: Long?)

    @Query("SELECT DISTINCT s.category FROM sets s WHERE s.active = 1 ORDER BY s.category")
    fun observeActiveCategories(): Flow<List<String>>
}
