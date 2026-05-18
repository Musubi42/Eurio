package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Journal entry — one row per JPEG archived by the best-frame pipeline
 * (D13/D24). Distinct from [CoinInVaultEntity]: archives can be orphan
 * (no possession row) when the user dismisses the AcceptedCard without
 * tapping "Ajouter au coffre".
 *
 * `captureMetadataJson` carries the full pipeline state at capture time
 * (FrameScore breakdown, trigger params, lock result, ArcFace top-3,
 * device info, …) so chunk-7 bench tools can replay the run without
 * needing the live model.
 *
 * `isPrimary` is mutated by [com.musubi.eurio.data.local.dao.VaultDao.setPrimary]
 * — exactly one capture per `eurioId` is primary at a time. The constraint is
 * enforced by `VaultDao.promotePrimary` (transactional), not by a DB-level
 * partial unique index (sqlite does not expose them via Room).
 */
@Entity(
    tableName = "coin_captures",
    foreignKeys = [
        ForeignKey(
            entity = CoinEntity::class,
            parentColumns = ["eurio_id"],
            childColumns = ["eurio_id"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [
        Index("eurio_id"),
        Index(value = ["eurio_id", "is_primary"]),
    ],
)
data class CoinCaptureEntity(
    @PrimaryKey
    @ColumnInfo(name = "capture_id")
    val captureId: String,

    @ColumnInfo(name = "eurio_id")
    val eurioId: String,

    @ColumnInfo(name = "captured_at")
    val capturedAt: Long,

    @ColumnInfo(name = "image_filename")
    val imageFilename: String,

    @ColumnInfo(name = "quality_score")
    val qualityScore: Float,

    @ColumnInfo(name = "is_primary")
    val isPrimary: Boolean,

    @ColumnInfo(name = "capture_metadata_json")
    val captureMetadataJson: String,

    @ColumnInfo(name = "low_quality_flag")
    val lowQualityFlag: Boolean = false,

    // Marketplace sync placeholder (P8 vision.md). NULL until the future
    // upload worker pushes the file to remote storage.
    @ColumnInfo(name = "uploaded_at")
    val uploadedAt: Long? = null,
)
