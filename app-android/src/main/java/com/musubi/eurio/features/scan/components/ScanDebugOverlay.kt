package com.musubi.eurio.features.scan.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Success
import com.musubi.eurio.ui.theme.Warning

/**
 * Snapshot of per-frame runtime data rendered in the debug overlay.
 * The view model populates this once per analyzer callback; when debug mode
 * is disabled the overlay is simply not composed.
 */
data class DebugViewData(
    val bbox: BboxInfo? = null,
    val top5: List<DebugMatch> = emptyList(),
    val deltaTop1Top2: Float = 0f,
    val latencies: Latencies = Latencies(),
    val runtime: Runtime = Runtime(),
    val histogram: Histogram = Histogram(),
) {
    data class BboxInfo(
        val left: Float,
        val top: Float,
        val right: Float,
        val bottom: Float,
        val frameWidth: Int,
        val frameHeight: Int,
        val label: String,
    )

    data class DebugMatch(val className: String, val score: Float)

    data class Latencies(
        val detMs: Long = 0,
        val embMs: Long = 0,
        val knnMs: Long = 0,
        val totalMs: Long = 0,
        val fps: Float = 0f,
    )

    data class Runtime(
        val model: String = "—",
        val embeddings: Int = 0,
        val hash: String = "—",
        val camera: String = "—",
        val deviceTempC: Int = 0,
    )

    data class Histogram(
        val okCount: Int = 0,
        val failCount: Int = 0,
        val skipCount: Int = 0,
        val window: Int = 10,
    )
}

/**
 * Scene parity: docs/design/prototype/scenes/scan-debug.html
 *
 * 5 monospace panels + a 7-button tool strip. Gated by [ScanViewModel.debugMode]
 * at the call site — this composable assumes it should draw when invoked.
 */
@Composable
fun ScanDebugOverlay(
    data: DebugViewData,
    onDump: () -> Unit,
    onDumps: () -> Unit,
    onReplay: () -> Unit,
    onFreeze: () -> Unit,
    onForce: () -> Unit,
    onEmbed: () -> Unit,
    onStats: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier.fillMaxSize()) {
        // 1. YOLO bbox (Canvas coordinates mapped to composable size)
        data.bbox?.let { BboxOverlay(it) }

        // 5. Convergence histogram (left, top)
        DebugPanel(
            title = "Converge",
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(top = EurioSpacing.s10, start = EurioSpacing.s3)
                .width(92.dp),
        ) {
            HistBar("Ok", data.histogram.okCount, data.histogram.window, Success)
            HistBar("Fail", data.histogram.failCount, data.histogram.window, Warning)
            HistBar("Skip", data.histogram.skipCount, data.histogram.window, Color.White.copy(alpha = 0.35f))
        }

        // 3. Latencies (right, top)
        DebugPanel(
            title = "Latency",
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(top = EurioSpacing.s10, end = EurioSpacing.s3)
                .width(118.dp),
        ) {
            KvRow("det", "${data.latencies.detMs}ms")
            KvRow("emb", "${data.latencies.embMs}ms")
            KvRow("knn", "${data.latencies.knnMs}ms")
            KvRow("tot", "${data.latencies.totalMs}ms")
            KvRow("fps", "%.1f".format(data.latencies.fps))
        }

        // 4. Runtime context (right, above tools)
        DebugPanel(
            title = "Runtime",
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(bottom = 210.dp, end = EurioSpacing.s3)
                .width(170.dp),
        ) {
            KvRow("model", data.runtime.model)
            KvRow("embeds", data.runtime.embeddings.toString())
            KvRow("hash", data.runtime.hash)
            KvRow("cam", data.runtime.camera)
            KvRow("device", "${data.runtime.deviceTempC}°C")
        }

        // 2. Top-5 matches (bottom, above tool strip)
        DebugPanel(
            title = "Top-5 kNN · cosine",
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(
                    bottom = 82.dp,
                    start = EurioSpacing.s3,
                    end = EurioSpacing.s3,
                )
                .fillMaxWidth(),
        ) {
            data.top5.take(5).forEachIndexed { i, m ->
                Top5Row(i + 1, m, highlight = i == 0)
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = EurioSpacing.s2,
                        vertical = EurioSpacing.s1,
                    ),
            ) {
                Text(
                    text = "Δ (top1 − top2) = %.3f".format(data.deltaTop1Top2),
                    style = MonoBadgeStyle,
                    color = Warning,
                )
            }
        }

        // Tools strip (bottom)
        DebugToolsStrip(
            onDump = onDump,
            onDumps = onDumps,
            onReplay = onReplay,
            onFreeze = onFreeze,
            onForce = onForce,
            onEmbed = onEmbed,
            onStats = onStats,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(
                    start = EurioSpacing.s3,
                    end = EurioSpacing.s3,
                    bottom = EurioSpacing.s4,
                )
                .fillMaxWidth(),
        )
    }
}

