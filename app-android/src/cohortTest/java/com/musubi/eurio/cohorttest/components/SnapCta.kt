package com.musubi.eurio.cohorttest.components

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Indigo600
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.Success

/**
 * Bottom-area helper text + the Snap pill button.
 *
 * Behavior — and the bug fix that motivated this refactor:
 *   - When [detected] = false, the button is disabled with the label
 *     "Vise une pièce…" and the helper reads "Pose la pièce, vise dans
 *     le cercle." Tapping does nothing.
 *   - When [detected] = true (Hough probe found a centered circle), the
 *     button enables, label flips to "Snap", helper turns success-green
 *     and reads "Pièce détectée. Tape pour capturer."
 *   - When [awaiting] = true, the button is disabled and label reads
 *     "Analyse…" (the snap was sent, ArcFace is running).
 *
 * The keyboard-matched-as-coin bug is impossible because [onSnap] is
 * gated on `detected && !awaiting`.
 */
@Composable
fun SnapCta(
    detected: Boolean,
    awaiting: Boolean,
    onSnap: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val helper = when {
        awaiting -> "Analyse en cours…" to Ink500
        detected -> "Pièce détectée. Tape pour capturer." to Success
        else -> "Pose la pièce, vise dans le cercle." to Ink500
    }
    val label = when {
        awaiting -> "Analyse…"
        detected -> "Snap"
        else -> "Vise une pièce…"
    }
    val enabled = detected && !awaiting

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            AnimatedContent(
                targetState = helper.first,
                transitionSpec = {
                    (fadeIn(initialAlpha = 0f) + slideInVertically { it / 4 })
                        .togetherWith(fadeOut(targetAlpha = 0f) + slideOutVertically { -it / 4 })
                },
                label = "helper-text",
            ) { txt ->
                Text(
                    txt,
                    color = helper.second,
                    fontSize = 12.5.sp,
                    textAlign = TextAlign.Center,
                )
            }
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(60.dp)
                .alpha(if (enabled) 1f else 0.42f)
                .shadow(if (enabled) 18.dp else 0.dp, RoundedCornerShape(EurioRadii.full), clip = false)
                .clip(RoundedCornerShape(EurioRadii.full))
                .background(
                    Brush.verticalGradient(
                        listOf(Indigo600, Indigo700),
                    ),
                )
                .clickable(enabled = enabled, onClick = onSnap),
            contentAlignment = Alignment.Center,
        ) {
            AnimatedContent(
                targetState = label,
                transitionSpec = {
                    (fadeIn(initialAlpha = 0f) + slideInVertically { it / 4 })
                        .togetherWith(fadeOut(targetAlpha = 0f) + slideOutVertically { -it / 4 })
                },
                label = "snap-label",
            ) { txt ->
                Text(
                    txt,
                    color = Color.White,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }
    }
}
