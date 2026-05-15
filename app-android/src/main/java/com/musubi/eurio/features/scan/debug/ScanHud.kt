package com.musubi.eurio.features.scan.debug

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import kotlinx.coroutines.delay

/**
 * Compact heads-up display rendered at the top of the scan screen in debug
 * builds. Lecture seule — never mutates state.
 *
 * Caller is responsible for gating on [com.musubi.eurio.BuildConfig.DEBUG];
 * this composable assumes "should render" once invoked.
 *
 * Tap to fade out temporarily so the underlying scene is visible.
 */
@Composable
fun ScanHud(
    state: ScanHudState,
    modifier: Modifier = Modifier,
) {
    var dimmed by remember { mutableStateOf(false) }
    val alpha by animateFloatAsState(
        targetValue = if (dimmed) 0.1f else 1f,
        animationSpec = tween(durationMillis = 200),
        label = "hudAlpha",
    )
    // Quality badges fade out when no frame was just scored — they'd
    // otherwise display stale numbers from the last detection.
    val isIdle = state.machineState == "Idle"
    val qualityAlpha = if (isIdle || state.lastFrameScore == null) 0.4f else 1f

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s3)
            .alpha(alpha)
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    while (true) {
                        val ev = awaitPointerEvent()
                        if (ev.changes.any { it.pressed }) {
                            dimmed = !dimmed
                            ev.changes.forEach { it.consume() }
                        }
                    }
                }
            },
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
    ) {
        StatePulseRow(state, qualityAlpha)

        if (state.arcfaceTop3.isNotEmpty() ||
            state.timings.totalMs() > 0 ||
            state.bufferCapacity > 0
        ) {
            SecondaryRow(state)
        }
    }
}

@Composable
private fun StatePulseRow(state: ScanHudState, qualityAlpha: Float) {
    var pulse by remember { mutableStateOf(false) }
    LaunchedEffect(state.machineState) {
        pulse = true
        delay(200)
        pulse = false
    }
    val pulseAlpha by animateFloatAsState(
        targetValue = if (pulse) 0.7f else 1f,
        animationSpec = tween(durationMillis = 200),
        label = "statePulse",
    )

    val score = state.lastFrameScore

    Row(
        modifier = Modifier
            .horizontalScroll(rememberScrollState())
            .background(
                color = Color.Black.copy(alpha = 0.55f),
                shape = RoundedCornerShape(EurioRadii.sm),
            )
            .clip(RoundedCornerShape(EurioRadii.sm))
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s1),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        Text(
            text = state.machineState,
            color = Color.White.copy(alpha = pulseAlpha),
            style = MaterialTheme.typography.labelMedium,
        )
        Dot()
        QualityBadge(
            label = "sharp",
            value = score?.let { "${it.sharpnessRaw.toInt()}" } ?: "—",
            pass = score?.passes?.sharpness,
            baseAlpha = qualityAlpha,
        )
        Dot()
        QualityBadge(
            label = "exp",
            value = score?.let { "%.2f".format(it.meanLuminance) } ?: "—",
            pass = score?.passes?.exposure,
            baseAlpha = qualityAlpha,
        )
        Dot()
        QualityBadge(
            label = "comp",
            value = score?.let { "%.2f".format(it.completeness) } ?: "—",
            pass = score?.passes?.completeness,
            baseAlpha = qualityAlpha,
        )
        if (score?.motion != null) {
            Dot()
            QualityBadge(
                label = "mot",
                value = "%.2f".format(score.motion),
                pass = score.passes.motion,
                baseAlpha = qualityAlpha,
            )
        }
        Dot()
        Text(
            text = score?.let { "agg %.2f".format(it.aggregate) } ?: "agg —",
            color = Color.White.copy(alpha = qualityAlpha),
            style = MaterialTheme.typography.labelSmall,
        )
        state.bestFrameIndex?.let {
            Dot()
            Text(
                text = "best #$it",
                color = MaterialTheme.colorScheme.tertiary,
                style = MaterialTheme.typography.labelSmall,
            )
        }
        state.sinceTriggerMs?.let { ms ->
            Dot()
            Text(
                text = "t+${"%.1f".format(ms / 1000f)}s",
                color = Color.White.copy(alpha = qualityAlpha),
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}

@Composable
private fun QualityBadge(
    label: String,
    value: String,
    pass: Boolean?,
    baseAlpha: Float,
) {
    val passMark = when (pass) {
        true -> "✓"
        false -> "✗"
        null -> ""
    }
    val passColor = when (pass) {
        true -> MaterialTheme.colorScheme.tertiary
        false -> MaterialTheme.colorScheme.error
        null -> Color.White
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            text = "$label $value",
            color = Color.White.copy(alpha = baseAlpha),
            style = MaterialTheme.typography.labelSmall,
        )
        if (passMark.isNotEmpty()) {
            Text(
                text = passMark,
                color = passColor.copy(alpha = baseAlpha),
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}

@Composable
private fun SecondaryRow(state: ScanHudState) {
    Row(
        modifier = Modifier
            .horizontalScroll(rememberScrollState())
            .background(
                color = Color.Black.copy(alpha = 0.45f),
                shape = RoundedCornerShape(EurioRadii.sm),
            )
            .clip(RoundedCornerShape(EurioRadii.sm))
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s1),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        state.arcfaceTop3.take(3).forEachIndexed { i, m ->
            if (i > 0) Dot()
            Text(
                text = "${m.className.take(8)} ${"%.2f".format(m.similarity)}",
                color = Color.White,
                style = MaterialTheme.typography.labelSmall,
            )
        }
        val t = state.timings
        if (t.totalMs() > 0) {
            if (state.arcfaceTop3.isNotEmpty()) Dot()
            Text(
                text = "det${t.detectMs} nrm${t.normalizeMs} arc${t.arcfaceMs} scr${t.scoreMs}",
                color = Color.White.copy(alpha = 0.8f),
                style = MaterialTheme.typography.labelSmall,
            )
        }
        if (state.bufferCapacity > 0) {
            if (state.arcfaceTop3.isNotEmpty() || t.totalMs() > 0) Dot()
            Text(
                text = "buf ${state.bufferSize}/${state.bufferCapacity}",
                color = Color.White.copy(alpha = 0.8f),
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}

@Composable
private fun Dot() {
    Text(
        text = "·",
        color = Color.White.copy(alpha = 0.5f),
        style = MaterialTheme.typography.labelSmall,
    )
}

private fun TimingBreakdown.totalMs(): Long =
    detectMs + normalizeMs + arcfaceMs + scoreMs
