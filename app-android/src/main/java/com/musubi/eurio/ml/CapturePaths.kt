package com.musubi.eurio.ml

/**
 * Single source of truth for the on-device capture-cohort filesystem layout.
 *
 * Both the writer ([CoinAnalyzer], capture-mode branch) and the reader
 * ([com.musubi.eurio.features.dev.capture.CaptureDiskReader], resume + status)
 * derive paths from here so the naming never drifts between the two sides.
 *
 * Layout (under `getExternalFilesDir(DIRECTORY_DOCUMENTS)/eurio_debug/`):
 * ```
 * eval_real/
 * ├── manifest.jsonl            # 1 line per snap + "event":"skip" lines
 * └── <eurioId>/
 *     ├── <stepId>_crop.jpg     # photoIndex == 0  (LEGACY naming preserved)
 *     ├── <stepId>_raw.jpg
 *     ├── <stepId>.json
 *     └── <stepId>_p<n>_crop.jpg  # photoIndex > 0 (ABLATION)
 * ```
 *
 * The `_p<n>` suffix is appended only when `photoIndex > 0` so the LEGACY
 * 1-photo-per-step flow keeps its historical `<stepId>_crop.jpg` names (zero
 * regression for the ml/datasets/eval_real pipeline).
 */
object CapturePaths {

    /** Directory name (under the debug root) holding all capture-cohort data. */
    const val EVAL_REAL_DIR = "eval_real"

    /** Append-only manifest filename inside [EVAL_REAL_DIR]. */
    const val MANIFEST_FILE = "manifest.jsonl"

    /** `_p<n>` suffix for the n-th photo of a step (empty for the first photo). */
    fun photoSuffix(photoIndex: Int): String = if (photoIndex > 0) "_p$photoIndex" else ""

    fun cropFileName(stepId: String, photoIndex: Int): String =
        "$stepId${photoSuffix(photoIndex)}_crop.jpg"

    fun rawFileName(stepId: String, photoIndex: Int): String =
        "$stepId${photoSuffix(photoIndex)}_raw.jpg"

    fun metaFileName(stepId: String, photoIndex: Int): String =
        "$stepId${photoSuffix(photoIndex)}.json"
}
