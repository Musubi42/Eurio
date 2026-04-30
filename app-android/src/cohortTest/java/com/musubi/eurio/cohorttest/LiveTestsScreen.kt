package com.musubi.eurio.cohorttest

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.ScanResult
import java.util.concurrent.Executors

/**
 * Sprint 4 — guided live-test runner. Flow:
 *
 *   1. Show "Test N/M : <expected_eurio_id> · <condition>".
 *   2. CameraX preview + a SNAP button.
 *   3. On snap: analyzer is in [CoinAnalyzer.photoMode], we set
 *      [CoinAnalyzer.snapRequested] = true, the next frame is normalized
 *      (Hough → 224×224 mask) and run through ArcFace.
 *   4. Result panel renders top-3 + ✓/✗ badge.
 *   5. "Test suivant →" jumps to the next not-yet-snapped test.
 *
 * No re-snap of an already-correct test (D-005). OQ-4: a "Refaire" button
 * shows up only when the previous result was an error (inference crash or
 * normalize miss), giving the user an out without enabling confirmation
 * bias on regular results.
 */
/**
 * Mutable relay : the activity builds the analyzer once with a callback that
 * dispatches into [delegate]. The composable swaps [delegate] each time the
 * active test changes so the result handler always closes over the current
 * test_idx + state mutators.
 */
class LiveTestRelay {
    @Volatile
    var delegate: ((ScanResult) -> Unit)? = null
    fun emit(result: ScanResult) {
        delegate?.invoke(result)
    }
}

@Composable
fun LiveTestsScreen(
    bundle: CohortBundle,
    tests: List<TestPrescription>,
    analyzer: CoinAnalyzer,
    relay: LiveTestRelay,
    logger: LiveTestLogger,
    initialResults: Map<Int, TestResult>,
) {
    if (tests.isEmpty()) {
        EmptyTestsState(bundle)
        return
    }

    val context = LocalContext.current
    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted -> hasCameraPermission = granted }

    LaunchedEffect(Unit) {
        if (!hasCameraPermission) {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    if (!hasCameraPermission) {
        PermissionDeniedState(
            onRequest = { permissionLauncher.launch(Manifest.permission.CAMERA) },
        )
        return
    }

    // Per-test result cache. Index = test_idx (1-based), null = not snapped.
    val results = remember {
        androidx.compose.runtime.mutableStateMapOf<Int, TestResult>().apply {
            putAll(initialResults)
        }
    }
    var currentIdx by remember {
        mutableIntStateOf(
            // Resume on the first test without a result, else last index.
            tests.firstOrNull { it.idx !in results }?.idx ?: tests.last().idx,
        )
    }
    val current = remember(currentIdx) { tests.first { it.idx == currentIdx } }
    val currentResult = results[current.idx]
    val completedCount = results.size
    var awaitingSnap by remember { mutableStateOf(false) }

    // Bind the analyzer's onResult callback. CoinAnalyzer is built once at
    // activity scope, so we relay through a mutable local handler that we
    // swap whenever the active test changes.
    LaunchedEffect(analyzer) {
        analyzer.photoMode = true
    }

    // Stable onResult: when a snap arrives, build the TestResult, persist,
    // and clear the awaitingSnap flag.
    val onScan: (ScanResult) -> Unit = remember {
        { scan ->
            if (awaitingSnap) {
                val top3 = scan.matches.take(3).map {
                    TopMatch(eurioId = it.className, similarity = it.similarity)
                }
                val top1 = top3.firstOrNull()
                val errorMsg = if (scan.rerankRejectedAll && top3.isEmpty()) {
                    scan.rerankDecisionReason.takeIf { it.isNotEmpty() }
                        ?: "inference returned no matches"
                } else null
                val result = TestResult(
                    testIdx = current.idx,
                    expectedEurioId = current.expected_eurio_id,
                    condition = current.condition,
                    predictedTop3 = top3,
                    predictedTop1 = top1?.eurioId,
                    similarityTop1 = top1?.similarity,
                    isCorrect = (top1?.eurioId == current.expected_eurio_id),
                    error = errorMsg,
                    ts = logger.isoNow(),
                )
                if (current.idx !in results) {
                    // First time we get a result for this test — commit.
                    results[current.idx] = result
                    runCatching { logger.append(result) }
                        .onFailure { android.util.Log.e("LiveTests", "Append failed", it) }
                } else if (results[current.idx]?.error != null && result.error == null) {
                    // OQ-4 — only allow re-snapping a previous failure.
                    results[current.idx] = result
                    runCatching { logger.append(result) }
                }
                awaitingSnap = false
            }
        }
    }
    LaunchedEffect(relay, onScan) {
        relay.delegate = onScan
    }
    DisposableEffect(relay) {
        onDispose { relay.delegate = null }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .systemBarsPadding(),
    ) {
        // Top bar — prescription
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface)
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "Test ${current.idx}/${tests.size}",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "$completedCount/${tests.size} faits",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                "${current.expected_eurio_id} · ${current.condition}",
                style = MaterialTheme.typography.bodyLarge,
                fontFamily = FontFamily.Monospace,
            )
            LinearProgressIndicator(
                progress = { (completedCount.toFloat() / tests.size).coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(),
            )
        }

        // Camera preview area
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(1f)
                .background(Color.Black),
        ) {
            CohortCameraPreview(
                analyzer = analyzer,
                modifier = Modifier.fillMaxSize(),
            )
            // Centered guide circle (purely visual)
            Box(
                modifier = Modifier
                    .align(Alignment.Center)
                    .fillMaxWidth(0.7f)
                    .aspectRatio(1f)
                    .clip(CircleShape)
                    .border(2.dp, Color.White.copy(alpha = 0.6f), CircleShape),
            )
        }

        // Bottom panel — result + actions
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (currentResult == null) {
                Text(
                    "Pose la pièce, vise, puis tape Snap.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(
                    onClick = {
                        awaitingSnap = true
                        analyzer.snapRequested = true
                    },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !awaitingSnap,
                ) {
                    Text(if (awaitingSnap) "Analyse…" else "Snap")
                }
            } else {
                ResultPanel(result = currentResult)
                val canRetry = currentResult.error != null
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    if (canRetry) {
                        OutlinedButton(
                            onClick = {
                                awaitingSnap = true
                                analyzer.snapRequested = true
                            },
                            modifier = Modifier.weight(1f),
                        ) { Text("Refaire") }
                    }
                    Button(
                        onClick = {
                            val next = tests.firstOrNull { it.idx !in results }
                            if (next != null) currentIdx = next.idx
                        },
                        modifier = Modifier.weight(1f),
                        enabled = tests.any { it.idx !in results },
                    ) {
                        Text(
                            if (tests.all { it.idx in results }) "Tous faits" else "Test suivant →",
                        )
                    }
                }
            }
            // Manual nav (chevron back/next) — D-005 forbids re-snap, but we
            // do allow scrolling through tests to inspect already-done ones.
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                OutlinedButton(
                    onClick = {
                        val prev = tests.lastOrNull { it.idx < current.idx }
                        if (prev != null) currentIdx = prev.idx
                    },
                    enabled = current.idx > tests.first().idx,
                ) { Text("‹") }
                Text(
                    if (tests.all { it.idx in results })
                        "Tous les tests sont faits — sync via cohort-test:pull-tests"
                    else "Tests restants: ${tests.size - completedCount}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedButton(
                    onClick = {
                        val next = tests.firstOrNull { it.idx > current.idx }
                        if (next != null) currentIdx = next.idx
                    },
                    enabled = current.idx < tests.last().idx,
                ) { Text("›") }
            }
            // End card — surfaced when the user has done everything.
            if (tests.all { it.idx in results }) {
                EndOfRunCard(iterationId = bundle.iterationId, logFile = logger.outputFile.absolutePath)
            }
        }
    }
}

