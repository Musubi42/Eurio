package com.musubi.eurio.features.onboarding.pages

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.musubi.eurio.features.onboarding.components.EurioWordmark
import com.musubi.eurio.features.onboarding.components.OnboardingCopyBlock
import com.musubi.eurio.features.onboarding.components.OnboardingIndigoBackground
import com.musubi.eurio.features.onboarding.components.OnboardingPagerDots
import com.musubi.eurio.features.onboarding.components.OnboardingPrimaryButton
import com.musubi.eurio.features.onboarding.components.OnboardingSkipButton
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.FrauncesFamily
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold300
import com.musubi.eurio.ui.theme.Gold700
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

// Proto parity: docs/design/prototype/scenes/onboarding-1.html
@Composable
fun OnboardingSlide1Page(
    onNext: () -> Unit,
    onSkip: () -> Unit,
    modifier: Modifier = Modifier,
) {
    OnboardingIndigoBackground(modifier = modifier, withBottomHalo = false) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(
                    start = EurioSpacing.s6,
                    end = EurioSpacing.s6,
                    top = 52.dp,
                    bottom = EurioSpacing.s8,
                ),
        ) {
            // Top bar: wordmark + skip pill
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                EurioWordmark()
                OnboardingSkipButton(label = "Passer", onClick = onSkip)
            }

            // Hero — breathing 2€ coin with halo
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                HeroCoin(sizeDp = 240)
            }

            OnboardingPagerDots(
                pageCount = 3,
                currentIndex = 0,
                modifier = Modifier
                    .fillMaxWidth()
                    .wrapContentSize(Alignment.Center)
                    .padding(bottom = EurioSpacing.s5),
            )

            OnboardingCopyBlock(
                eyebrow = "Étape 1 sur 3",
                title = "Scanne la pièce que tu as en main.",
                body = "Pointe ton téléphone, Eurio reconnaît la pièce en quelques dixièmes de seconde — 100 % hors-ligne.",
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = EurioSpacing.s6),
            )

            OnboardingPrimaryButton(
                label = "Commencer",
                onClick = onNext,
                modifier = Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(EurioSpacing.s2))
            Text(
                text = "FONCTIONNE HORS-LIGNE · AUCUN COMPTE REQUIS",
                style = MonoBadgeStyle.copy(
                    color = Color.White.copy(alpha = 0.35f),
                    fontSize = 9.sp,
                    letterSpacing = 1.3.sp,
                ),
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun HeroCoin(sizeDp: Int) {
    val transition = rememberInfiniteTransition(label = "heroCoin")
    val scale by transition.animateFloat(
        initialValue = 1f,
        targetValue = 1.035f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1700, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "heroCoinScale",
    )
    val haloAlpha by transition.animateFloat(
        initialValue = 0.55f,
        targetValue = 0.95f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1700, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "heroCoinHalo",
    )

    Box(
        modifier = Modifier.size((sizeDp + 60).dp),
        contentAlignment = Alignment.Center,
    ) {
        // Halo
        Box(
            modifier = Modifier
                .size((sizeDp + 60).dp)
                .scale(1f + (scale - 1f) * 2f)
                .clip(CircleShape)
                .background(
                    Brush.radialGradient(
                        colors = listOf(
                            Gold.copy(alpha = 0.28f * haloAlpha),
                            Gold.copy(alpha = 0.08f * haloAlpha),
                            Color.Transparent,
                        ),
                    ),
                ),
        )

        // Coin body with 12 euro stars
        Canvas(
            modifier = Modifier
                .size(sizeDp.dp)
                .scale(scale),
        ) {
            val w = size.width
            val h = size.height
            val cx = w / 2f
            val cy = h / 2f
            val rOuter = w / 2f - 4f
            val rInner = w * 80f / 240f
            val rStars = w * 98f / 240f

            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(Gold300, Gold, Gold700, GoldDeep),
                    center = Offset(w * 0.35f, h * 0.32f),
                    radius = w * 0.75f,
                ),
                radius = rOuter,
                center = Offset(cx, cy),
            )
            drawCircle(
                color = Color(0xFFFFE6AA).copy(alpha = 0.45f),
                radius = rOuter,
                center = Offset(cx, cy),
                style = Stroke(width = 1f),
            )
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(Gold300, Gold700),
                    center = Offset(w * 0.4f, h * 0.35f),
                    radius = w * 0.7f,
                ),
                radius = rInner,
                center = Offset(cx, cy),
            )
            drawCircle(
                color = Color(0xFF8F7637).copy(alpha = 0.55f),
                radius = rInner,
                center = Offset(cx, cy),
                style = Stroke(width = 1f),
            )

            // 12 stars around the ring
            val starR = 6f
            for (i in 0 until 12) {
                val angle = -PI.toFloat() / 2f + i * (2f * PI.toFloat() / 12f)
                val sx = cx + rStars * cos(angle)
                val sy = cy + rStars * sin(angle)
                drawStar(Offset(sx, sy), starR, PaperSurface.copy(alpha = 0.92f))
            }
        }

        // "2" label overlay (display italic)
        Text(
            text = "2",
            style = androidx.compose.material3.MaterialTheme.typography.displayLarge.copy(
                fontFamily = FrauncesFamily,
                fontStyle = FontStyle.Italic,
                fontWeight = FontWeight.Medium,
                color = Ink500,
                fontSize = 54.sp,
                letterSpacing = (-2).sp,
            ),
            modifier = Modifier
                .padding(bottom = 6.dp)
                .scale(scale),
        )
    }
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawStar(
    center: Offset,
    radius: Float,
    color: Color,
) {
    val path = Path()
    val pts = doubleArrayOf(
        0.0, -1.0,
        0.294, -0.308,
        1.0, -0.308,
        0.437, 0.117,
        0.648, 0.808,
        0.0, 0.4,
        -0.648, 0.808,
        -0.437, 0.117,
        -1.0, -0.308,
        -0.294, -0.308,
    )
    path.moveTo(
        center.x + (pts[0] * radius).toFloat(),
        center.y + (pts[1] * radius).toFloat(),
    )
    var i = 2
    while (i < pts.size) {
        path.lineTo(
            center.x + (pts[i] * radius).toFloat(),
            center.y + (pts[i + 1] * radius).toFloat(),
        )
        i += 2
    }
    path.close()
    drawPath(path, color)
}
