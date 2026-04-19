package com.musubi.eurio.features.onboarding.pages

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.musubi.eurio.features.onboarding.components.EurioWordmark
import com.musubi.eurio.features.onboarding.components.OnboardingIndigoBackground
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.FrauncesFamily
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold300
import com.musubi.eurio.ui.theme.Gold700
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.Indigo900
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import kotlinx.coroutines.delay

// Proto parity: docs/design/prototype/scenes/onboarding-splash.html
// Auto-advance to the next page after ~1.4s, or immediately on tap. The
// progress bar fill animates in lockstep with the auto-advance delay.
const val ONBOARDING_SPLASH_MS: Long = 1400L

@Composable
fun OnboardingSplashPage(
    onAdvance: () -> Unit,
    modifier: Modifier = Modifier,
) {
    LaunchedEffect(Unit) {
        delay(ONBOARDING_SPLASH_MS)
        onAdvance()
    }

    val interaction = remember { MutableInteractionSource() }
    OnboardingIndigoBackground(
        modifier = modifier
            .clickable(
                interactionSource = interaction,
                indication = null,
                onClick = onAdvance,
            ),
        withBottomHalo = true,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = EurioSpacing.s6),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            PulsingCoinBadge()
            Spacer(Modifier.height(EurioSpacing.s7))
            EurioWordmark(fontSize = 56.sp)
            Spacer(Modifier.height(EurioSpacing.s4))
            Text(
                text = "NUMISMATIQUE · EUROPÉENNE",
                style = MonoBadgeStyle.copy(
                    color = Color.White.copy(alpha = 0.55f),
                    fontSize = 10.sp,
                    letterSpacing = 2.sp,
                ),
                textAlign = TextAlign.Center,
            )
        }

        SplashProgress(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.BottomCenter)
                .padding(bottom = 72.dp),
        )
    }
}

@Composable
private fun PulsingCoinBadge() {
    val transition = rememberInfiniteTransition(label = "splashCoin")
    val scale by transition.animateFloat(
        initialValue = 1f,
        targetValue = 1.04f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1700, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "splashCoinScale",
    )

    Box(
        modifier = Modifier
            .size(148.dp)
            .scale(scale)
            .clip(CircleShape)
            .background(
                brush = Brush.radialGradient(
                    colors = listOf(Gold300, Gold, Gold700, GoldDeep),
                    center = Offset(0.35f, 0.32f) * 148f,
                    radius = 160f,
                ),
            ),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "2€",
            style = MaterialTheme.typography.displayMedium.copy(
                fontFamily = FrauncesFamily,
                fontStyle = FontStyle.Italic,
                fontWeight = FontWeight.Medium,
                fontSize = 46.sp,
                color = Indigo900,
            ),
        )
    }
}

private operator fun Offset.times(scalar: Float): Offset = Offset(x * scalar, y * scalar)

@Composable
private fun SplashProgress(modifier: Modifier = Modifier) {
    val transition = rememberInfiniteTransition(label = "splashProgress")
    val progress by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = ONBOARDING_SPLASH_MS.toInt(), easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "splashProgressValue",
    )

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Canvas(
            modifier = Modifier
                .size(width = 120.dp, height = 1.dp),
        ) {
            // Track (faint gold rule)
            drawRect(
                color = Gold.copy(alpha = 0.18f),
                topLeft = Offset.Zero,
                size = Size(size.width, size.height),
            )
            // Moving fill with soft edges (gradient left→right, width capped)
            val fillWidth = size.width * progress
            drawRect(
                brush = Brush.horizontalGradient(
                    colors = listOf(Color.Transparent, Gold, Color.Transparent),
                ),
                topLeft = Offset.Zero,
                size = Size(fillWidth, size.height),
            )
        }
        Spacer(Modifier.height(EurioSpacing.s3))
        Text(
            text = "MUSUBI · 2026",
            style = MonoBadgeStyle.copy(
                color = Color.White.copy(alpha = 0.38f),
                fontSize = 9.sp,
                letterSpacing = 1.6.sp,
            ),
        )
    }
}
