package com.musubi.eurio.features.dev.capture

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.musubi.eurio.features.scan.components.CameraPreview
import com.musubi.eurio.features.scan.components.PhotoGuideOverlay
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Success

/**
 * Écran /dev/capture — cohort capture (Phase 0 golden-set).
 *
 * UX : la vue est stable (caméra + bannière + ring + 2 boutons). Lors d'un
 * snap, seul le contenu du ring change (crop affiché à la place du live) et
 * les libellés des 2 boutons. Pas de plein écran intermédiaire, pas d'auto-
 * dismiss. Acté avec raph 2026-05-28.
 */
@Composable
fun CaptureScreen(
    viewModel: CaptureViewModel,
    relay: com.musubi.eurio.ScanCallbackRelay,
    onBack: () -> Unit,
) {
    val progress by viewModel.progress.collectAsStateWithLifecycle()
    val snap by viewModel.photoSnap.collectAsStateWithLifecycle()
    val circleFound by viewModel.photoLiveCircleFound.collectAsStateWithLifecycle()

    DisposableEffect(viewModel) {
        val handler: (com.musubi.eurio.ml.ScanResult) -> Unit = viewModel::onScanResult
        viewModel.enter()
        relay.delegate = handler
        onDispose {
            if (relay.delegate === handler) {
                relay.delegate = null
            }
            viewModel.leave()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Ink),
    ) {
        CameraPreview(
            onFrame = { image -> viewModel.onFrame(image) },
            modifier = Modifier.fillMaxSize(),
        )

        // Ring central — soit live (PhotoGuideOverlay) soit crop du snap pending.
        val snapPending = snap != null
        if (!snapPending) {
            PhotoGuideOverlay(circleFound = circleFound)
        } else {
            CaptureSnapRingOverlay(cropPath = snap?.cropPath)
        }

        // Bannière haute — toujours visible si la cohort est chargée.
        progress?.let { CaptureGuideOverlay(progress = it) }

        // Top bar : back + titre, posé au-dessus.
        Row(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(start = EurioSpacing.s2, top = EurioSpacing.s3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(
                    Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "Retour",
                    tint = Color.White,
                )
            }
            Text(
                text = "Capture cohorte",
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.85f),
            )
        }

        // Tools strip locale, en bas. Les 2 boutons ont 2 sémantiques :
        //  - pas de snap pending : "skip cellule" | "● SNAP"
        //  - snap pending + cropPath OK : "↻ refaire" | "✓ suivant"
        //  - snap pending + cropPath null : "↻ refaire" | (suivant disabled)
        val isComplete = progress?.isComplete == true
        if (!isComplete && progress != null) {
            val s = snap
            val leftLabel: String
            val rightLabel: String
            val leftAccent: Color
            val rightAccent: Color
            val leftAction: () -> Unit
            val rightAction: (() -> Unit)?

            if (s == null) {
                leftLabel = "skip cellule"
                rightLabel = "● SNAP"
                leftAccent = Color.White.copy(alpha = 0.6f)
                rightAccent = Success
                leftAction = { viewModel.onSkipCell() }
                rightAction = { viewModel.onSnap() }
            } else {
                leftLabel = "↻ refaire"
                rightLabel = "✓ suivant"
                leftAccent = Color.White.copy(alpha = 0.85f)
                rightAccent = Success
                leftAction = { viewModel.onRedo() }
                rightAction = if (s.cropPath != null) {
                    { viewModel.onAdvancePhoto() }
                } else null
            }

            Row(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .padding(
                        start = EurioSpacing.s3,
                        end = EurioSpacing.s3,
                        bottom = EurioSpacing.s5,
                    ),
                horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
            ) {
                ToolButton(
                    label = leftLabel,
                    accent = leftAccent,
                    onClick = leftAction,
                    modifier = Modifier.weight(1f),
                )
                ToolButton(
                    label = rightLabel,
                    accent = rightAccent,
                    onClick = rightAction ?: {},
                    enabled = rightAction != null,
                    modifier = Modifier.weight(2f),
                )
            }
        }
    }
}

@Composable
private fun ToolButton(
    label: String,
    accent: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val alpha = if (enabled) 1f else 0.35f
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.sm))
            .background(Color.Black.copy(alpha = if (enabled) 0.82f else 0.5f))
            .border(
                width = 1.dp,
                color = accent.copy(alpha = if (enabled) 0.55f else 0.2f),
                shape = RoundedCornerShape(EurioRadii.sm),
            )
            .let { if (enabled) it.clickable(onClick = onClick) else it }
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s4),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = label, style = MonoBadgeStyle, color = accent.copy(alpha = alpha))
    }
}
