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
 * 5 monospace panels + a single-button tool strip (Record). Gated by
 * [ScanViewModel.debugMode] at the call site — this composable assumes it
 * should draw when invoked.
 */
@Composable
fun ScanDebugOverlay(
    data: DebugViewData,
    recording: Boolean,
    recordedFrameCount: Int,
    photoMode: Boolean,
    hasSnapResult: Boolean,
    captureMode: Boolean,
    onRecordToggle: () -> Unit,
    onPhotoToggle: () -> Unit,
    onSnap: () -> Unit,
    onReset: () -> Unit,
    onCaptureToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier.fillMaxSize()) {
        // Capture mode hides every ArcFace-debug panel — those metrics are
        // misleading during golden-set capture (the model is intentionally
        // broken). Only the bottom tools strip stays.
        if (!captureMode) {
            ArcFaceDebugPanels(data = data)
        }

        // Tools strip (bottom): record | photo | snap-or-reset | capture.
        // The middle button is contextual: "snap" when the user is framing,
        // "reset" once a snap result is on screen — taps "reset" → live
        // preview returns (camera was kept warm), user re-frames, then taps
        // "snap" again. Splitting these two actions stops the previous
        // single-button flow that re-snapped immediately on tap, before
        // AF/AE could converge.
        DebugToolsStrip(
            recording = recording,
            recordedFrameCount = recordedFrameCount,
            photoMode = photoMode,
            hasSnapResult = hasSnapResult,
            captureMode = captureMode,
            onRecordToggle = onRecordToggle,
            onPhotoToggle = onPhotoToggle,
            onSnap = onSnap,
            onReset = onReset,
            onCaptureToggle = onCaptureToggle,
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
private fun ArcFaceDebugPanels(data: DebugViewData) {
    Box(modifier = Modifier.fillMaxSize()) {
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
    }
}

/**
 * Photo-mode guide circle, drawn on top of the camera preview. The diameter
 * matches `CoinAnalyzer.photoCropDiameterRatio` (70% of the short side) and
 * acts purely as a placement hint — the actual crop is determined by Hough
 * in [com.musubi.eurio.ml.SnapNormalizer], which tightly recenters on the
 * detected coin regardless of how the user framed it inside the guide.
 *
 * The ring color reflects the analyzer's live Hough probe (5 fps): green
 * when a centered circle is found (a SNAP now would normalize successfully)
 * and a dim default otherwise. The user gets immediate visual confirmation
 * that the framing is good without having to take the snap to find out.
 */
@Composable
fun PhotoGuideOverlay(
    circleFound: Boolean,
    modifier: Modifier = Modifier,
) {
    Canvas(modifier = modifier.fillMaxSize()) {
        val short = minOf(size.width, size.height)
        val radius = short * 0.35f
        val center = Offset(size.width / 2f, size.height / 2f)

        // Dim the background with an even-odd path: full screen rect minus the disk.
        val path = androidx.compose.ui.graphics.Path().apply {
            addRect(androidx.compose.ui.geometry.Rect(0f, 0f, size.width, size.height))
            addOval(androidx.compose.ui.geometry.Rect(
                center.x - radius, center.y - radius,
                center.x + radius, center.y + radius,
            ))
            fillType = androidx.compose.ui.graphics.PathFillType.EvenOdd
        }
        drawPath(path, color = Color.Black.copy(alpha = 0.55f))
        // Disk outline — green when ready to snap, gold (default) otherwise.
        // The stroke is also slightly thicker in the "ready" state so the
        // signal is legible at a glance, not just by hue.
        val ringColor = if (circleFound) Success else Gold.copy(alpha = 0.55f)
        val ringStroke = if (circleFound) 3.dp.toPx() else 2.dp.toPx()
        drawCircle(
            color = ringColor,
            radius = radius,
            center = center,
            style = Stroke(width = ringStroke),
        )
    }
}

/**
 * Top-center mode switch shown whenever debug mode is on. Splits the debug
 * UI into two disjoint experiences: the full scan inspector (panels + bbox +
 * tools) and the clean 3D coin carousel (just the viewer + a bottom nav).
 */
@Composable
fun ScanDebugModeToggle(
    carouselActive: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.sm))
            .background(Color.Black.copy(alpha = 0.78f))
            .border(
                width = 1.dp,
                color = Success.copy(alpha = 0.45f),
                shape = RoundedCornerShape(EurioRadii.sm),
            )
            .clickable(onClick = onClick)
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s2),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = if (carouselActive) "Scan coin debug" else "3D coin carrousel",
            style = MonoBadgeStyle,
            color = Success,
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
    recording: Boolean,
    recordedFrameCount: Int,
    photoMode: Boolean,
    hasSnapResult: Boolean,
    captureMode: Boolean,
    onRecordToggle: () -> Unit,
    onPhotoToggle: () -> Unit,
    onSnap: () -> Unit,
    onReset: () -> Unit,
    onCaptureToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        DebugStripButton(
            glyph = if (recording) "■" else "●",
            label = if (recording) "stop" else "rec",
            badge = if (recording || recordedFrameCount > 0) "$recordedFrameCount" else null,
            accent = if (recording) Warning else Success,
            onClick = onRecordToggle,
            modifier = Modifier.weight(1f),
        )
        DebugStripButton(
            glyph = "📷",
            label = if (photoMode) "photo on" else "photo",
            accent = if (photoMode) Gold else Success,
            onClick = onPhotoToggle,
            // Capture mode owns photoMode internally — disable manual photo toggle.
            enabled = !captureMode,
            modifier = Modifier.weight(1f),
        )
        DebugStripButton(
            glyph = if (hasSnapResult) "↻" else "📸",
            label = when {
                hasSnapResult -> "reset"
                else -> "snap"
            },
            accent = if (photoMode) Gold else Color.White.copy(alpha = 0.25f),
            enabled = photoMode,
            onClick = if (hasSnapResult) onReset else onSnap,
            modifier = Modifier.weight(1f),
        )
        DebugStripButton(
            glyph = "🎯",
            label = if (captureMode) "capture on" else "capture",
            accent = if (captureMode) Gold else Success,
            onClick = onCaptureToggle,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun DebugStripButton(
    glyph: String,
    label: String,
    accent: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    badge: String? = null,
    enabled: Boolean = true,
) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.sm))
            .background(Color.Black.copy(alpha = if (enabled) 0.78f else 0.4f))
            .border(
                width = 1.dp,
                color = accent.copy(alpha = if (enabled) 0.45f else 0.15f),
                shape = RoundedCornerShape(EurioRadii.sm),
            )
            .let { if (enabled) it.clickable(onClick = onClick) else it }
            .padding(horizontal = EurioSpacing.s2, vertical = EurioSpacing.s2),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = glyph, style = MonoBadgeStyle, color = accent)
        Text(
            text = label,
            style = MonoBadgeStyle,
            color = accent,
            modifier = Modifier.weight(1f),
        )
        if (badge != null) {
            Text(
                text = badge,
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.7f),
            )
        }
    }
}

