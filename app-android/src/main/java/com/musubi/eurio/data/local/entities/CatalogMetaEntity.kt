package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.PrimaryKey

// Store key/value léger pour méta-données applicatives :
// catalog_version, bootstrap_at, last_sync_at, streak_count, streak_last_day, …
@Entity(tableName = "catalog_meta")
data class CatalogMetaEntity(
    @PrimaryKey
    @ColumnInfo(name = "key")
    val key: String,

    @ColumnInfo(name = "value")
    val value: String,
) {
    companion object {
        const val KEY_CATALOG_VERSION = "catalog_version"
        const val KEY_BOOTSTRAP_AT = "bootstrap_at"
        const val KEY_LAST_SYNC_AT = "last_sync_at"
        const val KEY_STREAK_COUNT = "streak_count"
        const val KEY_STREAK_LAST_DAY = "streak_last_day"
        const val KEY_STREAK_GRACE_USED = "streak_grace_used"
        const val KEY_STREAK_BEST = "streak_best"
    }
}
