package com.musubi.eurio.features.dev.capture

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathFillType
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Success
import com.musubi.eurio.ui.theme.Warning

/**
 * Overlay rendu à la place de PhotoGuideOverlay quand un snap est en attente
 * de confirmation. Affiche le crop dans le disque central (même géométrie
 * que le guide ring : rayon = 35 % du côté court). En cas d'échec normalize
 * (cropPath=null), affiche un disque sombre avec un hint "no centered circle".
 *
 * Vue caméra et bannière restent visibles autour — on remplace seulement le
 * contenu du disque ; layout stable, aucun "blink" lors du basculement.
 */
@Composable
fun CaptureSnapRingOverlay(
    cropPath: String?,
    modifier: Modifier = Modifier,
) {
    val ok = cropPath != null
    val ringColor = if (ok) Success else Warning
    BoxWithConstraints(modifier = modifier.fillMaxSize()) {
        // Diamètre du disque = 2 × radius = 2 × 0.35 × min(width, height).
        val short = if (maxWidth < maxHeight) maxWidth else maxHeight
        val diameter = short * 0.70f

        // Couche de dim noir avec un trou circulaire au centre (même path
        // géométrique que PhotoGuideOverlay).
        Canvas(modifier = Modifier.fillMaxSize()) {
            val s = minOf(size.width, size.height)
            val radius = s * 0.35f
            val center = Offset(size.width / 2f, size.height / 2f)
            val path = Path().apply {
                addRect(Rect(0f, 0f, size.width, size.height))
                addOval(
                    Rect(
                        center.x - radius, center.y - radius,
                        center.x + radius, center.y + radius,
                    ),
                )
                fillType = PathFillType.EvenOdd
            }
            drawPath(path, color = Color.Black.copy(alpha = 0.55f))
            drawCircle(
                color = ringColor,
                radius = radius,
                center = center,
                style = Stroke(width = 3.dp.toPx()),
            )
        }

        // Contenu du disque centré.
        Box(
            modifier = Modifier
                .align(Alignment.Center)
                .size(diameter)
                .clip(CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            if (cropPath != null) {
                AsyncImage(
                    model = "file://$cropPath",
                    contentDescription = "Captured crop",
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(Color.Black.copy(alpha = 0.75f))
                        .padding(EurioSpacing.s3),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            text = "▲ NORMALIZE FAILED",
                            style = MonoBadgeStyle,
                            color = Warning,
                        )
                        Text(
                            text = "no centered circle",
                            style = MonoBadgeStyle,
                            color = Warning.copy(alpha = 0.7f),
                        )
                        Text(
                            text = "tap refaire",
                            style = MonoBadgeStyle,
                            color = Color.White.copy(alpha = 0.5f),
                        )
                    }
                }
            }
        }
    }
}
