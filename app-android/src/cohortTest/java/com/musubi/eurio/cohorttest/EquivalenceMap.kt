package com.musubi.eurio.cohorttest

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject

/**
 * Design-group equivalence — Kotlin mirror of `ml/eval/equivalence.py`.
 *
 * The lab trains in strict `eurio_id` mode (one centroid per coin). The
 * cohort-test verdict considers two `eurio_id` sharing the same non-null
 * `design_group_id` as equivalent at the verdict step (e.g. BE-2007,
 * DE-2007, FR-2007 commémoratives "Traité de Rome" all share the same
 * design — predicting DE when the ground truth is BE is not a real error
 * under the design-group rule).
 *
 * Parity contract — these two implementations MUST stay in sync:
 *   - Python: `ml/eval/equivalence.py` + `ml/tests/test_equivalence.py`.
 *   - Kotlin: this file + `EquivalenceMapTest.kt` (cohortTestUnitTest).
 *
 * The map source is the `coins` Supabase table; the bundle script
 * `ml/scripts/build_cohort_bundle.py` dumps the cohort-filtered subset to
 * `cohort_bundle/equivalence_map.json` consumed by [fromAssets].
 */
data class EquivalenceMap(
    val eurioToGroup: Map<String, String?>,
) {
    /** Returns the design_group_id for [eurioId], or null if standalone/unknown. */
    fun designGroup(eurioId: String): String? = eurioToGroup[eurioId]

    /**
     * True when [predicted] is correct under the design-group rule:
     *   - strict `eurio_id` match → equivalent ;
     *   - same non-null `design_group_id` → equivalent ;
     *   - otherwise → not equivalent.
     */
    fun areEquivalent(predicted: String, groundTruth: String): Boolean {
        if (predicted == groundTruth) return true
        // Le modèle prédit des labels de CLASSE = COALESCE(design_group_id,
        // eurio_id) : `predicted` peut être un id de design_group (ex.
        // "ad-2euro-standard-t1"), ABSENT des clés de la carte (qui mappe
        // eurio_id → group). On résout chaque côté vers sa classe canonique
        // (le groupe si connu, sinon l'id lui-même) puis on compare. Deux
        // pièces distinctes sans groupe restent non-équivalentes (id != id) —
        // pas de faux positif vs l'ancien garde `gPred != null`.
        val cPred = eurioToGroup[predicted] ?: predicted
        val cGt = eurioToGroup[groundTruth] ?: groundTruth
        return cPred == cGt
    }

    fun toJson(): String = buildString {
        append('{')
        val sortedKeys = eurioToGroup.keys.sorted()
        sortedKeys.forEachIndexed { i, k ->
            if (i > 0) append(',')
            append(esc(k)).append(':')
            val v = eurioToGroup[k]
            if (v == null) append("null") else append(esc(v))
        }
        append('}')
    }

    private fun esc(s: String): String {
        val sb = StringBuilder(s.length + 2)
        sb.append('"')
        for (c in s) {
            when (c) {
                '\\' -> sb.append("\\\\")
                '"' -> sb.append("\\\"")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                else -> if (c.code < 0x20) sb.append("\\u%04x".format(c.code)) else sb.append(c)
            }
        }
        sb.append('"')
        return sb.toString()
    }

    companion object {
        /** Empty map — `areEquivalent` then degrades to strict-only. */
        val EMPTY: EquivalenceMap = EquivalenceMap(emptyMap())

        fun fromJson(text: String): EquivalenceMap {
            val obj: JsonObject = Json.parseToJsonElement(text).jsonObject
            val out = LinkedHashMap<String, String?>(obj.size)
            for ((k, v) in obj) {
                out[k] = when (v) {
                    is JsonNull -> null
                    is JsonPrimitive -> v.contentOrNull
                    else -> null
                }
            }
            return EquivalenceMap(out)
        }

        /**
         * Load `cohort_bundle/equivalence_map.json` from app assets. Returns
         * [EMPTY] if the file is missing — older bundles built before phase 3
         * shipped without the map, and the cohort-test should still run with
         * strict-only verdicts in that case.
         */
        fun fromAssets(
            assets: android.content.res.AssetManager,
            path: String = "cohort_bundle/equivalence_map.json",
        ): EquivalenceMap = runCatching {
            assets.open(path).bufferedReader().use { fromJson(it.readText()) }
        }.getOrElse { EMPTY }
    }
}