@Composable
private fun ResultPanel(result: TestResult) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "Top-3",
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.SemiBold,
            )
            val (label, color) = when {
                result.error != null -> "Erreur" to MaterialTheme.colorScheme.error
                result.isCorrect -> "✓ correct" to Color(0xFF4CAF50)
                else -> "✗ incorrect" to MaterialTheme.colorScheme.error
            }
            Text(
                label,
                color = color,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
            )
        }
        if (result.error != null) {
            Text(
                result.error,
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.error,
            )
        }
        result.predictedTop3.forEachIndexed { idx, m ->
            val highlight = (m.eurioId == result.expectedEurioId)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    "#${idx + 1} ${m.eurioId}",
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = if (highlight) FontWeight.Bold else FontWeight.Normal,
                    color = if (highlight) Color(0xFF4CAF50)
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    "%.3f".format(m.similarity),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                )
            }
        }
        if (result.predictedTop3.isEmpty()) {
            Text(
                "(no matches)",
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun EndOfRunCard(iterationId: String, logFile: String) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.tertiaryContainer)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            "Tous les tests faits.",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "Sur ton ordi, lance:",
            style = MaterialTheme.typography.bodySmall,
        )
        Text(
            "go-task -t app-android/Taskfile.yml cohort-test:pull-tests ITERATION=$iterationId",
            style = MaterialTheme.typography.bodySmall,
            fontFamily = FontFamily.Monospace,
        )
        Text(
            "Log: $logFile",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onTertiaryContainer.copy(alpha = 0.7f),
            fontFamily = FontFamily.Monospace,
        )
    }
}

@Composable
private fun EmptyTestsState(bundle: CohortBundle) {
    Box(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            "Aucun test prescrit pour ${bundle.cohortName} / ${bundle.iterationId}.",
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun PermissionDeniedState(onRequest: () -> Unit) {
    Box(
        modifier = Modifier.fillMaxSize().systemBarsPadding().padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                "Autorisation caméra requise.",
                style = MaterialTheme.typography.bodyLarge,
            )
            Button(onClick = onRequest) { Text("Autoriser la caméra") }
        }
    }
}

@Composable
private fun CohortCameraPreview(
    analyzer: CoinAnalyzer,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }

    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            PreviewView(ctx).also { previewView ->
                val providerFuture = ProcessCameraProvider.getInstance(ctx)
                providerFuture.addListener({
                    val provider = providerFuture.get()
                    val preview = Preview.Builder().build().also {
                        it.surfaceProvider = previewView.surfaceProvider
                    }
                    val analysis = ImageAnalysis.Builder()
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build()
                        .also { it.setAnalyzer(executor) { image -> analyzer.analyze(image) } }
                    try {
                        provider.unbindAll()
                        provider.bindToLifecycle(
                            lifecycleOwner,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            analysis,
                        )
                    } catch (e: Exception) {
                        android.util.Log.e("LiveTests", "Camera bind failed", e)
                    }
                }, ContextCompat.getMainExecutor(ctx))
            }
        },
    )

    DisposableEffect(lifecycleOwner) {
        onDispose {
            executor.shutdown()
            runCatching { ProcessCameraProvider.getInstance(context).get().unbindAll() }
        }
    }
}
