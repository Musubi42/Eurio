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

/**
 * UI-ready display block emitted by `ml/utils/i18n.coin_display`. Embedded
 * per-test in v2 of `live_tests_manifest.json` so the Android client never
 * parses an eurio_id slug or formats a face value on device. Same shape
 * also appears in the top-level `coins_display` map keyed by eurio_id, used
 * to render "Le modèle a vu" when the predicted top-1 ≠ expected.
 */
@Serializable
data class CoinDisplay(
    val title: String,
    val country_iso: String,
    val country_fr: String,
    val flag_emoji: String,
    val year: Int? = null,
    val face_value_label: String,
    val image_obverse_url: String? = null,
    val eyebrow_compact: String,
)

@Serializable
data class TestPrescription(
    val idx: Int,
    val expected_eurio_id: String,
    val condition: String,
    val display: CoinDisplay,
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
    /**
     * R@1 under the design-group equivalence rule (cf. [EquivalenceMap]).
     * Strict `eurio_id` match → true ; same non-null `design_group_id` →
     * true ; otherwise false. Always >= [isCorrect].
     */
    val isCorrectEq: Boolean,
    val error: String?,
    val ts: String,
    /**
     * Scan-corpus archive hashes (Lot 2, corpus-spec §6). Full sha256 hex of
     * the exact `frames/<iteration>/<captureId>.raw.jpg` / `.crop.png` bytes
     * written at snap time; `captureId == rawSha[:16]`. Null when archiving
     * was disabled or failed (the scan itself never fails on archive errors).
     */
    val rawSha: String? = null,
    val cropSha: String? = null,
)

data class TopMatch(
    val eurioId: String,
    val similarity: Float,
)
