package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "coin_prices",
    indices = [Index("eurio_id")],
)
data class CoinPriceEntity(
    @PrimaryKey(autoGenerate = true)
    @ColumnInfo(name = "id")
    val id: Long = 0,

    @ColumnInfo(name = "eurio_id")
    val eurioId: String,

    @ColumnInfo(name = "grade")
    val grade: String,

    @ColumnInfo(name = "p_low")
    val pLow: Int?,

    @ColumnInfo(name = "p_mid")
    val pMid: Int?,

    @ColumnInfo(name = "p_high")
    val pHigh: Int?,

    @ColumnInfo(name = "currency")
    val currency: String?,

    @ColumnInfo(name = "source")
    val source: String?,

    @ColumnInfo(name = "sampled_at")
    val sampledAt: String?,
)
