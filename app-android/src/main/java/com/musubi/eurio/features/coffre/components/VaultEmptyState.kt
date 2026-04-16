package com.musubi.eurio.features.coffre.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.GoldSoft
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.PaperSurface

/**
 * Empty vault state with coin illustration and CTA, matching vault-empty.html.
 */
@Composable
fun VaultEmptyState(
    onScanClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s6, vertical = EurioSpacing.s6),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Spacer(Modifier.height(EurioSpacing.s8))

        CoinIllustration(
            modifier = Modifier.size(220.dp),
        )

        Spacer(Modifier.height(EurioSpacing.s6))

        Text(
            text = "Ton coffre\nattend sa première pièce.",
            style = MaterialTheme.typography.displaySmall.copy(fontStyle = FontStyle.Italic),
            color = Ink,
            textAlign = TextAlign.Center,
        )

        Spacer(Modifier.height(EurioSpacing.s3))

        Text(
            text = "Scanne une pièce euro pour commencer ta collection. Eurio la reconnaît, l'évalue, et la range ici pour toi.",
            style = MaterialTheme.typography.bodyMedium,
            color = Ink500,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = EurioSpacing.s4),
        )

        Spacer(Modifier.height(EurioSpacing.s8))

        Button(
            onClick = onScanClick,
            colors = ButtonDefaults.buttonColors(
                containerColor = Indigo700,
                contentColor = PaperSurface,
            ),
            shape = RoundedCornerShape(EurioRadii.full),
            modifier = Modifier.height(52.dp),
        ) {
            Text(
                text = "Scanner ma première pièce",
                style = MaterialTheme.typography.titleMedium,
            )
        }

        Spacer(Modifier.height(EurioSpacing.s10))
    }
}

@Composable
private fun CoinIllustration(modifier: Modifier = Modifier) {
    Canvas(modifier = modifier) {
        val cx = size.width / 2f
        val cy = size.height / 2f

        // Halo
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(Gold.copy(alpha = 0.28f), Gold.copy(alpha = 0f)),
                center = Offset(cx, cy),
                radius = cx * 0.96f,
            ),
            radius = cx * 0.96f,
            center = Offset(cx, cy),
        )

        // Dashed orbit
        drawCircle(
            color = Indigo700.copy(alpha = 0.1f),
            radius = cx * 0.73f,
            center = Offset(cx, cy),
            style = Stroke(
                width = 1.dp.toPx(),
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(2.dp.toPx(), 4.dp.toPx())),
            ),
        )

        // Ghost coins
        val ghostPositions = listOf(
            Offset(cx * 0.42f, cy * 0.58f) to 14.dp.toPx(),
            Offset(cx * 1.63f, cy * 0.67f) to 11.dp.toPx(),
            Offset(cx * 0.5f, cy * 1.54f) to 10.dp.toPx(),
            Offset(cx * 1.67f, cy * 1.5f) to 13.dp.toPx(),
        )
        for ((offset, r) in ghostPositions) {
            drawCircle(
                color = Indigo700.copy(alpha = 0.28f),
                radius = r,
                center = offset,
            )
        }

        // Main coin shadow
        drawOval(
            color = Ink.copy(alpha = 0.15f),
            topLeft = Offset(cx - 56.dp.toPx() + 4.dp.toPx(), cy - 12.dp.toPx() + 8.dp.toPx()),
            size = androidx.compose.ui.geometry.Size(112.dp.toPx(), 24.dp.toPx()),
        )

        // Main coin
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(GoldSoft, Gold, GoldDeep),
                center = Offset(cx - 12.dp.toPx(), cy - 14.dp.toPx()),
                radius = 58.dp.toPx(),
            ),
            radius = 58.dp.toPx(),
            center = Offset(cx, cy),
        )

        // Inner dashed border
        drawCircle(
            color = GoldDeep.copy(alpha = 0.45f),
            radius = 52.dp.toPx(),
            center = Offset(cx, cy),
            style = Stroke(
                width = 1.dp.toPx(),
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(1.dp.toPx(), 3.dp.toPx())),
            ),
        )
    }
}
