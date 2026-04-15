package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "coin_series",
    indices = [Index("country")],
)
data class CoinSeriesEntity(
    @PrimaryKey
    @ColumnInfo(name = "id")
    val id: String,

    @ColumnInfo(name = "country")
    val country: String,

    @ColumnInfo(name = "designation_fr")
    val designationFr: String,

    @ColumnInfo(name = "designation_en")
    val designationEn: String?,

    @ColumnInfo(name = "minting_started_at")
    val mintingStartedAt: String,

    @ColumnInfo(name = "minting_ended_at")
    val mintingEndedAt: String?,

    @ColumnInfo(name = "minting_end_reason")
    val mintingEndReason: String?,

    @ColumnInfo(name = "supersedes_series_id")
    val supersedesSeriesId: String?,
)
