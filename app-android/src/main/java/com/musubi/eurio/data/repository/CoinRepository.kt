package com.musubi.eurio.data.repository

import com.musubi.eurio.data.local.dao.CoinDao
import com.musubi.eurio.data.local.entities.CoinEntity
import com.musubi.eurio.domain.IssueType

/**
 * UI-layer view of a coin. Stable DTO surface exposed by the repository to
 * features (scan, vault, coindetail) so they have zero knowledge of Room.
 */
data class CoinViewData(
    val eurioId: String,
    val nameFr: String,
    val country: String,
    val year: Int,
    val faceValueCents: Int,
    val imageObverseUrl: String?,
    val imageReverseUrl: String? = null,
    val issueType: String,
    val designDescription: String? = null,
    val obversePhotoMeta: PhotoMeta? = null,
    val reversePhotoMeta: PhotoMeta? = null,
)

// {cx_uv, cy_uv, radius_uv} — coin center & radius normalized to [0,1] in the
// source Numista photo. Consumed by the 3D coin viewer (cf.
// docs/coin-3d-viewer/technical-notes.md, section UV mapping XY → photo).
data class PhotoMeta(
    val cxUv: Float,
    val cyUv: Float,
    val radiusUv: Float,
)

interface CoinRepository {
    suspend fun findByEurioId(eurioId: String): CoinViewData?
    suspend fun resolveByClassifierName(className: String): CoinViewData?
    suspend fun findAllByFaceValue(faceValue: Double): List<CoinViewData>
}

class RoomCoinRepository(
    private val dao: CoinDao,
) : CoinRepository {

    override suspend fun findByEurioId(eurioId: String): CoinViewData? {
        return dao.findByEurioId(eurioId)?.toViewData()
    }

    override suspend fun findAllByFaceValue(faceValue: Double): List<CoinViewData> =
        dao.findAllByFaceValue(faceValue).map { it.toViewData() }

    override suspend fun resolveByClassifierName(className: String): CoinViewData? {
        dao.findByEurioId(className)?.let { return it.toViewData() }
        className.toIntOrNull()?.let { numistaId ->
            dao.findByNumistaId(numistaId)?.let { return it.toViewData() }
        }
        return null
    }

    private fun CoinEntity.toViewData(): CoinViewData = CoinViewData(
        eurioId = eurioId,
        nameFr = nameFr ?: nameEn ?: eurioId,
        country = country,
        year = year ?: 0,
        faceValueCents = ((faceValue ?: 0.0) * 100).toInt(),
        imageObverseUrl = imageObverseUrl,
        imageReverseUrl = imageReverseUrl,
        issueType = when (issueType) {
            IssueType.CIRCULATION, IssueType.STARTER_KIT -> "circulation"
            IssueType.COMMEMO_NATIONAL, IssueType.COMMEMO_COMMON -> "commemo"
            IssueType.BU_SET, IssueType.PROOF -> "circulation"
            null -> "circulation"
        },
        designDescription = designDescription,
        obversePhotoMeta = photoMetaFrom(obverseCxUv, obverseCyUv, obverseRadiusUv),
        reversePhotoMeta = photoMetaFrom(reverseCxUv, reverseCyUv, reverseRadiusUv),
    )

    private fun photoMetaFrom(cx: Float?, cy: Float?, r: Float?): PhotoMeta? =
        if (cx != null && cy != null && r != null) PhotoMeta(cx, cy, r) else null
}
