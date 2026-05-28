package com.musubi.eurio.features.dev.carousel

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.musubi.eurio.features.scan.components.Coin3DTuneFab
import com.musubi.eurio.features.scan.components.Coin3DTuning
import com.musubi.eurio.features.scan.components.Coin3DTuningPanel
import com.musubi.eurio.features.scan.components.Coin3DViewer
import com.musubi.eurio.features.scan.components.ScanCarouselNav
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.MonoBadgeStyle

/**
 * Écran /dev/carousel — 3D coin viewer + tuning PBR.
 *
 * Pas de caméra ni de pipeline ML. Cycle prev/next sur toutes les pièces 2 €
 * via le repo. Permet d'inspecter le rendu Coin3DViewer et d'ajuster les
 * paramètres PBR en live.
 */
@Composable
fun CarouselScreen(
    viewModel: CarouselViewModel,
    onBack: () -> Unit,
) {
    val coin by viewModel.current.collectAsStateWithLifecycle()
    var tuning by remember { mutableStateOf(Coin3DTuning.Default) }
    var tunePanelOpen by remember { mutableStateOf(false) }

    LaunchedEffect(viewModel) {
        viewModel.enter()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Ink),
    ) {
        val c = coin
        if (c != null) {
            Coin3DViewer(
                eurioId = c.eurioId,
                obverseImageUrl = c.imageObverseUrl,
                reverseImageUrl = c.imageReverseUrl,
                obverseMeta = c.obversePhotoMeta,
                reverseMeta = c.reversePhotoMeta,
                flipKey = c.eurioId,
                tuning = tuning,
                isOpaque = false,
                modifier = Modifier.fillMaxSize(),
            )
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
                text = "3D coin carrousel",
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.85f),
            )
        }

        ScanCarouselNav(
            coin = c,
            onPrev = { viewModel.onPrev() },
            onNext = { viewModel.onNext() },
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = EurioSpacing.s6),
        )

        Column(
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = EurioSpacing.s3, bottom = 88.dp),
            horizontalAlignment = Alignment.End,
            verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
        ) {
            if (tunePanelOpen) {
                Coin3DTuningPanel(
                    tuning = tuning,
                    onChange = { tuning = it },
                    onReset = { tuning = Coin3DTuning.Default },
                )
            }
            Coin3DTuneFab(
                open = tunePanelOpen,
                onClick = { tunePanelOpen = !tunePanelOpen },
            )
        }
    }
}
