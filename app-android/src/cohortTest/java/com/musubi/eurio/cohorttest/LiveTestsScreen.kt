package com.musubi.eurio.cohorttest

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.musubi.eurio.cohorttest.components.DetectionViewfinder
import com.musubi.eurio.cohorttest.components.HeroCoinCard
import com.musubi.eurio.cohorttest.components.ProgressStrip
import com.musubi.eurio.cohorttest.components.ResultSheet
import com.musubi.eurio.cohorttest.components.SnapCta
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.ScanResult
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.PaperSurface1
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

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

/**
 * Sprint 4 (refacto v2) — guided live-test runner.
 *
 * Orchestrates camera permission, the per-test cursor, the snap relay,
 * the result sheet, and writes each result to JSONL via [LiveTestLogger].
 * Visual layout owned by `components/`:
 *   - [ProgressStrip] above the hero
 *   - [HeroCoinCard] with the coin to snap
 *   - [DetectionViewfinder] (CameraX preview + ring + status badges)
 *   - [SnapCta] (gated on [detectionFlow])
 *   - [ResultSheet] (slides over camera + CTA after a snap)
 *
 * The "no re-snap" rule (D-005) is preserved: the only way to overwrite a
 * recorded result is via the Refaire button, and that button is only
 * surfaced when the previous attempt failed with [TestResult.error] != null
 * (OQ-4). Manual chevron nav (in the end-of-run card) lets the user
 * inspect already-done tests.
 */
@Composable
fun LiveTestsScreen(
    bundle: CohortBundle,
    tests: List<TestPrescription>,
    analyzer: CoinAnalyzer,
    relay: LiveTestRelay,
    logger: LiveTestLogger,
    initialResults: Map<Int, TestResult>,
    detectionFlow: StateFlow<Boolean>,
    equivalence: EquivalenceMap,
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
        mutableStateMapOf<Int, TestResult>().apply {
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
    var awaitingSnap by remember { mutableStateOf(false) }
    var sheetVisible by remember { mutableStateOf(false) }

    val detected by detectionFlow.collectAsStateWithLifecycle()

    LaunchedEffect(analyzer) {
        analyzer.photoMode = true
    }

    // Reset detection visual state every time the active test changes so a
    // stale "detected" from the previous frame doesn't auto-enable the
    // next snap before the user has even pointed the camera.
    LaunchedEffect(currentIdx) {
        (detectionFlow as? MutableStateFlow<Boolean>)?.value = false
    }

    // Auto-open the sheet when a result is available for the current test
    // (covers both fresh snap and resume-from-cold-start with a previous
    // result in JSONL).
    LaunchedEffect(currentIdx, currentResult) {
        sheetVisible = currentResult != null
    }

    // Bind the analyzer's onResult callback. CoinAnalyzer is built once at
    // activity scope, so we relay through a mutable local handler that we
    // swap whenever the active test changes (via rememberUpdatedState).
    val currentRef = rememberUpdatedState(current)
    val onScan: (ScanResult) -> Unit = remember {
        { scan ->
            if (awaitingSnap) {
                val active = currentRef.value
                val top3 = scan.matches.take(3).map {
                    TopMatch(eurioId = it.className, similarity = it.similarity)
                }
                val top1 = top3.firstOrNull()
                val errorMsg = if (scan.rerankRejectedAll && top3.isEmpty()) {
                    scan.rerankDecisionReason.takeIf { it.isNotEmpty() }
                        ?: "inference returned no matches"
                } else null
                val result = TestResult(
                    testIdx = active.idx,
                    expectedEurioId = active.expected_eurio_id,
                    condition = active.condition,
                    predictedTop3 = top3,
                    predictedTop1 = top1?.eurioId,
                    similarityTop1 = top1?.similarity,
                    isCorrect = (top1?.eurioId == active.expected_eurio_id),
                    isCorrectEq = top1?.eurioId?.let {
                        equivalence.areEquivalent(it, active.expected_eurio_id)
                    } ?: false,
                    error = errorMsg,
                    ts = logger.isoNow(),
                )
                if (active.idx !in results) {
                    results[active.idx] = result
                    runCatching { logger.append(result) }
                        .onFailure { android.util.Log.e("LiveTests", "Append failed", it) }
                } else if (results[active.idx]?.error != null && result.error == null) {
                    // OQ-4 — only allow re-snapping a previous failure.
                    results[active.idx] = result
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

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(PaperSurface),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .systemBarsPadding(),
        ) {
            // Phase 4 — provenance header (cohort name + bundle source).
            // Sober caption above the progress strip ; renders "Bundle
            // legacy" when the bundle predates phase 4 (no bundle_meta.json).
            BundleSourceHeader(
                cohortName = bundle.cohortName,
                meta = bundle.bundleMeta,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = EurioSpacing.s5,
                        vertical = EurioSpacing.s2,
                    ),
            )

            // Top: progress strip
            ProgressStrip(
                tests = tests,
                results = results,
                currentIdx = current.idx,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = EurioSpacing.s5,
                        vertical = EurioSpacing.s3,
                    ),
            )

            // Hero card
            HeroCoinCard(
                display = current.display,
                condition = current.condition,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = EurioSpacing.s5,
                        vertical = EurioSpacing.s2,
                    ),
            )

            // Camera viewfinder
            DetectionViewfinder(
                detected = detected,
                analyzer = analyzer,
                modifier = Modifier.fillMaxWidth(),
            )

            // Bottom: snap CTA + end-of-run card
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(
                        start = EurioSpacing.s5,
                        end = EurioSpacing.s5,
                        top = EurioSpacing.s4,
                        bottom = EurioSpacing.s5,
                    ),
                verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
            ) {
                SnapCta(
                    detected = detected,
                    awaiting = awaitingSnap,
                    onSnap = {
                        if (detected && !awaitingSnap) {
                            awaitingSnap = true
                            analyzer.snapRequested = true
                        }
                    },
                )
                if (tests.all { it.idx in results }) {
                    EndOfRunCard(
                        iterationId = bundle.iterationId,
                        logFile = logger.outputFile.absolutePath,
                    )
                }
            }
        }

        // Result sheet — overlays the camera + bottom CTA.
        ResultSheet(
            visible = sheetVisible,
            result = currentResult,
            expected = current.display,
            predictedDisplay = currentResult?.predictedTop1?.let { bundle.coinsDisplay[it] },
            onNext = {
                val next = tests.firstOrNull { it.idx !in results }
                if (next != null) {
                    sheetVisible = false
                    currentIdx = next.idx
                } else {
                    // Everything snapped — just close the sheet so the
                    // EndOfRunCard becomes visible.
                    sheetVisible = false
                }
            },
            onRetry = if (currentResult?.error != null) {
                {
                    sheetVisible = false
                    awaitingSnap = true
                    analyzer.snapRequested = true
                }
            } else null,
            onDismiss = { sheetVisible = false },
        )
    }
}

