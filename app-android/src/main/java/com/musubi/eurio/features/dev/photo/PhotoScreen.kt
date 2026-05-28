package com.musubi.eurio.features.dev.photo

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Success

/**
 * Écran /dev/photo — photo snap standalone (ArcFace inspect).
 *
 * Layout : CameraPreview + PhotoGuideOverlay (ring centré) jusqu'au tap SNAP ;
 * après snap → PhotoSnapResultLayer plein écran avec le crop + top-K. Le bouton
 * du bas alterne SNAP ↔ reset selon le state.
 */
@Composable
fun PhotoScreen(
    viewModel: PhotoViewModel,
    relay: com.musubi.eurio.ScanCallbackRelay,
    onBack: () -> Unit,
) {
    val snap by viewModel.snap.collectAsStateWithLifecycle()
    val liveCircleFound by viewModel.liveCircleFound.collectAsStateWithLifecycle()

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

        val s = snap
        if (s != null) {
            PhotoSnapResultLayer(snap = s)
        } else {
            PhotoGuideOverlay(circleFound = liveCircleFound)
        }

        // Top bar.
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
                text = "Photo (ArcFace inspect)",
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.85f),
            )
        }

        // Bottom tool : SNAP / reset.
        val hasSnap = s != null
        Box(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .padding(
                    start = EurioSpacing.s3,
                    end = EurioSpacing.s3,
                    bottom = EurioSpacing.s5,
                ),
        ) {
            ToolButton(
                label = if (hasSnap) "↻ reset" else "● SNAP",
                accent = if (hasSnap) Gold else Success,
                onClick = { if (hasSnap) viewModel.onReset() else viewModel.onSnap() },
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun ToolButton(
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
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s4),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = label, style = MonoBadgeStyle, color = accent)
    }
}

