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
import com.musubi.eurio.features.scan.ScanViewModel.CaptureProgress
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Success

/**
 * Top-screen banner shown during capture mode. Displays the current coin and
 * the framing instruction for the current step. The actual disk-guide circle
 * is still drawn by [PhotoGuideOverlay] underneath.
 */
@Composable
fun CaptureGuideOverlay(
    progress: CaptureProgress,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 120.dp, start = EurioSpacing.s3, end = EurioSpacing.s3)
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
                Text(
                    text = "PIÈCE ${progress.coinIndex + 1}/${com.musubi.eurio.features.scan.CaptureProtocol.coins.size}" +
                        " · STEP ${progress.stepIndex + 1}/${com.musubi.eurio.features.scan.CaptureProtocol.steps.size}",
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

/**
 * Buttons shown on top of the photo snap result while capture mode is active:
 * [Redo] re-takes the same step, [Next] advances to the next step (or coin).
 */
@Composable
fun CaptureResultActions(
    onRedo: () -> Unit,
    onNext: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        CaptureActionButton(
            label = "↻ refaire",
            accent = Color.White.copy(alpha = 0.7f),
            onClick = onRedo,
            modifier = Modifier.weight(1f),
        )
        CaptureActionButton(
            label = "✓ suivant",
            accent = Success,
            onClick = onNext,
            modifier = Modifier.weight(1f),
        )
    }
}

/**
 * Capture-mode replacement for [PhotoSnapResultLayer]. Shows just the saved
 * crop + the capture banner — no ArcFace decision, no top-K matches. Decision
 * data is irrelevant during golden-set capture and would only mislead.
 */
@Composable
fun CaptureSnapResultLayer(
    snap: ScanViewModel.PhotoSnap,
    progress: CaptureProgress,
    onRedo: () -> Unit,
    onNext: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val normalizeFailed = snap.cropPath == null
    val accent = if (normalizeFailed) com.musubi.eurio.ui.theme.Warning else Success
    Column(
        modifier = modifier
            .fillMaxSize()
            .background(Ink)
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s4),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        Spacer(Modifier.height(EurioSpacing.s10))
        Text(
            text = if (normalizeFailed) "▲ NORMALIZE FAILED" else "✓ SNAP SAVED",
            style = MonoBadgeStyle,
            color = accent,
        )
        Text(
            text = "${progress.coin.displayName} · Step ${progress.stepIndex + 1}/${com.musubi.eurio.features.scan.CaptureProtocol.steps.size}",
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.85f),
        )
        Text(
            text = progress.step.label,
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.6f),
        )

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
                    text = "no centered circle\nrecadre + refaire",
                    style = MonoBadgeStyle,
                    color = accent,
                )
            } else {
                AsyncImage(
                    model = "file://${snap.cropPath}",
                    contentDescription = "Captured crop",
                    modifier = Modifier.fillMaxSize(),
                )
            }
        }

        Text(
            text = if (normalizeFailed) "step not counted — refaire pour réessayer"
                else "${snap.cropSize}×${snap.cropSize} px",
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.4f),
        )

        Spacer(Modifier.height(EurioSpacing.s3))

        // Disable "next" on failure: a failed snap must not advance the
        // protocol — golden set integrity depends on every step having a
        // valid normalized crop on disk.
        if (normalizeFailed) {
            CaptureResultActions(onRedo = onRedo, onNext = { /* disabled */ })
        } else {
            CaptureResultActions(onRedo = onRedo, onNext = onNext)
        }
    }
}

@Composable
private fun CaptureActionButton(
    label: String,
    accent: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.sm))
            .background(Color.Black.copy(alpha = 0.82f))
            .border(
                width = 1.dp,
                color = accent.copy(alpha = 0.55f),
                shape = RoundedCornerShape(EurioRadii.sm),
            )
            .clickable(onClick = onClick)
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s3),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = label, style = MonoBadgeStyle, color = accent)
    }
}