@Composable
private fun EndOfRunCard(iterationId: String, logFile: String) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(PaperSurface1)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            "Tous les tests faits.",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "Sur ton ordi, lance :",
            style = MaterialTheme.typography.bodySmall,
        )
        Text(
            "go-task -t app-android/Taskfile.yml cohort-test:pull-tests ITERATION=$iterationId",
            style = MaterialTheme.typography.bodySmall,
            fontFamily = FontFamily.Monospace,
        )
        Text(
            "Log : $logFile",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontFamily = FontFamily.Monospace,
        )
    }
}

/**
 * Provenance header shown above the progress strip — phase 4 (lab-prod-refacto).
 *
 * Renders the cohort name in title case + a one-line caption summarising
 * the bundle source (lab iteration vs. promoted prod). Falls back to a
 * "Bundle legacy" caption when [meta] is null (pre-phase-4 bundle without
 * `bundle_meta.json`). Style is intentionally sober — it's tooling text,
 * not a hero badge.
 */
@Composable
private fun BundleSourceHeader(
    cohortName: String,
    meta: BundleMeta?,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(
            text = cohortName,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            text = meta?.shortLabel() ?: BundleMeta.LEGACY_LABEL,
            style = MaterialTheme.typography.labelSmall,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (meta != null) {
            // Discreet sub-line with the model identity. Useful when an
            // operator runs two flavored APKs side by side.
            val modelBits = buildList {
                meta.modelVersion?.takeIf { it.isNotBlank() }?.let { add(it) }
                meta.numClasses?.let { add("$it classes") }
            }
            if (modelBits.isNotEmpty()) {
                Text(
                    text = modelBits.joinToString(" · "),
                    style = MaterialTheme.typography.labelSmall,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
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
