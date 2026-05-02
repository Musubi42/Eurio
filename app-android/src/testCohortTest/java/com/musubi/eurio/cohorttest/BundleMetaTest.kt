package com.musubi.eurio.cohorttest

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Parse + label tests for [BundleMeta] vs the JSON written by
 * `ml/scripts/build_cohort_bundle.py` (phase 4, lab-prod-refacto).
 *
 * These tests pin the **wire contract** between the bundle script and the
 * cohort-test app : if the Python writer drops a field or renames the
 * source enum, this suite breaks before the device does. They also cover
 * the legacy fallback path so older bundles built before phase 4 still
 * load and display "Bundle legacy" in the header.
 */
class BundleMetaTest {

    @Test
    fun parses_lab_bundle_with_full_identity() {
        val json = """
            {
              "schema_version": 2,
              "source": "lab",
              "cohort_id": "abc123",
              "cohort_name": "treaty-of-rome",
              "iteration_id": "8ac508b062da",
              "iteration_name": "test-1 v2",
              "training_run_id": "run-1",
              "model_version": "v10-arcface",
              "num_classes": 7,
              "class_kind": "eurio_id",
              "built_at": "2026-05-02T17:30:00Z",
              "sha256": {
                "eurio_embedder_v1.tflite": "deadbeef",
                "embeddings_v1.json": "cafebabe",
                "model_meta.json": "f00dface"
              }
            }
        """.trimIndent()

        val meta = BundleMeta.fromJson(json)
        assertNotNull(meta)
        meta!!
        assertEquals(2, meta.schemaVersion)
        assertEquals(BundleMeta.Source.LAB, meta.source)
        assertEquals("abc123", meta.cohortId)
        assertEquals("treaty-of-rome", meta.cohortName)
        assertEquals("8ac508b062da", meta.iterationId)
        assertEquals("test-1 v2", meta.iterationName)
        assertEquals("run-1", meta.trainingRunId)
        assertEquals("v10-arcface", meta.modelVersion)
        assertEquals(7, meta.numClasses)
        assertEquals("eurio_id", meta.classKind)
        assertEquals("deadbeef", meta.sha256["eurio_embedder_v1.tflite"])
        // Label uses iteration_name when present.
        assertEquals("Lab · test-1 v2", meta.shortLabel())
    }

    @Test
    fun parses_prod_bundle_without_iteration_id() {
        // Case where promoted_from.json was missing at bundle time, so the
        // Python script wrote iteration_id=null and dependent fields=null.
        val json = """
            {
              "schema_version": 2,
              "source": "prod",
              "cohort_id": "abc123",
              "cohort_name": "treaty-of-rome",
              "iteration_id": null,
              "iteration_name": null,
              "training_run_id": null,
              "model_version": "v10-arcface",
              "num_classes": 7,
              "class_kind": "eurio_id",
              "built_at": "2026-05-02T17:30:00Z",
              "sha256": {}
            }
        """.trimIndent()

        val meta = BundleMeta.fromJson(json)
        assertNotNull(meta)
        meta!!
        assertEquals(BundleMeta.Source.PROD, meta.source)
        assertNull(meta.iterationId)
        assertNull(meta.iterationName)
        assertNull(meta.trainingRunId)
        // Label degrades to plain "Prod" without iteration anchor.
        assertEquals("Prod", meta.shortLabel())
    }

    @Test
    fun parses_prod_bundle_with_iteration_id() {
        val json = """
            {
              "schema_version": 2,
              "source": "prod",
              "cohort_id": "abc123",
              "cohort_name": "treaty-of-rome",
              "iteration_id": "8ac508b062da",
              "iteration_name": "promoted",
              "model_version": "v10-arcface",
              "num_classes": 7,
              "built_at": "2026-05-02T17:30:00Z",
              "sha256": {}
            }
        """.trimIndent()

        val meta = BundleMeta.fromJson(json)
        assertNotNull(meta)
        // Prod uses the short id, not the iteration_name (the name is
        // typically a lab-only label that's confusing once promoted).
        assertEquals("Prod · promu depuis 8ac508b0", meta!!.shortLabel())
    }

    @Test
    fun lab_label_falls_back_to_short_iteration_id_when_name_missing() {
        val json = """
            {
              "schema_version": 2,
              "source": "lab",
              "cohort_id": "abc123",
              "cohort_name": "treaty-of-rome",
              "iteration_id": "8ac508b062da",
              "iteration_name": null,
              "sha256": {}
            }
        """.trimIndent()

        val meta = BundleMeta.fromJson(json)
        assertNotNull(meta)
        assertEquals("Lab · 8ac508b0", meta!!.shortLabel())
    }

    @Test
    fun returns_null_on_malformed_json() {
        assertNull(BundleMeta.fromJson("not-json{"))
        assertNull(BundleMeta.fromJson(""))
    }

    @Test
    fun returns_null_when_source_missing_or_unknown() {
        val noSource = """
            { "schema_version": 2, "cohort_id": "abc" }
        """.trimIndent()
        assertNull(BundleMeta.fromJson(noSource))

        val badSource = """
            { "schema_version": 2, "source": "wat", "cohort_id": "abc" }
        """.trimIndent()
        assertNull(BundleMeta.fromJson(badSource))
    }

    @Test
    fun returns_null_when_cohort_id_missing() {
        val json = """
            { "schema_version": 2, "source": "lab" }
        """.trimIndent()
        assertNull(BundleMeta.fromJson(json))
    }

    @Test
    fun returns_null_for_future_schema_version() {
        // We refuse to render a future schema rather than risk
        // mis-interpreting renamed/removed fields. Older schemas
        // (schema_version=1, before phase 4) never had bundle_meta.json
        // shipped at all — they hit the fromAssets fallback instead.
        val json = """
            {
              "schema_version": 99,
              "source": "lab",
              "cohort_id": "abc"
            }
        """.trimIndent()
        assertNull(BundleMeta.fromJson(json))
    }

    @Test
    fun legacy_label_used_when_no_meta() {
        // Smoke test for the constant the UI uses when fromAssets returned
        // null. Pinned here so a rename of the constant breaks the test.
        assertTrue(BundleMeta.LEGACY_LABEL.isNotBlank())
    }
}
