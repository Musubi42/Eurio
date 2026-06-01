package com.musubi.eurio.data.local.entities

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "coins",
    indices = [
        Index("country"),
        Index("year"),
    ],
)
data class CoinEntity(
    @PrimaryKey
    @ColumnInfo(name = "eurio_id")
    val eurioId: String,

    @ColumnInfo(name = "country")
    val country: String,

    @ColumnInfo(name = "country_name")
    val countryName: String?,

    @ColumnInfo(name = "year")
    val year: Int?,

    @ColumnInfo(name = "face_value_cents")
    val faceValueCents: Int,

    @ColumnInfo(name = "is_commemorative")
    val isCommemorative: Boolean,

    @ColumnInfo(name = "collector_only")
    val collectorOnly: Boolean,

    @ColumnInfo(name = "theme")
    val theme: String?,

    @ColumnInfo(name = "design_description")
    val designDescription: String?,

    @ColumnInfo(name = "mintage")
    val mintage: Long?,

    @ColumnInfo(name = "diameter_mm")
    val diameterMm: Float?,

    @ColumnInfo(name = "weight_g")
    val weightG: Float?,

    @ColumnInfo(name = "thickness_mm")
    val thicknessMm: Float?,

    @ColumnInfo(name = "composition")
    val composition: String?,

    @ColumnInfo(name = "shape")
    val shape: String?,

    @ColumnInfo(name = "edge_lettering")
    val edgeLettering: String?,

    @ColumnInfo(name = "design_group_id")
    val designGroupId: String?,

    @ColumnInfo(name = "variant_kind")
    val variantKind: String,

    @ColumnInfo(name = "canonical_eurio_id")
    val canonicalEurioId: String?,

    @ColumnInfo(name = "shared_reverse_id")
    val sharedReverseId: String?,

    @ColumnInfo(name = "name_fr")
    val nameFr: String?,

    @ColumnInfo(name = "name_en")
    val nameEn: String?,

    @ColumnInfo(name = "desc_fr")
    val descFr: String?,

    @ColumnInfo(name = "desc_en")
    val descEn: String?,
)
