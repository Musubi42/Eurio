package com.musubi.eurio.cohorttest

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Phase 4 (lab-prod-refacto) — provenance card for the cohort-test bundle.
 *
 * Mirror of the JSON written by `ml/scripts/build_cohort_bundle.py` into
 * `cohort_bundle/bundle_meta.json`. Tells the device which **source** the
 * shipped model came from (a lab iteration vs. the promoted prod current),
 * so the user can read it on the cohort-test home screen and so live-test
 * JSONL logs can later be filtered by source server-side.
 *
 * Pre-phase-4 bundles ship without `bundle_meta.json`; in that case
 * [fromAssets] returns `null` and the UI degrades to a "legacy bundle"
 * label — the cohort-test still runs (the rest of the bundle is enough
 * for inference + live tests).
 *
 * Parity contract :
 *   - Python writer : `ml/scripts/build_cohort_bundle.py` (BUNDLE_META_VERSION).
 *   - Kotlin reader : this file + `BundleMetaTest.kt` (testCohortTest).
 *   - When the schema bumps, update [SCHEMA_VERSION] and the parser; we
 *     refuse to deserialize a future schema rather than silently mis-render.
 */
data class BundleMeta(
    val schemaVersion: Int,
    val source: Source,
    val cohortId: String,
    val cohortName: String,
    /**
     * The lab iteration this bundle is rooted in. Always set for
     * [Source.LAB]. May be `null` for [Source.PROD] when the operator
     * built the prod bundle without a `promoted_from.json` next to
     * `prod/current/` (legacy promotion or hand-pushed weights).
     */
    val iterationId: String?,
    val iterationName: String?,
    val trainingRunId: String?,
    val modelVersion: String?,
    val numClasses: Int?,
    val classKind: String?,
    val builtAt: String?,
    val sha256: Map<String, String>,
) {
    enum class Source(val wire: String) {
        LAB("lab"),
        PROD("prod"),
        ;

        companion object {
            fun fromWire(s: String?): Source? = when (s) {
                "lab" -> LAB
                "prod" -> PROD
                else -> null
            }
        }
    }

    /**
     * Short, single-line provenance label for the cohort-test header.
     * Examples :
     *   - `"Lab · test-1 v2"`           (source=lab, iteration_name set)
     *   - `"Lab · 8ac508b0"`            (source=lab, no name → short id)
     *   - `"Prod · promu depuis 8ac508b0"` (source=prod with iteration_id)
     *   - `"Prod"`                      (source=prod without iteration_id)
     */
    fun shortLabel(): String = when (source) {
        Source.LAB -> "Lab · ${iterationName?.takeIf { it.isNotBlank() } ?: shortIid()}"
        Source.PROD -> if (iterationId != null) {
            "Prod · promu depuis ${shortIid()}"
        } else {
            "Prod"
        }
    }

    private fun shortIid(): String =
        iterationId?.take(8) ?: "?"

    companion object {
        const val SCHEMA_VERSION: Int = 2
        const val ASSET_PATH: String = "cohort_bundle/bundle_meta.json"

        /** Sentinel label used when [fromAssets] returned `null`. */
        const val LEGACY_LABEL: String = "Bundle legacy"

        private val parser = Json {
            ignoreUnknownKeys = true
            explicitNulls = false
        }

        /**
         * Parse a `bundle_meta.json` payload. Returns `null` on any of:
         *   - malformed JSON ;
         *   - unknown / missing `source` ;
         *   - missing required identity fields (`cohort_id`).
         *
         * A future `schema_version` higher than [SCHEMA_VERSION] also
         * yields `null` — we'd rather show "Bundle legacy" than gamble on a
         * field whose semantics changed under us. Lower versions are
         * accepted (current code only adds optional fields).
         */
        fun fromJson(text: String): BundleMeta? = runCatching {
            val obj = parser.parseToJsonElement(text).jsonObject
            val schema = obj["schema_version"]?.jsonPrimitive?.intOrNull
                ?: return@runCatching null
            if (schema > SCHEMA_VERSION) return@runCatching null
            val source = Source.fromWire(obj.str("source"))
                ?: return@runCatching null
            val cohortId = obj.str("cohort_id") ?: return@runCatching null
            val cohortName = obj.str("cohort_name") ?: cohortId
            BundleMeta(
                schemaVersion = schema,
                source = source,
                cohortId = cohortId,
                cohortName = cohortName,
                iterationId = obj.str("iteration_id"),
                iterationName = obj.str("iteration_name"),
                trainingRunId = obj.str("training_run_id"),
                modelVersion = obj.str("model_version"),
                numClasses = obj["num_classes"]?.jsonPrimitive?.intOrNull,
                classKind = obj.str("class_kind"),
                builtAt = obj.str("built_at"),
                sha256 = (obj["sha256"] as? JsonObject)?.mapValues { (_, v) ->
                    (v as? JsonPrimitive)?.contentOrNull.orEmpty()
                } ?: emptyMap(),
            )
        }.getOrNull()

        /**
         * Load `cohort_bundle/bundle_meta.json` from app assets. Returns
         * `null` for pre-phase-4 bundles (file absent) or when the payload
         * fails to parse cleanly. Caller renders [LEGACY_LABEL] in that
         * case.
         */
        fun fromAssets(
            assets: android.content.res.AssetManager,
            path: String = ASSET_PATH,
        ): BundleMeta? = runCatching {
            assets.open(path).bufferedReader().use { fromJson(it.readText()) }
        }.getOrNull()

        private fun JsonObject.str(key: String): String? =
            this[key]?.jsonPrimitive?.contentOrNull
    }
}
