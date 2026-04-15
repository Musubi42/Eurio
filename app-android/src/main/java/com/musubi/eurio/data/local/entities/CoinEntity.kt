package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey
import com.musubi.eurio.domain.IssueType

@Entity(
    tableName = "coins",
    indices = [
        Index("country"),
        Index("year"),
        Index("series_id"),
        Index("issue_type"),
    ],
)
data class CoinEntity(
    @PrimaryKey
    @ColumnInfo(name = "eurio_id")
    val eurioId: String,

    @ColumnInfo(name = "numista_id")
    val numistaId: Int?,

    @ColumnInfo(name = "country")
    val country: String,

    @ColumnInfo(name = "year")
    val year: Int?,

    @ColumnInfo(name = "face_value")
    val faceValue: Double?,

    @ColumnInfo(name = "issue_type")
    val issueType: IssueType?,

    @ColumnInfo(name = "series_id")
    val seriesId: String?,

    @ColumnInfo(name = "name_fr")
    val nameFr: String?,

    @ColumnInfo(name = "name_en")
    val nameEn: String?,

    @ColumnInfo(name = "image_obverse_url")
    val imageObverseUrl: String?,

    @ColumnInfo(name = "image_reverse_url")
    val imageReverseUrl: String?,

    @ColumnInfo(name = "mintage")
    val mintage: Long?,

    @ColumnInfo(name = "is_withdrawn")
    val isWithdrawn: Boolean = false,

    @ColumnInfo(name = "withdrawal_reason")
    val withdrawalReason: String? = null,

    @ColumnInfo(name = "design_description")
    val designDescription: String? = null,

    @ColumnInfo(name = "theme_code")
    val themeCode: String? = null,
)
