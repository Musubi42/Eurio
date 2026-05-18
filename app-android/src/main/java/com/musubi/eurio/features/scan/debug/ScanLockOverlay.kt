package com.musubi.eurio.features.scan.debug

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import com.musubi.eurio.BuildConfig
import com.musubi.eurio.domain.scan.ScanState
import com.musubi.eurio.features.scan.components.DebugViewData
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.collectLatest

/**
 * Graphical overlay layered above `CameraPreview` and below `ScanHud` —
 * spatial complement to the textual HUD. Draws the live bbox, the AF metering
 * region during acquire, a halo while locked, and a red abort flash.
 *
 * Mapping note: bbox coords from [DebugViewData.BboxInfo] are in analysis-frame
 * pixel space. We normalize against `frameWidth` / `frameHeight` and scale to
 * the Canvas size. This assumes the analysis frame and the preview share
 * aspect ratio (typical on Pixel 9a in portrait). Slight misalignment is
 * acceptable — this is a debug aid, not a production AR overlay.
 *
 * Gated `BuildConfig.DEBUG` so it disappears from release builds.
 */
@Composable
fun ScanLockOverlay(
    bbox: DebugViewData.BboxInfo?,
    shadowState: ScanState,
    abortEvents: SharedFlow<AbortEvent>,
    modifier: Modifier = Modifier,
    regionExpansion: Float = 0.12f,
) {
    if (!BuildConfig.DEBUG) return

    val phase = shadowState.phase()

    val primaryColor = MaterialTheme.colorScheme.primary
    val secondaryColor = MaterialTheme.colorScheme.secondary
    val tertiaryColor = MaterialTheme.colorScheme.tertiary
    val errorColor = MaterialTheme.colorScheme.error
    val bboxColor = when (phase) {
        OverlayPhase.Detecting -> tertiaryColor
        OverlayPhase.Acquiring, OverlayPhase.Locked -> primaryColor
        OverlayPhase.Identifying -> secondaryColor
        OverlayPhase.Failed -> errorColor
        OverlayPhase.Idle -> Color.Transparent
    }

    val pulseTransition = rememberInfiniteTransition(label = "lockPulse")
    val pulse by pulseTransition.animateFloat(
        initialValue = 0.5f,
        targetValue = 1.0f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 600),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "lockPulseAlpha",
    )

    var flashAlpha by remember { mutableStateOf(0f) }
    var flashBbox by remember { mutableStateOf<DebugViewData.BboxInfo?>(null) }
    LaunchedEffect(abortEvents) {
        abortEvents.collectLatest { ev ->
            val b = ev.lastBbox
            flashBbox = if (b != null && ev.frameWidth > 0 && ev.frameHeight > 0) {
                DebugViewData.BboxInfo(
                    left = b.left, top = b.top, right = b.right, bottom = b.bottom,
                    frameWidth = ev.frameWidth, frameHeight = ev.frameHeight,
                    label = ev.reason,
                )
            } else null
            flashAlpha = 1f
            val steps = 10
            val stepMs = 20L
            repeat(steps) {
                flashAlpha -= 1f / steps
                delay(stepMs)
            }
            flashAlpha = 0f
        }
    }

    val density = LocalDensity.current
    val strokeThin = with(density) { 1.dp.toPx() }
    val strokeMedium = with(density) { 2.dp.toPx() }
    val strokeThick = with(density) { 3.dp.toPx() }
    val corner = with(density) { 8.dp.toPx() }

    Canvas(modifier = modifier) {
        if (bbox != null && bbox.frameWidth > 0 && bbox.frameHeight > 0) {
            val rect = mapBbox(bbox, size)
            val stroke = Stroke(
                width = if (phase == OverlayPhase.Locked) strokeThick else strokeMedium,
            )
            val alpha = if (phase == OverlayPhase.Acquiring) pulse else 1f

            drawRoundRect(
                color = bboxColor.copy(alpha = alpha),
                topLeft = rect.topLeft,
                size = rect.size,
                cornerRadius = CornerRadius(corner, corner),
                style = stroke,
            )
            if (phase == OverlayPhase.Locked) {
                drawRoundRect(
                    color = bboxColor.copy(alpha = 0.08f),
                    topLeft = rect.topLeft,
                    size = rect.size,
                    cornerRadius = CornerRadius(corner, corner),
                )
            }

            if (phase == OverlayPhase.Acquiring) {
                val af = rect.expand(regionExpansion).clipTo(size)
                drawRoundRect(
                    color = tertiaryColor.copy(alpha = pulse),
                    topLeft = af.topLeft,
                    size = af.size,
                    cornerRadius = CornerRadius(corner, corner),
                    style = Stroke(
                        width = strokeThin,
                        pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 8f)),
                    ),
                )
            }

            if (phase == OverlayPhase.Acquiring || phase == OverlayPhase.Locked ||
                phase == OverlayPhase.Identifying
            ) {
                val cx = rect.topLeft.x + rect.size.width / 2f
                val cy = rect.topLeft.y + rect.size.height / 2f
                val r = maxOf(rect.size.width, rect.size.height) * 0.6f
                val haloAlpha = when (phase) {
                    OverlayPhase.Acquiring -> pulse
                    OverlayPhase.Identifying -> 0.5f + 0.5f * pulse
                    else -> 0.85f
                }
                drawCircle(
                    color = bboxColor.copy(alpha = haloAlpha),
                    radius = r,
                    center = Offset(cx, cy),
                    style = Stroke(width = strokeMedium),
                )
            }
        }

        val fb = flashBbox
        if (flashAlpha > 0f && fb != null && fb.frameWidth > 0 && fb.frameHeight > 0) {
            val rect = mapBbox(fb, size)
            drawRoundRect(
                color = errorColor.copy(alpha = flashAlpha),
                topLeft = rect.topLeft,
                size = rect.size,
                cornerRadius = CornerRadius(corner, corner),
                style = Stroke(width = strokeThick),
            )
        }
    }
}

