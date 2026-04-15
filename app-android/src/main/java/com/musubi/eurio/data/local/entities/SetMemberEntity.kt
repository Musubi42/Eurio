package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index

@Entity(
    tableName = "set_members",
    primaryKeys = ["set_id", "coin_eurio_id"],
    foreignKeys = [
        ForeignKey(
            entity = SetEntity::class,
            parentColumns = ["id"],
            childColumns = ["set_id"],
            onDelete = ForeignKey.CASCADE,
        ),
        ForeignKey(
            entity = CoinEntity::class,
            parentColumns = ["eurio_id"],
            childColumns = ["coin_eurio_id"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index("coin_eurio_id")],
)
data class SetMemberEntity(
    @ColumnInfo(name = "set_id")
    val setId: String,

    @ColumnInfo(name = "coin_eurio_id")
    val coinEurioId: String,

    // Ordre d'affichage dans le set. Nullable car l'admin peut laisser
    // l'ordre libre (tri par défaut : pays/année). Utilisé principalement
    // sur les sets curated où l'ordre importe pour la narration.
    @ColumnInfo(name = "position")
    val position: Int?,
)
