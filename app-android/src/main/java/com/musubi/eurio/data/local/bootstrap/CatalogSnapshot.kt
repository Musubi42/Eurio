package com.musubi.eurio.data.local.bootstrap

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// DTOs pour désérialiser catalog_snapshot.json packagé dans assets/.
// Le script ml/export_catalog_snapshot.py doit produire exactement ce format.

@Serializable
data class CatalogSnapshot(
    @SerialName("catalog_version") val catalogVersion: String,
    @SerialName("generated_at") val generatedAt: String,
    val coins: List<CoinDto>,
    @SerialName("coin_series") val coinSeries: List<CoinSeriesDto> = emptyList(),
    val sets: List<SetDto> = emptyList(),
    @SerialName("set_members") val setMembers: List<SetMemberDto> = emptyList(),
)

@Serializable
data class CoinDto(
    @SerialName("eurio_id") val eurioId: String,
    @SerialName("numista_id") val numistaId: Int? = null,
    val country: String,
    val year: Int? = null,
    @SerialName("face_value") val faceValue: Double? = null,
    @SerialName("issue_type") val issueType: String? = null,
    @SerialName("series_id") val seriesId: String? = null,
    @SerialName("name_fr") val nameFr: String? = null,
    @SerialName("name_en") val nameEn: String? = null,
    val name: String? = null,
    @SerialName("image_obverse_url") val imageObverseUrl: String? = null,
    @SerialName("image_reverse_url") val imageReverseUrl: String? = null,
    @SerialName("obverse_meta") val obverseMeta: PhotoMetaDto? = null,
    @SerialName("reverse_meta") val reverseMeta: PhotoMetaDto? = null,
    val mintage: Long? = null,
    @SerialName("is_withdrawn") val isWithdrawn: Boolean = false,
    @SerialName("withdrawal_reason") val withdrawalReason: String? = null,
    @SerialName("design_description") val designDescription: String? = null,
    @SerialName("theme_code") val themeCode: String? = null,
)

// {cx_uv, cy_uv, radius_uv} — coordonnées normalisées du centre & rayon de la
// pièce dans la photo Numista, mesurées par ml/measure_photo_meta.py et
// embarquées dans le snapshot. Consommées par le viewer 3D
// (cf. docs/coin-3d-viewer/technical-notes.md, section UV mapping XY → photo).
@Serializable
data class PhotoMetaDto(
    @SerialName("cx_uv") val cxUv: Float,
    @SerialName("cy_uv") val cyUv: Float,
    @SerialName("radius_uv") val radiusUv: Float,
)

@Serializable
data class CoinSeriesDto(
    val id: String,
    val country: String,
    val designation: String,
    @SerialName("designation_i18n") val designationI18n: Map<String, String>? = null,
    @SerialName("minting_started_at") val mintingStartedAt: String,
    @SerialName("minting_ended_at") val mintingEndedAt: String? = null,
    @SerialName("minting_end_reason") val mintingEndReason: String? = null,
    @SerialName("supersedes_series_id") val supersedesSeriesId: String? = null,
)

@Serializable
data class SetDto(
    val id: String,
    val kind: String,
    @SerialName("name_i18n") val nameI18n: Map<String, String>,
    @SerialName("description_i18n") val descriptionI18n: Map<String, String>? = null,
    val criteria: kotlinx.serialization.json.JsonElement? = null,
    @SerialName("param_key") val paramKey: String? = null,
    val reward: kotlinx.serialization.json.JsonElement? = null,
    @SerialName("display_order") val displayOrder: Int = 1000,
    val category: String,
    val icon: String? = null,
    @SerialName("expected_count") val expectedCount: Int? = null,
    val active: Boolean = true,
)

@Serializable
data class SetMemberDto(
    @SerialName("set_id") val setId: String,
    @SerialName("eurio_id") val eurioId: String,
    val position: Int? = null,
)
