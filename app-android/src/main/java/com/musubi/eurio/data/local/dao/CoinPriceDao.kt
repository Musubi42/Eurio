package com.musubi.eurio.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.musubi.eurio.data.local.entities.CoinPriceEntity

@Dao
interface CoinPriceDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(prices: List<CoinPriceEntity>)

    @Query("SELECT * FROM coin_prices WHERE eurio_id = :eurioId")
    suspend fun findByEurioId(eurioId: String): List<CoinPriceEntity>

    @Query("DELETE FROM coin_prices")
    suspend fun clearAll()
}
