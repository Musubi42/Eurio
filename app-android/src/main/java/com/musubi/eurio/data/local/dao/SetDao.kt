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

    @Query("SELECT * FROM sets WHERE active = 1 ORDER BY display_order, name_fr")
    fun observeActive(): Flow<List<SetEntity>>

    @Query("SELECT * FROM sets WHERE id = :id LIMIT 1")
    suspend fun findById(id: String): SetEntity?

    @Query("DELETE FROM sets")
    suspend fun clearSets()

    @Query("DELETE FROM set_members")
    suspend fun clearMembers()
}
