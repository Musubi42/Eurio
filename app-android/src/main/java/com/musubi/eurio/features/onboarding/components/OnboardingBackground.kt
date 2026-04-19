package com.musubi.eurio.features.onboarding.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import com.musubi.eurio.ui.theme.Indigo500
import com.musubi.eurio.ui.theme.Indigo800
import com.musubi.eurio.ui.theme.Indigo900

// Indigo gradient shared by the 3 tutorial slides (onboarding-1/2/3) and the
// splash. Proto reference: layered radial gradients on Indigo500 → Indigo800,
// plus a dimmer Indigo900 halo at the bottom for the splash. Compose
// radialGradient approximates the proto's ellipse 90%×55% via a single radius.
@Composable
fun OnboardingIndigoBackground(
    modifier: Modifier = Modifier,
    withBottomHalo: Boolean = false,
    content: @Composable BoxScope.() -> Unit,
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(Indigo800)
            .background(
                Brush.radialGradient(
                    colors = listOf(Indigo500, Indigo800.copy(alpha = 0f)),
                    center = Offset.Unspecified,
                    radius = 1600f,
                ),
            ),
    ) {
        if (withBottomHalo) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(
                        Brush.verticalGradient(
                            colors = listOf(
                                Indigo800.copy(alpha = 0f),
                                Indigo800.copy(alpha = 0f),
                                Indigo900.copy(alpha = 0.6f),
                            ),
                        ),
                    ),
            )
        }
        content()
    }
}
