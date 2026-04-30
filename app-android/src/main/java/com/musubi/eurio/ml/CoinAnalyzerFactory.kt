package com.musubi.eurio.ml

import android.content.Context

/**
 * Builder for [CoinAnalyzer] that decouples *where* the model + reference
 * embeddings come from. The prod ([com.musubi.eurio.EurioApp]) lazies the
 * analyzer with the canonical paths under `assets/models/` and `assets/data/`,
 * but the Sprint 4 cohortTest flavor needs to load its bundle from
 * `assets/cohort_bundle/` instead — without dragging Room/Supabase along.
 *
 * Usage:
 * ```kotlin
 * val analyzer = CoinAnalyzerFactory(context).build(
 *     CoinAnalyzerFactory.AssetPaths(
 *         modelPath = "cohort_bundle/eurio_embedder_v1.tflite",
 *         metaPath = "cohort_bundle/model_meta.json",
 *         embeddingsPath = "cohort_bundle/embeddings_v1.json",
 *     ),
 *     onResult = { result -> /* ... */ },
 * )
 * ```
 *
 * This intentionally does NOT touch [com.musubi.eurio.EurioApp] — flavors
 * that need a different setup just call this factory directly. YOLO/Hough
 * detector are skipped by default (cohortTest is photo-mode only, snap →
 * normalize → ArcFace) but can be enabled if a future flavor wants both.
 */
class CoinAnalyzerFactory(private val context: Context) {
    data class AssetPaths(
        val modelPath: String,
        val metaPath: String,
        val embeddingsPath: String,
    ) {
        companion object {
            /** Default prod paths (matches `EurioApp.coinAnalyzer`). */
            val PROD = AssetPaths(
                modelPath = "models/eurio_embedder_v1.tflite",
                metaPath = "data/model_meta.json",
                embeddingsPath = "data/coin_embeddings.json",
            )

            /** cohortTest paths under `cohort_bundle/`. */
            val COHORT_BUNDLE = AssetPaths(
                modelPath = "cohort_bundle/eurio_embedder_v1.tflite",
                metaPath = "cohort_bundle/model_meta.json",
                embeddingsPath = "cohort_bundle/embeddings_v1.json",
            )
        }
    }

    /**
     * Build a fresh [CoinAnalyzer]. Caller owns the lifecycle — keep it as a
     * singleton in your Application/ViewModel since interpreter init is
     * non-trivial. The matcher is wired only when the model is in arcface/embed
     * mode, mirroring the prod logic.
     */
    fun build(
        paths: AssetPaths,
        onResult: (ScanResult) -> Unit,
        debugRootDir: java.io.File? = null,
        analyzeIntervalMs: Long = 400L,
    ): CoinAnalyzer {
        val recognizer = CoinRecognizer(
            context, modelPath = paths.modelPath, metaPath = paths.metaPath,
        )
        val matcher = if (recognizer.meta.mode == "arcface" || recognizer.meta.mode == "embed") {
            EmbeddingMatcher(context, dataPath = paths.embeddingsPath)
        } else null
        return CoinAnalyzer(
            recognizer = recognizer,
            matcher = matcher,
            detector = null,                 // cohortTest = photo mode only
            onResult = onResult,
            analyzeIntervalMs = analyzeIntervalMs,
        ).apply {
            this.debugRootDir = debugRootDir
        }
    }
}
