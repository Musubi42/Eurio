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

    // Photo metadata — coin center & radius normalized to [0,1] in the source
    // Numista photo, used by the 3D coin viewer to align textures on the mesh
    // (cf. docs/coin-3d-viewer/technical-notes.md). Null when no measured photo
    // is available; the viewer falls back to (0.5, 0.5, 0.499).
    @ColumnInfo(name = "obverse_cx_uv")
    val obverseCxUv: Float? = null,
    @ColumnInfo(name = "obverse_cy_uv")
    val obverseCyUv: Float? = null,
    @ColumnInfo(name = "obverse_radius_uv")
    val obverseRadiusUv: Float? = null,
    @ColumnInfo(name = "reverse_cx_uv")
    val reverseCxUv: Float? = null,
    @ColumnInfo(name = "reverse_cy_uv")
    val reverseCyUv: Float? = null,
    @ColumnInfo(name = "reverse_radius_uv")
    val reverseRadiusUv: Float? = null,
)
