package com.musubi.eurio.features.dev.bench

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.musubi.eurio.features.scan.components.CameraPreview
import com.musubi.eurio.features.scan.debug.BenchProtocolActions
import com.musubi.eurio.features.scan.debug.BenchProtocolHeader
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.MonoBadgeStyle

/**
 * Écran /dev/bench — protocole bench guidé (chunk-7b).
 *
 * Layout : CameraPreview pleine page + bannière header (cellule courante) en
 * haut + actions Start/Done/Skip en bas. Pas de HUD ni de tools strip — c'est
 * un écran focalisé sur le protocole.
 */
@Composable
fun BenchProtocolScreen(
    viewModel: BenchProtocolViewModel,
    relay: com.musubi.eurio.ScanCallbackRelay,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

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

        // Top bar : back + titre.
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
                text = "Bench protocol",
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.85f),
            )
        }

        val s = state
        if (s != null) {
            BenchProtocolHeader(
                state = s,
                onQuit = onBack,
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .padding(top = 64.dp),
            )
            BenchProtocolActions(
                state = s,
                onStart = { viewModel.startCurrent() },
                onDone = { viewModel.markCurrentDone() },
                onSkip = { viewModel.skipCurrent() },
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = EurioSpacing.s5),
            )
        } else {
            // Cohort vide → message d'aide.
            Text(
                text = "Aucune cohorte chargée.\nPush cohort.csv via :\ngo-task android:push-capture-csv",
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.7f),
                modifier = Modifier
                    .align(Alignment.Center)
                    .padding(EurioSpacing.s4),
            )
        }
    }
}