private enum class OverlayPhase { Idle, Detecting, Acquiring, Locked, Identifying, Failed }

/**
 * Map the shadow state machine to one visual phase. Sub-states that
 * differ semantically but share a render (eg. `Idle` and `Accepted`
 * both hide the overlay because the sheet is on top) collapse here.
 */
private fun ScanState.phase(): OverlayPhase = when (this) {
    ScanState.Idle -> OverlayPhase.Idle
    ScanState.Detecting -> OverlayPhase.Detecting
    is ScanState.Locking -> OverlayPhase.Acquiring
    is ScanState.Capturing -> OverlayPhase.Locked
    is ScanState.Identifying -> OverlayPhase.Identifying
    is ScanState.Accepted -> OverlayPhase.Idle  // sheet covers the canvas
    is ScanState.Aborted -> OverlayPhase.Failed
}

private data class MappedRect(val topLeft: Offset, val size: Size) {
    fun expand(margin: Float): MappedRect {
        val mx = size.width * margin
        val my = size.height * margin
        return MappedRect(
            topLeft = Offset(topLeft.x - mx, topLeft.y - my),
            size = Size(size.width + 2 * mx, size.height + 2 * my),
        )
    }

    fun clipTo(canvas: Size): MappedRect {
        val x = topLeft.x.coerceIn(0f, canvas.width)
        val y = topLeft.y.coerceIn(0f, canvas.height)
        val right = (topLeft.x + size.width).coerceIn(0f, canvas.width)
        val bottom = (topLeft.y + size.height).coerceIn(0f, canvas.height)
        return MappedRect(
            Offset(x, y),
            Size((right - x).coerceAtLeast(0f), (bottom - y).coerceAtLeast(0f)),
        )
    }
}

private fun mapBbox(b: DebugViewData.BboxInfo, canvas: Size): MappedRect {
    if (b.frameWidth <= 0 || b.frameHeight <= 0) {
        return MappedRect(Offset.Zero, Size.Zero)
    }
    val sx = canvas.width / b.frameWidth.toFloat()
    val sy = canvas.height / b.frameHeight.toFloat()
    val left = b.left * sx
    val top = b.top * sy
    val width = (b.right - b.left) * sx
    val height = (b.bottom - b.top) * sy
    return MappedRect(Offset(left, top), Size(width, height))
}
