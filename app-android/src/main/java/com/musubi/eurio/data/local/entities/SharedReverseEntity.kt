package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "shared_reverse")
data class SharedReverseEntity(
    @PrimaryKey
    @ColumnInfo(name = "id")
    val id: String,

    @ColumnInfo(name = "label")
    val label: String?,

    @ColumnInfo(name = "asset_name")
    val assetName: String?,

    @ColumnInfo(name = "map_version")
    val mapVersion: Int?,
)
