package com.musubi.eurio.data.local.entities

import androidx.room.Embedded
import androidx.room.Relation

/**
 * Room relation joining a [CoinInVaultEntity] row with its parent [CoinEntity].
 * Replaces the pre-D24 `VaultEntryWithCoin` — one row per possessed coin.
 */
data class VaultCoinWithCoin(
    @Embedded val vault: CoinInVaultEntity,
    @Relation(
        parentColumn = "eurio_id",
        entityColumn = "eurio_id",
    )
    val coin: CoinEntity,
)
