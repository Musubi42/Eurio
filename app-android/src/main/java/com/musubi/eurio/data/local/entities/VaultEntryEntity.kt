package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey
import com.musubi.eurio.domain.ScanSource

@Entity(
    tableName = "vault_entries",
    foreignKeys = [
        ForeignKey(
            entity = CoinEntity::class,
            parentColumns = ["eurio_id"],
            childColumns = ["coin_eurio_id"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [
        Index("coin_eurio_id"),
        Index("scanned_at"),
    ],
)
data class VaultEntryEntity(
    @PrimaryKey(autoGenerate = true)
    @ColumnInfo(name = "id")
    val id: Long = 0,

    @ColumnInfo(name = "coin_eurio_id")
    val coinEurioId: String,

    @ColumnInfo(name = "scanned_at")
    val scannedAt: Long,

    @ColumnInfo(name = "source")
    val source: ScanSource,

    @ColumnInfo(name = "confidence")
    val confidence: Float?,

    @ColumnInfo(name = "notes")
    val notes: String? = null,
)
