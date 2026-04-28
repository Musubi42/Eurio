package com.musubi.eurio.features.scan.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.musubi.eurio.features.scan.ScanViewModel
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Success
import com.musubi.eurio.ui.theme.Warning

/**
 * Photo-mode debug result. Replaces the 3D viewer + AcceptedCard flow when a
 * snap completes. Shows the exact masked square that ArcFace received, plus
 * the top-K matches and the decision reason — so the user can diagnose why
 * the model is returning what it returns.
 */
@Composable
fun PhotoSnapResultLayer(
    snap: ScanViewModel.PhotoSnap,
    modifier: Modifier = Modifier,
) {
    val normalizeFailed = snap.cropPath == null
    val accent = when {
        normalizeFailed -> Warning
        snap.accepted -> Success
        else -> Warning
    }
    Column(
        modifier = modifier
            .fillMaxSize()
            .background(Ink)
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s4),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        Spacer(Modifier.height(EurioSpacing.s8))
        Text(
            text = when {
                normalizeFailed -> "▲ NORMALIZE FAILED"
                snap.accepted -> "● ACCEPTED"
                else -> "■ REJECTED"
            },
            style = MonoBadgeStyle,
            color = accent,
        )

        // The crop the model actually saw. Aspect ratio is 1:1 (square).
        // When normalization failed there is no crop — render a placeholder
        // tile with a brief retry hint instead.
        Box(
            modifier = Modifier
                .fillMaxWidth(0.85f)
                .aspectRatio(1f)
                .clip(RoundedCornerShape(EurioRadii.sm))
                .background(Color.Black.copy(alpha = 0.55f))
                .border(
                    width = 1.dp,
                    color = accent.copy(alpha = 0.45f),
                    shape = RoundedCornerShape(EurioRadii.sm),
                ),
            contentAlignment = Alignment.Center,
        ) {
            if (normalizeFailed) {
                Text(
                    text = "no centered circle\nrecadre + retry",
                    style = MonoBadgeStyle,
                    color = Warning,
                )
            } else {
                AsyncImage(
                    model = "file://${snap.cropPath}",
                    contentDescription = "ArcFace input",
                    modifier = Modifier.fillMaxSize(),
                )
            }
        }

        Text(
            text = if (normalizeFailed) "no normalized crop · ArcFace skipped"
                else "${snap.cropSize}×${snap.cropSize} px · black mask (Hough)",
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.5f),
        )

        // Decision + scores panel.
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(EurioRadii.sm))
                .background(Color.Black.copy(alpha = 0.55f))
                .border(
                    width = 1.dp,
                    color = accent.copy(alpha = 0.25f),
                    shape = RoundedCornerShape(EurioRadii.sm),
                )
                .padding(EurioSpacing.s3),
            verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
        ) {
            Text(
                text = snap.decisionReason,
                style = MonoBadgeStyle,
                color = accent,
            )
            if (snap.matches.isEmpty()) {
                Text(
                    text = "no matches",
                    style = MonoBadgeStyle,
                    color = Color.White.copy(alpha = 0.4f),
                )
            } else {
                snap.matches.take(5).forEachIndexed { i, m ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                    ) {
                        Text(
                            "${i + 1}.",
                            style = MonoBadgeStyle,
                            color = Color.White.copy(alpha = 0.45f),
                        )
                        Text(
                            text = m.className,
                            style = MonoBadgeStyle,
                            color = if (i == 0) Gold else Color.White.copy(alpha = 0.85f),
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            text = "%.3f".format(m.similarity),
                            style = MonoBadgeStyle,
                            color = if (i == 0) Gold else Color.White.copy(alpha = 0.85f),
                        )
                    }
                }
            }
        }

        // The reset action lives in the debug bottom strip — SNAP becomes
        // RESET while a result is on screen and clears the snap (without
        // triggering a new one), keeping a single control point and avoiding
        // a double-button conflict at the bottom edge.
    }
}
