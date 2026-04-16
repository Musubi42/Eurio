package com.musubi.eurio.features.scan.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing

/**
 * Scene parity: docs/design/prototype/scenes/scan-idle.html
 *
 * L-corner guide ring (280dp square, 4 brackets of ~26dp with 1.6dp stroke)
 * plus a bottom hint pill. The guide pulses between 0.55 and 0.9 opacity and
 * scales 1.00 → 1.03 every 2.2s, matching the proto keyframe.
 */
@Composable
fun ScanIdleLayer(
    modifier: Modifier = Modifier,
    hint: String = "En attente — centre la pièce dans le cadre",
) {
    val transition = rememberInfiniteTransition(label = "scan-idle-pulse")
    val pulse by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 2200, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulse",
    )
    val alpha = 0.55f + (0.9f - 0.55f) * pulse
    val scale = 1.0f + 0.03f * pulse

    Box(modifier = modifier.fillMaxSize()) {
        // Guide ring — 4 L-corner brackets
        Canvas(
            modifier = Modifier
                .size(280.dp)
                .align(Alignment.Center)
                .scale(scale),
        ) {
            val strokeWidth = 1.6.dp.toPx()
            val cornerLen = 26.dp.toPx()
            val w = size.width
            val h = size.height
            val color = Color.White.copy(alpha = 0.85f * alpha)

            // Top-left: horizontal top + vertical left
            drawLine(color, Offset(0f, 0f), Offset(cornerLen, 0f), strokeWidth)
            drawLine(color, Offset(0f, 0f), Offset(0f, cornerLen), strokeWidth)
            // Top-right
            drawLine(color, Offset(w - cornerLen, 0f), Offset(w, 0f), strokeWidth)
            drawLine(color, Offset(w, 0f), Offset(w, cornerLen), strokeWidth)
            // Bottom-left
            drawLine(color, Offset(0f, h - cornerLen), Offset(0f, h), strokeWidth)
            drawLine(color, Offset(0f, h), Offset(cornerLen, h), strokeWidth)
            // Bottom-right
            drawLine(color, Offset(w - cornerLen, h), Offset(w, h), strokeWidth)
            drawLine(color, Offset(w, h - cornerLen), Offset(w, h), strokeWidth)
        }

        // Hint pill — bottom
        HintPill(
            text = hint,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = EurioSpacing.s12),
        )
    }
}

@Composable
private fun HintPill(text: String, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(Color.Black.copy(alpha = 0.55f))
            .border(
                width = 1.dp,
                color = Color.White.copy(alpha = 0.1f),
                shape = RoundedCornerShape(EurioRadii.full),
            )
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s3),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        Box(
            modifier = Modifier
                .size(7.dp)
                .clip(CircleShape)
                .background(Color.White.copy(alpha = 0.92f)),
        )
        Text(
            text = text,
            style = MaterialTheme.typography.bodySmall,
            color = Color.White.copy(alpha = 0.92f),
        )
    }
}
