package com.musubi.eurio.data.repository

import com.musubi.eurio.BuildConfig
import com.musubi.eurio.data.local.dao.CoinDao
import com.musubi.eurio.data.local.dao.CoinPriceDao
import com.musubi.eurio.data.local.dao.SharedReverseDao
import com.musubi.eurio.data.local.entities.CoinEntity

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
// source photo. Consumed by the 3D coin viewer (cf.
// docs/coin-3d-viewer/technical-notes.md, section UV mapping XY → photo).
// PhotoMeta is kept for API compatibility with the 3D viewer; all fields are
// null since the V2 catalog relies on the viewer's built-in (0.5, 0.5, 0.499)
// fallback.
data class PhotoMeta(
    val cxUv: Float,
    val cyUv: Float,
    val radiusUv: Float,
)

interface CoinRepository {
    suspend fun findByEurioId(eurioId: String): CoinViewData?
    suspend fun resolveByClassifierName(className: String): CoinViewData?
    suspend fun findAllByFaceValue(faceValue: Double): List<CoinViewData>

    /**
     * Marché d'une pièce dérivé des cotes réelles (`coin_prices`), ou `null`
     * si pas de cote exploitable (circulation à la faciale). Cf. [CoinMarket].
     */
    suspend fun findMarket(eurioId: String, faceValueCents: Int): CoinMarket?
}

class RoomCoinRepository(
    private val dao: CoinDao,
    private val sharedReverseDao: SharedReverseDao,
    private val priceDao: CoinPriceDao,
) : CoinRepository {

    // Cached asset_name lookup for shared reverses — tiny table (2 rows),
    // populated once on first access. Thread-safe via @Volatile + double-check.
    @Volatile
    private var reverseAssetCache: Map<String, String>? = null

    override suspend fun findByEurioId(eurioId: String): CoinViewData? {
        return dao.findByEurioId(eurioId)?.toViewData()
    }

    override suspend fun findAllByFaceValue(faceValue: Double): List<CoinViewData> {
        val cents = (faceValue * 100).toInt()
        return dao.findAllByFaceValueCents(cents).map { it.toViewData() }
    }

    override suspend fun resolveByClassifierName(className: String): CoinViewData? {
        dao.findByEurioId(className)?.let { return it.toViewData() }
        return null
    }

    override suspend fun findMarket(eurioId: String, faceValueCents: Int): CoinMarket? =
        deriveMarketFromPrices(priceDao.findByEurioId(eurioId), faceValueCents)

    private suspend fun resolveReverseUrl(sharedReverseId: String?): String? {
        if (sharedReverseId == null) return null
        val cache = reverseAssetCache ?: buildReverseCache().also { reverseAssetCache = it }
        val assetName = cache[sharedReverseId] ?: return null
        return "file:///android_asset/shared_reverse/$assetName"
    }

    private suspend fun buildReverseCache(): Map<String, String> {
        // Only 2 rows — acceptable to fetch individually; no bulk query in DAO.
        // We rely on Room observing the table only at insertion time.
        val knownIds = listOf("2eur-map-v1", "2eur-map-v2")
        return knownIds.mapNotNull { id ->
            val row = sharedReverseDao.findById(id) ?: return@mapNotNull null
            val assetName = row.assetName ?: return@mapNotNull null
            id to assetName
        }.toMap()
    }

    private suspend fun CoinEntity.toViewData(): CoinViewData = CoinViewData(
        eurioId = eurioId,
        nameFr = nameFr ?: nameEn ?: eurioId,
        country = country,
        year = year ?: 0,
        faceValueCents = faceValueCents,
        imageObverseUrl = obverseStorageUrl(eurioId),
        imageReverseUrl = resolveReverseUrl(sharedReverseId),
        issueType = if (isCommemorative) "commemo" else "circulation",
        designDescription = designDescription,
        obversePhotoMeta = null,
        reversePhotoMeta = null,
    )
}

/**
 * Derives the obverse image URL for a coin.
 *
 * In QA builds (`BuildConfig.IS_QA`), images are bundled as assets by the QA
 * dump (`src/qa/assets/coin-images/<id>/obverse.webp`) so parity captures are
 * 100% hermetic — zero network. Coil resolves the `file:///android_asset/...`
 * URI offline; a coin without a bundled asset (e.g. `fr-1999`) yields a Coil
 * error → the component falls back to its placeholder (mirror of the web SVG
 * fallback). In release, IS_QA is false → the Supabase Storage branch is taken
 * (the coin-images bucket is public; no auth required), so no QA code leaks.
 */
fun obverseStorageUrl(eurioId: String): String =
    if (BuildConfig.IS_QA)
        "file:///android_asset/coin-images/$eurioId/obverse.webp"
    else
        "${SupabaseConfig.STORAGE_BASE_URL}/coin-images/$eurioId/obverse.webp"

/**
 * Central place for Supabase project constants used by the Android app.
 * The project URL drives both the PostgREST client and Storage bucket URLs.
 */
object SupabaseConfig {
    const val PROJECT_URL = "https://ettxkixkxrzchbnohgfm.supabase.co"
    const val STORAGE_BASE_URL = "$PROJECT_URL/storage/v1/object/public"
}
