package com.musubi.eurio.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.musubi.eurio.data.local.entities.CatalogMetaEntity

@Dao
interface MetaDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entry: CatalogMetaEntity)

    @Query("SELECT value FROM catalog_meta WHERE `key` = :key LIMIT 1")
    suspend fun getRaw(key: String): String?

    suspend fun getString(key: String): String? = getRaw(key)

    suspend fun putString(key: String, value: String) =
        upsert(CatalogMetaEntity(key, value))

    suspend fun getLong(key: String): Long? = getRaw(key)?.toLongOrNull()

    suspend fun putLong(key: String, value: Long) =
        upsert(CatalogMetaEntity(key, value.toString()))

    suspend fun getInt(key: String): Int? = getRaw(key)?.toIntOrNull()

    suspend fun putInt(key: String, value: Int) =
        upsert(CatalogMetaEntity(key, value.toString()))

    suspend fun getBoolean(key: String): Boolean? = getRaw(key)?.toBooleanStrictOrNull()

    suspend fun putBoolean(key: String, value: Boolean) =
        upsert(CatalogMetaEntity(key, value.toString()))
}