@Composable
private fun BboxOverlay(bbox: DebugViewData.BboxInfo) {
    Canvas(modifier = Modifier.fillMaxSize()) {
        if (bbox.frameWidth <= 0) return@Canvas
        val scaleX = size.width / bbox.frameWidth
        val scaleY = size.height / bbox.frameHeight
        drawRect(
            color = Success,
            topLeft = Offset(bbox.left * scaleX, bbox.top * scaleY),
            size = Size((bbox.right - bbox.left) * scaleX, (bbox.bottom - bbox.top) * scaleY),
            style = Stroke(width = 1.5.dp.toPx()),
        )
    }
}

@Composable
private fun DebugPanel(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.sm))
            .background(Color.Black.copy(alpha = 0.72f))
            .border(
                width = 1.dp,
                color = Success.copy(alpha = 0.25f),
                shape = RoundedCornerShape(EurioRadii.sm),
            ),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(Success.copy(alpha = 0.15f))
                .padding(horizontal = EurioSpacing.s2, vertical = EurioSpacing.s1),
        ) {
            Text(
                text = title.uppercase(),
                style = MonoBadgeStyle,
                color = Success,
            )
        }
        Column(
            modifier = Modifier.padding(
                horizontal = EurioSpacing.s2,
                vertical = EurioSpacing.s1,
            ),
        ) {
            content()
        }
    }
}

@Composable
private fun KvRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.5f),
        )
        Text(
            text = value,
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.92f),
        )
    }
}

@Composable
private fun HistBar(label: String, count: Int, window: Int, color: Color) {
    val filled = count.coerceIn(0, window)
    val empty = window - filled
    val track = "█".repeat(filled) + "░".repeat(empty)
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label.uppercase(),
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.5f),
        )
        Text(
            text = track,
            style = MonoBadgeStyle,
            color = color,
        )
    }
}

@Composable
private fun Top5Row(rank: Int, match: DebugViewData.DebugMatch, highlight: Boolean) {
    val labelColor = if (highlight) Gold else Color.White.copy(alpha = 0.85f)
    val scoreColor = if (highlight) Gold else Warning
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s2, vertical = EurioSpacing.s1),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "$rank.",
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.45f),
        )
        Text(
            text = match.className,
            style = MonoBadgeStyle,
            color = labelColor,
            modifier = Modifier.weight(1f),
        )
        Text(
            text = "%.3f".format(match.score),
            style = MonoBadgeStyle,
            color = scoreColor,
        )
    }
}

@Composable
private fun DebugToolsStrip(
    onDump: () -> Unit,
    onDumps: () -> Unit,
    onReplay: () -> Unit,
    onFreeze: () -> Unit,
    onForce: () -> Unit,
    onEmbed: () -> Unit,
    onStats: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.sm))
            .background(Color.Black.copy(alpha = 0.78f))
            .border(
                width = 1.dp,
                color = Success.copy(alpha = 0.25f),
                shape = RoundedCornerShape(EurioRadii.sm),
            )
            .padding(EurioSpacing.s1),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
    ) {
        ToolButton("⬇", "Dump", onDump, modifier = Modifier.weight(1f))
        ToolButton("▦", "Dumps", onDumps, modifier = Modifier.weight(1f))
        ToolButton("↻", "Replay", onReplay, modifier = Modifier.weight(1f))
        ToolButton("⏸", "Freeze", onFreeze, modifier = Modifier.weight(1f))
        ToolButton("◎", "Force", onForce, modifier = Modifier.weight(1f))
        ToolButton("⧖", "Embed", onEmbed, modifier = Modifier.weight(1f))
        ToolButton("▤", "Stats", onStats, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun ToolButton(
    glyph: String,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(3.dp))
            .background(Color.White.copy(alpha = 0.04f))
            .border(
                width = 1.dp,
                color = Color.White.copy(alpha = 0.08f),
                shape = RoundedCornerShape(3.dp),
            )
            .clickable(onClick = onClick)
            .padding(vertical = EurioSpacing.s1, horizontal = EurioSpacing.s1),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
    ) {
        Text(
            text = glyph,
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.92f),
        )
        Text(
            text = label,
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.82f),
        )
    }
}
