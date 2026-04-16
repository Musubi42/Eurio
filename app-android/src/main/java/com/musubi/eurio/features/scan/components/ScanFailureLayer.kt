package com.musubi.eurio.features.scan.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Warning
import kotlinx.coroutines.delay

/**
 * Scene parity: docs/design/prototype/scenes/scan-failure.html
 *
 * Warm-gold guide ring still pulsing, plus a glass hint bubble near the
 * bottom of the screen and a tiny "nouvelle tentative dans quelques secondes"
 * caption. Auto-retries via [onRetry] after 3 seconds — tapping anywhere
 * on the layer also retries.
 */
@Composable
fun ScanFailureLayer(
    reason: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    LaunchedEffect(reason) {
        delay(3_000L)
        onRetry()
    }

    val transition = rememberInfiniteTransition(label = "scan-failure-pulse")
    val pulse by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1400, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulse",
    )
    val alpha = 0.55f + (0.85f - 0.55f) * pulse
    val scale = 1.0f + 0.02f * pulse

    Box(
        modifier = modifier
            .fillMaxSize()
            .clickable { onRetry() },
    ) {
        Canvas(
            modifier = Modifier
                .size(280.dp)
                .align(Alignment.Center)
                .scale(scale),
        ) {
            val strokeWidth = 2.dp.toPx()
            val cornerLen = 28.dp.toPx()
            val w = size.width
            val h = size.height
            val color = Warning.copy(alpha = alpha)
            drawLine(color, Offset(0f, 0f), Offset(cornerLen, 0f), strokeWidth)
            drawLine(color, Offset(0f, 0f), Offset(0f, cornerLen), strokeWidth)
            drawLine(color, Offset(w - cornerLen, 0f), Offset(w, 0f), strokeWidth)
            drawLine(color, Offset(w, 0f), Offset(w, cornerLen), strokeWidth)
            drawLine(color, Offset(0f, h - cornerLen), Offset(0f, h), strokeWidth)
            drawLine(color, Offset(0f, h), Offset(cornerLen, h), strokeWidth)
            drawLine(color, Offset(w - cornerLen, h), Offset(w, h), strokeWidth)
            drawLine(color, Offset(w, h - cornerLen), Offset(w, h), strokeWidth)
        }

        AnimatedVisibility(
            visible = true,
            enter = slideInVertically(initialOffsetY = { it / 4 }) + fadeIn(),
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = EurioSpacing.s11),
        ) {
            HintBubble(reason = reason)
        }

        Text(
            text = "NOUVELLE TENTATIVE DANS QUELQUES SECONDES",
            style = EyebrowStyle,
            color = Color.White.copy(alpha = 0.45f),
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = EurioSpacing.s9),
        )
    }
}

@Composable
private fun HintBubble(reason: String) {
    Column(
        modifier = Modifier
            .width(280.dp)
            .clip(RoundedCornerShape(EurioRadii.lg))
            .background(Color.Black.copy(alpha = 0.55f))
            .border(
                width = 1.dp,
                color = Warning.copy(alpha = 0.35f),
                shape = RoundedCornerShape(EurioRadii.lg),
            )
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s4),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = "CONSEIL",
            style = EyebrowStyle,
            color = Warning,
        )
        Box(modifier = Modifier.padding(top = EurioSpacing.s1))
        Text(
            text = reason.ifBlank { "Approche un peu — ou essaie une meilleure lumière." },
            style = MaterialTheme.typography.bodyMedium.copy(fontStyle = FontStyle.Italic),
            color = Color.White,
        )
    }
}
