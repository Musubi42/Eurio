package com.musubi.eurio.features.scan.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.musubi.eurio.data.repository.CoinViewData
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold100
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.Success

/**
 * Scene parity: docs/design/prototype/scenes/scan-matched.html
 *
 * Bottom sheet overlay (~75% of screen height max, anchors to bottom).
 * Slides in from the bottom with a 0.55s spring, and is dismissible via a
 * downward swipe on the sheet itself.
 *
 * Structure:
 *  - gold disc thumbnail (Coil AsyncImage, falls back to a gradient disc)
 *  - eyebrow: country + face value
 *  - italic display title (coin name)
 *  - 3 inline badges: confidence %, issue type, rarity
 *  - 2 CTAs: "Voir la fiche" (ghost) + "Ajouter au coffre" (gold)
 */
@Composable
fun ScanAcceptedCard(
    coin: CoinViewData,
    confidence: Float,
    onDetail: () -> Unit,
    onAddToVault: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var dragOffset by remember { mutableStateOf(0f) }
    val dragState = rememberDraggableState { delta ->
        dragOffset = (dragOffset + delta).coerceAtLeast(0f)
    }

    AnimatedVisibility(
        visible = true,
        enter = slideInVertically(
            initialOffsetY = { it },
            animationSpec = spring(
                dampingRatio = Spring.DampingRatioLowBouncy,
                stiffness = Spring.StiffnessLow,
            ),
        ),
        exit = slideOutVertically(targetOffsetY = { it }),
        modifier = modifier,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .fillMaxHeight(0.75f),
            contentAlignment = Alignment.BottomCenter,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(
                        RoundedCornerShape(
                            topStart = EurioRadii.r2xl,
                            topEnd = EurioRadii.r2xl,
                            bottomStart = EurioRadii.xs,
                            bottomEnd = EurioRadii.xs,
                        ),
                    )
                    .background(PaperSurface)
                    .draggable(
                        state = dragState,
                        orientation = Orientation.Vertical,
                        onDragStopped = {
                            if (dragOffset > 120f) onDismiss()
                            dragOffset = 0f
                        },
                    )
                    .padding(
                        horizontal = EurioSpacing.s5,
                        vertical = EurioSpacing.s5,
                    ),
                verticalArrangement = Arrangement.spacedBy(EurioSpacing.s4),
            ) {
                // Grab handle
                Box(
                    modifier = Modifier
                        .align(Alignment.CenterHorizontally)
                        .width(40.dp)
                        .height(4.dp)
                        .clip(CircleShape)
                        .background(Ink.copy(alpha = 0.12f)),
                )

                // Head row: thumb + meta
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s4),
                ) {
                    CoinThumb(imageUrl = coin.imageObverseUrl, contentDescription = coin.nameFr)

                    Column(modifier = Modifier.fillMaxWidth()) {
                        Text(
                            text = "${coin.country.uppercase()} · ${formatFaceValue(coin.faceValueCents)}",
                            style = MaterialTheme.typography.labelSmall,
                            color = Ink500,
                        )
                        Spacer(Modifier.height(EurioSpacing.s1))
                        Text(
                            text = coin.nameFr,
                            style = MaterialTheme.typography.headlineMedium.copy(fontStyle = FontStyle.Italic),
                            color = Ink,
                        )
                        Spacer(Modifier.height(EurioSpacing.s1))
                        Text(
                            text = coin.year.toString(),
                            style = MaterialTheme.typography.bodySmall,
                            color = Ink400,
                        )
                    }
                }

                // Badge row: confidence + issue type
                Row(
                    horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                ) {
                    MiniBadge(
                        text = "${(confidence * 100).toInt()} %",
                        background = Success.copy(alpha = 0.15f),
                        foreground = Success,
                    )
                    MiniBadge(
                        text = if (coin.issueType == "commemo") "Commémorative" else "Circulation",
                        background = Gold100,
                        foreground = GoldDeep,
                    )
                }

                Spacer(Modifier.height(EurioSpacing.s2))

                // Actions
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
                ) {
                    OutlinedButton(
                        onClick = onDetail,
                        modifier = Modifier.weight(1f),
                        shape = RoundedCornerShape(EurioRadii.full),
                    ) {
                        Text("Voir la fiche")
                    }
                    Button(
                        onClick = onAddToVault,
                        modifier = Modifier.weight(1f),
                        shape = RoundedCornerShape(EurioRadii.full),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = Gold,
                            contentColor = Ink,
                        ),
                    ) {
                        Text("Ajouter au coffre")
                    }
                }
            }
        }
    }
}

@Composable
private fun CoinThumb(imageUrl: String?, contentDescription: String) {
    Box(
        modifier = Modifier
            .size(84.dp)
            .clip(CircleShape)
            .background(
                Brush.radialGradient(
                    colors = listOf(Gold100, Gold, GoldDeep),
                ),
            )
            .border(1.dp, Gold.copy(alpha = 0.4f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        if (imageUrl != null) {
            AsyncImage(
                model = imageUrl,
                contentDescription = contentDescription,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(CircleShape),
            )
        }
    }
}

@Composable
private fun MiniBadge(text: String, background: Color, foreground: Color) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(background)
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s1),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = foreground,
        )
    }
}

private fun formatFaceValue(cents: Int): String = when {
    cents >= 100 -> "${cents / 100} €"
    else -> "$cents c"
}
