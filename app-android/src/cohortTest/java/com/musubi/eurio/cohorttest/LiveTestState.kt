package com.musubi.eurio.cohorttest

import kotlinx.serialization.Serializable

/**
 * Sprint 4 — on-device state for the prescribed live-test loop. The
 * [TestPrescription] list comes from `cohort_bundle/live_tests_manifest.json`
 * (built by `ml/scripts/build_cohort_bundle.py`). Results are accumulated in
 * `results[idx-1]` so the index aligns with the `test_idx` we ship in the
 * JSONL log; null means "not yet snapped".
 *
 * The activity owns this state in `mutableStateOf`/`mutableStateListOf`
 * fields — there's no ViewModel here, the cohortTest flavor stays
 * deliberately bare-bones (no Hilt/Koin, no Room, no DataStore).
 */
@Serializable
data class TestPrescription(
    val idx: Int,
    val expected_eurio_id: String,
    val condition: String,
)

/**
 * Result of one live test. Mirrors the JSONL schema written by
 * [LiveTestLogger]; the activity converts this to a dict before the writer
 * sees it but holds onto it in-memory for the UI.
 */
data class TestResult(
    val testIdx: Int,
    val expectedEurioId: String,
    val condition: String,
    val predictedTop3: List<TopMatch>,
    val predictedTop1: String?,
    val similarityTop1: Float?,
    val isCorrect: Boolean,
    val error: String?,
    val ts: String,
)

data class TopMatch(
    val eurioId: String,
    val similarity: Float,
)
