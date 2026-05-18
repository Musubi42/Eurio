package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * One row per coin the user owns (D24 — possession, distinct from journal).
 *
 * Created by [com.musubi.eurio.data.repository.VaultRepository.confirmPossession]
 * when the user taps "Ajouter au coffre" — *not* on archive auto. Captures
 * (`coin_captures`) accumulate independently of this table; promotion of a
 * capture to "primary" is the only link back ([primaryCaptureId]).
 *
 * `primaryCaptureId` is nullable because:
 *  - Post-migration v2→v3 (D23) we don't have historical JPEGs, so all
 *    backfilled rows start with NULL.
 *  - Future manual-add flows may create a vault entry before any photo.
 *
 * `declaredCount` is user-facing only (D14) — the journal aspect of the old
 * `vault_entries` table is preserved as the count of scan events at migration
 * time, but post-D24 the count is no longer auto-incremented on re-scan.
 * Subsequent bumps happen via the coffre UI (Phase 2).
 */
@Entity(
    tableName = "coin_in_vault",
    foreignKeys = [
        ForeignKey(
            entity = CoinEntity::class,
            parentColumns = ["eurio_id"],
            childColumns = ["eurio_id"],
            onDelete = ForeignKey.CASCADE,
        ),
        ForeignKey(
            entity = CoinCaptureEntity::class,
            parentColumns = ["capture_id"],
            childColumns = ["primary_capture_id"],
            onDelete = ForeignKey.NO_ACTION,
        ),
    ],
    indices = [
        Index("primary_capture_id"),
        Index("first_captured_at"),
    ],
)
data class CoinInVaultEntity(
    @PrimaryKey
    @ColumnInfo(name = "eurio_id")
    val eurioId: String,

    @ColumnInfo(name = "first_captured_at")
    val firstCapturedAt: Long,

    @ColumnInfo(name = "primary_capture_id")
    val primaryCaptureId: String? = null,

    @ColumnInfo(name = "declared_count")
    val declaredCount: Int = 1,

    @ColumnInfo(name = "notes")
    val notes: String? = null,

    // Sync placeholders for the marketplace phase (Référentiel V2 §4). Nullable
    // so they cost nothing in v1 and we don't need a v3→v4 migration just to
    // add them. Wired by future upload workers, never written by app code today.
    @ColumnInfo(name = "uploaded_at")
    val uploadedAt: Long? = null,

    @ColumnInfo(name = "remote_vault_id")
    val remoteVaultId: String? = null,
)
