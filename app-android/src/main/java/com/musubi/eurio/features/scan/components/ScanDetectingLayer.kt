package com.musubi.eurio.features.scan.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
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
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Warning

/**
 * Scene parity: docs/design/prototype/scenes/scan-detecting.html
 *
 * Faster pulse (0.85s) on a warm-gold ring + a linear progress indicator that
 * fills over 1.6s while the ArcFace embedding is computed. The "Extraction
 * de l'empreinte" label sits below the progress bar.
 */
@Composable
fun ScanDetectingLayer(
    modifier: Modifier = Modifier,
) {
    val transition = rememberInfiniteTransition(label = "scan-detecting-pulse")
    val pulse by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 850, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulse",
    )
    val alpha = 0.7f + (1f - 0.7f) * pulse
    val scale = 1.0f + 0.04f * pulse

    Box(modifier = modifier.fillMaxSize()) {
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

        Column(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = EurioSpacing.s12)
                .width(240.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        ) {
            Text(
                text = "Extraction de l'empreinte…",
                style = MaterialTheme.typography.titleSmall,
                color = Color.White.copy(alpha = 0.85f),
            )
            LinearProgressIndicator(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(3.dp)
                    .clip(RoundedCornerShape(2.dp)),
                color = Gold,
                trackColor = Color.White.copy(alpha = 0.12f),
            )
            Text(
                text = "EMBEDDING · 128-D · ON-DEVICE",
                style = EyebrowStyle,
                color = Color.White.copy(alpha = 0.55f),
            )
        }
    }
}
