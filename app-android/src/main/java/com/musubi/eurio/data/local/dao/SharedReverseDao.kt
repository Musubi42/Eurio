package com.musubi.eurio.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.musubi.eurio.data.local.entities.SharedReverseEntity

@Dao
interface SharedReverseDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(rows: List<SharedReverseEntity>)

    @Query("SELECT * FROM shared_reverse WHERE id = :id LIMIT 1")
    suspend fun findById(id: String): SharedReverseEntity?

    @Query("DELETE FROM shared_reverse")
    suspend fun clearAll()
}
