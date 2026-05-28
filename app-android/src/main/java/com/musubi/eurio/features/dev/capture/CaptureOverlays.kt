package com.musubi.eurio.features.dev.capture

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.musubi.eurio.features.scan.CaptureProtocol
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Success

/**
 * Bannière haute affichée en /dev/capture. Montre la pièce en cours + la
 * consigne de cadrage. Le ring vert/or est rendu par PhotoGuideOverlay (vue
 * live) ou CaptureSnapRingOverlay (snap pending).
 */
@Composable
fun CaptureGuideOverlay(
    progress: CaptureViewModel.CaptureProgress,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 80.dp, start = EurioSpacing.s3, end = EurioSpacing.s3)
                .fillMaxWidth()
                .clip(RoundedCornerShape(EurioRadii.sm))
                .background(Color.Black.copy(alpha = 0.82f))
                .border(
                    width = 1.dp,
                    color = Gold.copy(alpha = 0.55f),
                    shape = RoundedCornerShape(EurioRadii.sm),
                )
                .padding(EurioSpacing.s3),
            verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
        ) {
            if (progress.isComplete) {
                Text(
                    text = "CAPTURE TERMINÉE",
                    style = MonoBadgeStyle,
                    color = Success,
                )
                Text(
                    text = "${progress.captured}/${progress.total} snaps · pull via go-task android:pull-debug",
                    style = MonoBadgeStyle,
                    color = Color.White.copy(alpha = 0.85f),
                )
                return@Column
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                val photoLabel = if (progress.photosPerStep > 1) {
                    " · PHOTO ${progress.photoIndex + 1}/${progress.photosPerStep}"
                } else ""
                Text(
                    text = "PIÈCE ${progress.coinIndex + 1}/${CaptureProtocol.coins.size}" +
                        " · STEP ${progress.stepIndex + 1}/${CaptureProtocol.steps.size}" +
                        photoLabel,
                    style = MonoBadgeStyle,
                    color = Gold,
                )
                Text(
                    text = "${progress.captured}/${progress.total}",
                    style = MonoBadgeStyle,
                    color = Color.White.copy(alpha = 0.7f),
                )
            }
            Text(
                text = progress.coin.displayName,
                style = MonoBadgeStyle,
                color = Color.White,
            )
            Text(
                text = "→ ${progress.step.label}",
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.85f),
            )
        }
    }
}
