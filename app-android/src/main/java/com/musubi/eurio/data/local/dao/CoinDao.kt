package com.musubi.eurio.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.musubi.eurio.data.local.entities.CoinEntity
import com.musubi.eurio.data.local.entities.CoinSeriesEntity
import kotlinx.coroutines.flow.Flow

@Dao
interface CoinDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAllCoins(coins: List<CoinEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAllSeries(series: List<CoinSeriesEntity>)

    @Query("SELECT COUNT(*) FROM coins")
    suspend fun countCoins(): Int

    @Query("SELECT COUNT(*) FROM coins")
    fun observeCoinCount(): Flow<Int>

    @Query("SELECT * FROM coins WHERE eurio_id = :eurioId LIMIT 1")
    suspend fun findByEurioId(eurioId: String): CoinEntity?

    @Query("SELECT * FROM coins WHERE numista_id = :numistaId LIMIT 1")
    suspend fun findByNumistaId(numistaId: Int): CoinEntity?

    @Query("SELECT * FROM coins ORDER BY country, year, face_value")
    fun observeAll(): Flow<List<CoinEntity>>

    @Query("DELETE FROM coins")
    suspend fun clearCoins()

    @Query("DELETE FROM coin_series")
    suspend fun clearSeries()
}
