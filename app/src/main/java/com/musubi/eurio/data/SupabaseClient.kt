package com.musubi.eurio.data

import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.postgrest.Postgrest
import io.github.jan.supabase.postgrest.from
import kotlinx.serialization.Serializable

@Serializable
data class CoinDetail(
    val id: String,
    val numista_id: Int? = null,
    val name: String,
    val country: String,
    val year: Int? = null,
    val face_value: Double? = null,
    val type: String? = null,
    val mintage: Int? = null,
    val image_obverse_url: String? = null,
    val image_reverse_url: String? = null,
)

/**
 * Minimal Supabase client for fetching coin details.
 * Reads config from BuildConfig (set via build.gradle).
 */
object SupabaseCoinClient {

    private val client by lazy {
        createSupabaseClient(
            supabaseUrl = com.musubi.eurio.BuildConfig.SUPABASE_URL,
            supabaseKey = com.musubi.eurio.BuildConfig.SUPABASE_ANON_KEY,
        ) {
            install(Postgrest)
        }
    }

    /**
     * Fetch coin details by numista_id.
     * Returns null if not found.
     */
    suspend fun getCoinByNumistaId(numistaId: Int): CoinDetail? {
        return try {
            client.from("coins")
                .select()  {
                    filter { eq("numista_id", numistaId) }
                    limit(1)
                }
                .decodeSingleOrNull<CoinDetail>()
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Fetch coin details by UUID.
     */
    suspend fun getCoinById(id: String): CoinDetail? {
        return try {
            client.from("coins")
                .select() {
                    filter { eq("id", id) }
                    limit(1)
                }
                .decodeSingleOrNull<CoinDetail>()
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Fetch all coins (for the POC, there are only 5).
     */
    suspend fun getAllCoins(): List<CoinDetail> {
        return try {
            client.from("coins")
                .select()
                .decodeList<CoinDetail>()
        } catch (e: Exception) {
            emptyList()
        }
    }
}
