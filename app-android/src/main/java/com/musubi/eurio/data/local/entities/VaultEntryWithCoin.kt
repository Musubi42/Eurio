package com.musubi.eurio.data.local.entities

import androidx.room.Embedded
import androidx.room.Relation

/**
 * Room relation joining a [VaultEntryEntity] with its parent [CoinEntity].
 * Used by VaultDao queries that need coin metadata alongside vault entries.
 */
data class VaultEntryWithCoin(
    @Embedded val entry: VaultEntryEntity,
    @Relation(
        parentColumn = "coin_eurio_id",
        entityColumn = "eurio_id",
    )
    val coin: CoinEntity,
)
