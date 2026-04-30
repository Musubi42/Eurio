package com.musubi.eurio.cohorttest

import android.os.Bundle
import android.os.Environment
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.CoinAnalyzerFactory
import com.musubi.eurio.ui.theme.EurioTheme
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.opencv.android.OpenCVLoader

/**
 * Sprint 4 entry point for the per-cohort test build.
 *
 * Loads the bundle from `assets/cohort_bundle/`, builds a [CoinAnalyzer] via
 * [CoinAnalyzerFactory] (handoff option (b) — keeps EurioApp untouched while
 * letting cohortTest pick its own asset paths), and mounts [LiveTestsScreen]
 * which walks the user through the prescribed snaps and persists each
 * result to JSONL.
 */
class CohortTestActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // SnapNormalizer needs OpenCV. EurioApp.onCreate() already calls
        // initLocal() on the main process, but we re-do it defensively in
        // case the application class init order changes — initLocal() is
        // idempotent.
        if (!OpenCVLoader.initLocal()) {
            Log.e(TAG, "OpenCV init failed")
        }

        setContent {
            EurioTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    CohortTestRoot()
                }
            }
        }
    }

    companion object {
        private const val TAG = "CohortTestActivity"
    }
}

data class CohortBundle(
    val cohortName: String,
    val iterationId: String,
    val iterationName: String,
    val modelVersion: String,
    val trainedAt: String?,
    val numCoins: Int,
    val tests: List<TestPrescription>,
)

@Composable
private fun CohortTestRoot() {
    val context = LocalContext.current
    var bundle by remember { mutableStateOf<CohortBundle?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        runCatching {
            loadBundle(context.assets)
        }.onSuccess { bundle = it }
         .onFailure { error = it.message ?: it::class.java.simpleName }
    }

    when {
        error != null -> ErrorState(error!!)
        bundle == null -> Box(
            modifier = Modifier.fillMaxSize().systemBarsPadding(),
            contentAlignment = androidx.compose.ui.Alignment.Center,
        ) { Text("Chargement du bundle…") }
        else -> RunFlow(bundle = bundle!!)
    }
}

@Composable
private fun RunFlow(bundle: CohortBundle) {
    val context = LocalContext.current
    val relay = remember { LiveTestRelay() }
    val logger = remember(bundle.iterationId) {
        LiveTestLogger(context, bundle.iterationId)
    }
    val initialResults = remember(bundle.iterationId) {
        runCatching { logger.readAll() }
            .onFailure { Log.w("CohortTestActivity", "Read existing log failed", it) }
            .getOrDefault(emptyMap())
    }

    var analyzer by remember { mutableStateOf<CoinAnalyzer?>(null) }
    var initError by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(bundle) {
        runCatching {
            CoinAnalyzerFactory(context).build(
                paths = CoinAnalyzerFactory.AssetPaths.COHORT_BUNDLE,
                onResult = relay::emit,
                debugRootDir = java.io.File(
                    context.getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS),
                    "eurio_debug",
                ).apply { mkdirs() },
            ).also {
                // Live tests are one-shot only (D-005), so leave the
                // analyzer in photoMode.
                it.photoMode = true
            }
        }.onSuccess { analyzer = it }
         .onFailure { initError = it.message ?: it::class.java.simpleName }
    }

    when {
        initError != null -> ErrorState("Init analyzer: $initError")
        analyzer == null -> Box(
            modifier = Modifier.fillMaxSize().systemBarsPadding(),
            contentAlignment = androidx.compose.ui.Alignment.Center,
        ) { Text("Chargement du modèle…") }
        else -> LiveTestsScreen(
            bundle = bundle,
            tests = bundle.tests,
            analyzer = analyzer!!,
            relay = relay,
            logger = logger,
            initialResults = initialResults,
        )
    }
}

@Composable
private fun ErrorState(msg: String) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .systemBarsPadding()
            .padding(24.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                "Eurio · Cohort test",
                style = MaterialTheme.typography.headlineSmall,
            )
            Text(
                msg,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.error,
            )
            Text(
                "Lance:\n  go-task -t app-android/Taskfile.yml cohort-test:install COHORT=… ITERATION=…",
                fontFamily = FontFamily.Monospace,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

private fun loadBundle(assets: android.content.res.AssetManager): CohortBundle {
    val meta = assets.open("cohort_bundle/cohort_meta.json").bufferedReader()
        .use { it.readText() }
    val manifest = assets.open("cohort_bundle/live_tests_manifest.json").bufferedReader()
        .use { it.readText() }
    val catalog = assets.open("cohort_bundle/catalog_snapshot.json").bufferedReader()
        .use { it.readText() }

    val metaJson = Json.parseToJsonElement(meta).jsonObject
    val manifestJson = Json.parseToJsonElement(manifest).jsonObject
    val catalogJson = Json.parseToJsonElement(catalog).jsonObject

    val tests = manifestJson["tests"]?.jsonArray?.map { el ->
        val obj = el.jsonObject
        TestPrescription(
            idx = obj["idx"]!!.jsonPrimitive.int,
            expected_eurio_id = obj["expected_eurio_id"]!!.jsonPrimitive.content,
            condition = obj["condition"]!!.jsonPrimitive.content,
        )
    } ?: emptyList()

    return CohortBundle(
        cohortName = metaJson.str("cohort_name") ?: "?",
        iterationId = metaJson.str("iteration_id") ?: "?",
        iterationName = metaJson.str("iteration_name") ?: "?",
        modelVersion = metaJson.str("model_version") ?: "?",
        trainedAt = metaJson.str("trained_at"),
        numCoins = catalogJson["coins"]?.jsonArray?.size ?: 0,
        tests = tests,
    )
}

private fun JsonObject.str(key: String): String? =
    this[key]?.jsonPrimitive?.contentOrNull
