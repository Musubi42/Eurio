package com.musubi.eurio.features.dev.status

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.musubi.eurio.features.dev.capture.CaptureDiskReader
import com.musubi.eurio.features.dev.capture.CaptureProgressScanner
import com.musubi.eurio.features.dev.capture.CaptureProgressScanner.StepStatus
import com.musubi.eurio.features.scan.CaptureProtocol
import com.musubi.eurio.ml.CapturePaths
import java.io.File

/**
 * Read-only `/dev/status` screen — a faithful dump of what the capture-cohort
 * data on disk actually looks like (cf. docs/operations/debug-data-taxonomy.md
 * §6.2). Strictly read-only : it never writes nor deletes ; clean-up goes
 * through `go-task android:capture:clean`. Used to answer "where am I in my
 * captures?" on the phone and to verify the device is empty after a clean.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebugStatusScreen(
    debugRootDir: File?,
    benchRootDir: File?,
    onBack: () -> Unit,
) {
    var refreshKey by remember { mutableIntStateOf(0) }
    val scan = remember(refreshKey) { CaptureDiskReader.read(debugRootDir) }
    val coins = remember(refreshKey) { CaptureProtocol.coins }
    val steps = remember(refreshKey) { CaptureProtocol.steps }
    // Ephemeral categories (flat dump). eval_real is shown structured above ;
    // bench lives on a different root (getExternalFilesDir(null)/bench/).
    val categories = remember(refreshKey) {
        listOf(
            DebugCategoryReader.read(
                "photo_snaps",
                debugRootDir?.let { File(it, CapturePaths.PHOTO_SNAPS_DIR) },
            ),
            DebugCategoryReader.read(
                "scan_sessions",
                debugRootDir?.let { File(it, CapturePaths.SCAN_SESSIONS_DIR) },
            ),
            DebugCategoryReader.read(
                "bench",
                benchRootDir?.let { File(it, "sessions") },
            ),
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Debug status — capture", fontFamily = FontFamily.Monospace) },
                navigationIcon = {
                    TextButton(onClick = onBack) { Text("‹ Back") }
                },
                actions = {
                    TextButton(onClick = { refreshKey++ }) { Text("Refresh") }
                },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 12.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            item { SummaryHeader(scan) }
            item { HorizontalDivider(modifier = Modifier.padding(vertical = 6.dp)) }

            if (coins.isEmpty()) {
                item {
                    Text(
                        "Aucune cohorte chargée.\nPush un cohort.csv : go-task android:push-capture-csv CSV=…",
                        fontFamily = FontFamily.Monospace,
                        fontSize = 12.sp,
                        color = StatusColors.PENDING,
                    )
                }
            } else {
                items(scan.coins, key = { it.coinIndex }) { coinRow ->
                    val coin = coins.getOrNull(coinRow.coinIndex)
                    CoinBlock(
                        title = coin?.let { "${it.displayName}  (${it.eurioId})" } ?: "coin #${coinRow.coinIndex}",
                        steps = coinRow.steps,
                        stepLabel = { idx -> steps.getOrNull(idx)?.id ?: "step#$idx" },
                    )
                }
            }

            item { HorizontalDivider(modifier = Modifier.padding(vertical = 6.dp)) }
            item {
                Text(
                    "Catégories éphémères (read-only — pull/clean via go-task)",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                    color = StatusColors.DIM,
                    modifier = Modifier.padding(bottom = 2.dp),
                )
            }
            items(categories, key = { it.label }) { cat -> CategoryBlock(cat) }
        }
    }
}

@Composable
private fun SummaryHeader(scan: CaptureProgressScanner.Scan) {
    val skippedSteps = scan.coins.sumOf { row -> row.steps.count { it.status == StepStatus.SKIPPED } }
    val pendingSteps = scan.coins.sumOf { row -> row.steps.count { it.status == StepStatus.PENDING } }
    Column {
        Text(
            "Capturé  ${scan.captured} / ${scan.total} photos",
            fontFamily = FontFamily.Monospace,
            fontSize = 14.sp,
            color = if (scan.isComplete && scan.total > 0) StatusColors.CAPTURED else StatusColors.TEXT,
        )
        Text(
            "Steps : $skippedSteps skippés · $pendingSteps en attente" +
                if (scan.isComplete && scan.total > 0) "  · ✓ COMPLET" else "",
            fontFamily = FontFamily.Monospace,
            fontSize = 12.sp,
            color = StatusColors.DIM,
        )
    }
}

@Composable
private fun CoinBlock(
    title: String,
    steps: List<CaptureProgressScanner.StepCell>,
    stepLabel: (Int) -> String,
) {
    Column(modifier = Modifier.padding(top = 8.dp)) {
        Text(title, fontFamily = FontFamily.Monospace, fontSize = 13.sp, color = StatusColors.TEXT)
        steps.forEach { cell ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    statusGlyph(cell.status),
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                    color = statusColor(cell.status),
                )
                Text(
                    stepLabel(cell.stepIndex).padEnd(18).take(18),
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                    color = StatusColors.DIM,
                )
                Text(
                    when (cell.status) {
                        StepStatus.SKIPPED -> "skip"
                        else -> "${cell.capturedPhotos}/${cell.photosPerStep}"
                    },
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                    color = statusColor(cell.status),
                )
            }
        }
    }
}

@Composable
private fun CategoryBlock(cat: DebugCategoryReader.Category) {
    Column(modifier = Modifier.padding(top = 8.dp)) {
        val header = if (!cat.present) {
            "${cat.label}/  — vide"
        } else {
            "${cat.label}/  ${cat.fileCount} fichiers · ${DebugCategoryReader.formatBytes(cat.totalBytes)}"
        }
        Text(
            header,
            fontFamily = FontFamily.Monospace,
            fontSize = 13.sp,
            color = if (cat.present && cat.fileCount > 0) StatusColors.TEXT else StatusColors.DIM,
        )
        // Flat tree : one line per immediate child. Capped to keep the dump
        // readable on a long-running session ; the count above stays exact.
        cat.entries.take(MAX_ENTRY_LINES).forEach { entry ->
            Text(
                "  ${if (entry.isDirectory) "▸" else "·"} ${entry.name}" +
                    "  (${entry.fileCount}f · ${DebugCategoryReader.formatBytes(entry.totalBytes)})",
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp,
                color = StatusColors.DIM,
            )
        }
        if (cat.entries.size > MAX_ENTRY_LINES) {
            Text(
                "  … +${cat.entries.size - MAX_ENTRY_LINES} autres",
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp,
                color = StatusColors.DIM,
            )
        }
    }
}

private const val MAX_ENTRY_LINES = 30

private fun statusGlyph(status: StepStatus): String = when (status) {
    StepStatus.CAPTURED -> "✓"
    StepStatus.PARTIAL -> "◐"
    StepStatus.SKIPPED -> "⤫"
    StepStatus.PENDING -> "·"
}

private fun statusColor(status: StepStatus): Color = when (status) {
    StepStatus.CAPTURED -> StatusColors.CAPTURED
    StepStatus.PARTIAL -> StatusColors.PARTIAL
    StepStatus.SKIPPED -> StatusColors.SKIPPED
    StepStatus.PENDING -> StatusColors.PENDING
}

/**
 * Debug-only palette. Hardcoded on purpose : this is a developer diagnostics
 * screen with no proto/design-token counterpart (exempt from the hardcoded-color
 * rule, like the other dev tooling under features/dev).
 */
private object StatusColors {
    val TEXT = Color(0xFFE0E0E0)
    val DIM = Color(0xFF9E9E9E)
    val CAPTURED = Color(0xFF66BB6A)
    val PARTIAL = Color(0xFFFFCA28)
    val SKIPPED = Color(0xFF8D8D8D)
    val PENDING = Color(0xFF7E9CFF)
}
