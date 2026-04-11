package com.musubi.eurio.ml

import android.content.Context
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.float
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.sqrt

data class CoinMatch(
    val className: String,
    val similarity: Float,
)

/**
 * Loads reference coin embeddings from a JSON asset and matches query embeddings
 * via cosine similarity.
 */
class EmbeddingMatcher(context: Context, dataPath: String = "data/coin_embeddings.json") {

    private val referenceEmbeddings: Map<String, FloatArray>

    init {
        val jsonText = context.assets.open(dataPath).bufferedReader().use { it.readText() }
        val jsonObject = Json.parseToJsonElement(jsonText) as JsonObject

        referenceEmbeddings = jsonObject.mapValues { (_, value) ->
            value.jsonArray.map { it.jsonPrimitive.float }.toFloatArray()
        }
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
