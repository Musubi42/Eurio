package com.musubi.eurio.ml

/**
 * Single source of truth for the on-device debug filesystem layout under
 * `eurio_debug/`. Every writer and reader derives its sub-directory name from
 * here so the naming never drifts between the two sides
 * (cf. docs/operations/debug-data-taxonomy.md §3).
 *
 * Layout (under `getExternalFilesDir(DIRECTORY_DOCUMENTS)/eurio_debug/`):
 * ```
 * eval_real/                    # ← /dev/capture (NAME PRESERVED — ML coupling)
 * ├── manifest.jsonl            # 1 line per snap + "event":"skip" lines
 * └── <eurioId>/
 *     ├── <stepId>_crop.jpg     # photoIndex == 0  (LEGACY naming preserved)
 *     ├── <stepId>_raw.jpg
 *     ├── <stepId>.json
 *     └── <stepId>_p<n>_crop.jpg  # photoIndex > 0 (ABLATION)
 * photo_snaps/                  # ← /dev/photo  (renamed from snaps/)
 * └── snap_<ts>/{crop,raw}.jpg + meta.json
 * scan_sessions/                # ← /scan record  (renamed from flat session_<ts>/)
 * └── session_<ts>/frame_*.jpg + session.jsonl
 * ```
 *
 * The `_p<n>` suffix is appended only when `photoIndex > 0` so the LEGACY
 * 1-photo-per-step flow keeps its historical `<stepId>_crop.jpg` names (zero
 * regression for the ml/datasets/eval_real pipeline). Bench lives on a
 * different root (`getExternalFilesDir(null)/bench/`) and is not modelled here.
 */
object CapturePaths {

    /** Directory name (under the debug root) holding all capture-cohort data. */
    const val EVAL_REAL_DIR = "eval_real"

    /** Directory name (under the debug root) for rolling photo snaps (`/dev/photo`). */
    const val PHOTO_SNAPS_DIR = "photo_snaps"

    /** Directory name (under the debug root) for scan record sessions (`/scan` record). */
    const val SCAN_SESSIONS_DIR = "scan_sessions"

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
