package com.musubi.eurio.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Upsert
import com.musubi.eurio.data.local.entities.CoinEntity
import com.musubi.eurio.data.local.entities.CoinSeriesEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface CoinDao {
    // @Upsert (insert-or-UPDATE-in-place), NOT @Insert(REPLACE): REPLACE deletes
    // the existing row before inserting, which fires coin_in_vault's
    // `ON DELETE CASCADE` FK and would wipe the user's vault on every catalog
    // refresh. Upsert updates columns in place — the eurio_id (referenced key)
    // is untouched, so no cascade ever fires. Never call clearCoins() on the
    // catalog-refresh path for the same reason.
    @Upsert
    suspend fun insertAllCoins(coins: List<CoinEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAllSeries(series: List<CoinSeriesEntity>)

    @Query("SELECT COUNT(*) FROM coins")
    suspend fun countCoins(): Int

    @Query("SELECT COUNT(*) FROM coins")
    fun observeCoinCount(): Flow<Int>

    @Query("SELECT * FROM coins WHERE eurio_id = :eurioId LIMIT 1")
    suspend fun findByEurioId(eurioId: String): CoinEntity?

    // Used by the debug carousel to cycle through every 2 € coin.
    // faceValueCents is passed as cents (e.g. 200 for 2 €).
    @Query("SELECT * FROM coins WHERE face_value_cents = :faceValueCents ORDER BY country, year, eurio_id")
    suspend fun findAllByFaceValueCents(faceValueCents: Int): List<CoinEntity>

    @Query("SELECT * FROM coins ORDER BY country, year, face_value_cents")
    fun observeAll(): Flow<List<CoinEntity>>

    @Query("DELETE FROM coins")
    suspend fun clearCoins()

    @Query("DELETE FROM coin_series")
    suspend fun clearSeries()
}
