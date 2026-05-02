package com.musubi.eurio.ml

import android.content.Context
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.float
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.sqrt

data class CoinMatch(
    val className: String,
    val similarity: Float,
)

/**
 * Loads reference coin embeddings from a JSON asset and matches query embeddings
 * via cosine similarity.
 *
 * Two on-disk schemas are supported transparently:
 *   - Flat (prod, `data/coin_embeddings.json`): `{ <key>: [floats] }`,
 *     produced by `ml/training/compute_embeddings.py`.
 *   - Cohort bundle (`cohort_bundle/embeddings_v1.json`): the richer
 *     `{ version, model, embedding_dim, coins: { <eurio_id>: { embedding: [floats], ... } } }`,
 *     produced by `ml/scripts/build_cohort_bundle.py`.
 *
 * The class name returned by [match] is the JSON key — numista_id for prod,
 * eurio_id for cohort bundles.
 */
class EmbeddingMatcher(context: Context, dataPath: String = "data/coin_embeddings.json") {

    private val referenceEmbeddings: Map<String, FloatArray>

    init {
        val jsonText = context.assets.open(dataPath).bufferedReader().use { it.readText() }
        val root = Json.parseToJsonElement(jsonText).jsonObject
        val coinsMap = (root["coins"] as? JsonObject) ?: root

        referenceEmbeddings = coinsMap.entries
            .mapNotNull { (key, value) ->
                val embedding = value.toEmbeddingArrayOrNull() ?: return@mapNotNull null
                key to embedding
            }
            .toMap()
    }

    private fun JsonElement.toEmbeddingArrayOrNull(): FloatArray? {
        val arr: JsonArray = when (this) {
            is JsonArray -> this
            is JsonObject -> (this["embedding"] as? JsonArray) ?: return null
            else -> return null
        }
        return arr.map { it.jsonPrimitive.float }.toFloatArray()
    }

    /**
     * Find the top-K most similar coins to the given embedding.
     */
    fun match(embedding: FloatArray, topK: Int = 3): List<CoinMatch> {
        return referenceEmbeddings.map { (name, ref) ->
            CoinMatch(name, cosineSimilarity(embedding, ref))
        }
            .sortedByDescending { it.similarity }
            .take(topK)
    }

    val coinCount: Int get() = referenceEmbeddings.size

    companion object {
        fun cosineSimilarity(a: FloatArray, b: FloatArray): Float {
            var dot = 0f
            var normA = 0f
            var normB = 0f
            for (i in a.indices) {
                dot += a[i] * b[i]
                normA += a[i] * a[i]
                normB += b[i] * b[i]
            }
            val denom = sqrt(normA) * sqrt(normB)
            return if (denom > 0f) dot / denom else 0f
        }
    }
}
