package com.musubi.eurio.features.onboarding.pages

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.musubi.eurio.features.onboarding.components.EurioWordmark
import com.musubi.eurio.features.onboarding.components.OnboardingBackButton
import com.musubi.eurio.features.onboarding.components.OnboardingCopyBlock
import com.musubi.eurio.features.onboarding.components.OnboardingIndigoBackground
import com.musubi.eurio.features.onboarding.components.OnboardingPagerDots
import com.musubi.eurio.features.onboarding.components.OnboardingPrimaryButton
import com.musubi.eurio.features.onboarding.components.OnboardingSkipButton
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.FrauncesFamily
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold300
import com.musubi.eurio.ui.theme.Gold700
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.Indigo800
import com.musubi.eurio.ui.theme.Indigo900
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.PaperSurface

// Proto parity: docs/design/prototype/scenes/onboarding-3.html
@Composable
fun OnboardingSlide3Page(
    onNext: () -> Unit,
    onBack: () -> Unit,
    onSkip: () -> Unit,
    modifier: Modifier = Modifier,
) {
    OnboardingIndigoBackground(modifier = modifier, withBottomHalo = false) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(
                    start = EurioSpacing.s6,
                    end = EurioSpacing.s6,
                    top = 52.dp,
                    bottom = EurioSpacing.s8,
                ),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                EurioWordmark()
                OnboardingSkipButton(label = "Passer", onClick = onSkip)
            }

            Spacer(Modifier.height(EurioSpacing.s6))

            SetProgressCard(modifier = Modifier.fillMaxWidth())

            Spacer(Modifier.height(EurioSpacing.s6))

            OnboardingPagerDots(
                pageCount = 3,
                currentIndex = 2,
                modifier = Modifier.fillMaxWidth().padding(bottom = EurioSpacing.s4),
            )

            OnboardingCopyBlock(
                eyebrow = "Étape 3 sur 3",
                title = "Complète des séries entières.",
                body = "Eurio traque chaque série par pays et millésime. Sans points kitsch, sans notifications agressives — juste la satisfaction de voir la collection se compléter.",
                titleFontSize = 30.sp,
                modifier = Modifier.fillMaxWidth().padding(bottom = EurioSpacing.s6),
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OnboardingBackButton(onClick = onBack)
                OnboardingPrimaryButton(
                    label = "C'est parti",
                    onClick = onNext,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun SetProgressCard(modifier: Modifier = Modifier) {
    Box(modifier = modifier) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(EurioRadii.xl))
                .background(
                    Brush.verticalGradient(
                        colors = listOf(
                            Color.White.copy(alpha = 0.08f),
                            Color.White.copy(alpha = 0.03f),
                        ),
                    ),
                )
                .border(1.dp, Gold.copy(alpha = 0.45f), RoundedCornerShape(EurioRadii.xl))
                .padding(EurioSpacing.s5),
        ) {
            // Head: flag + title + fraction
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
            ) {
                FrenchFlagDisc()
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "France · circulation",
                        style = MaterialTheme.typography.titleLarge.copy(
                            fontFamily = FrauncesFamily,
                            fontStyle = FontStyle.Italic,
                            color = PaperSurface,
                            fontSize = 18.sp,
                        ),
                    )
                    Spacer(Modifier.height(2.dp))
                    Text(
                        text = "SÉRIE DES 8 VALEURS",
                        style = MonoBadgeStyle.copy(
                            color = Color.White.copy(alpha = 0.45f),
                            letterSpacing = 1.4.sp,
                        ),
                    )
                }
                FractionPill(text = "6 / 8")
            }

            Spacer(Modifier.height(EurioSpacing.s4))

            // Progress bar — 75 %
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(Color.White.copy(alpha = 0.1f)),
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(0.75f)
                        .fillMaxHeight()
                        .clip(RoundedCornerShape(2.dp))
                        .background(
                            Brush.horizontalGradient(
                                colors = listOf(Gold300, Gold, Gold700),
                            ),
                        ),
                )
            }

            Spacer(Modifier.height(EurioSpacing.s4))

            // 4×2 grid : 6 owned + 2 missing
            val cells = listOf(
                "1c" to true, "2c" to true, "5c" to false, "10c" to true,
                "20c" to true, "50c" to false, "1€" to true, "2€" to true,
            )
            Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3)) {
                for (row in 0 until 2) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
                    ) {
                        for (col in 0 until 4) {
                            val (label, owned) = cells[row * 4 + col]
                            SetCoin(
                                label = label,
                                owned = owned,
                                modifier = Modifier.weight(1f).aspectRatio(1f),
                            )
                        }
                    }
                }
            }
        }

        // "Exemple · progression" tag
        Box(
            modifier = Modifier
                .align(Alignment.TopStart)
                .offset(x = 20.dp, y = (-10).dp)
                .clip(RoundedCornerShape(EurioRadii.full))
                .background(Indigo800)
                .border(1.dp, Gold.copy(alpha = 0.45f), RoundedCornerShape(EurioRadii.full))
                .padding(horizontal = 10.dp, vertical = 2.dp),
        ) {
            Text(
                text = "EXEMPLE · PROGRESSION",
                style = MonoBadgeStyle.copy(
                    color = Gold,
                    fontSize = 9.sp,
                    letterSpacing = 1.8.sp,
                    fontWeight = FontWeight.SemiBold,
                ),
            )
        }
    }
}

@Composable
private fun FrenchFlagDisc() {
    val blue = Color(0xFF0055A4)
    val white = Color(0xFFFFFFFF)
    val red = Color(0xFFEF4135)
    Box(
        modifier = Modifier
            .size(44.dp)
            .clip(CircleShape)
            .border(1.dp, Color.White.copy(alpha = 0.2f), CircleShape),
    ) {
        Row(modifier = Modifier.fillMaxSize()) {
            Box(modifier = Modifier.weight(1f).fillMaxHeight().background(blue))
            Box(modifier = Modifier.weight(1f).fillMaxHeight().background(white))
            Box(modifier = Modifier.weight(1f).fillMaxHeight().background(red))
        }
    }
}

@Composable
private fun FractionPill(text: String) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(Gold.copy(alpha = 0.14f))
            .border(1.dp, Gold.copy(alpha = 0.35f), RoundedCornerShape(EurioRadii.full))
            .padding(horizontal = 12.dp, vertical = 4.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.titleMedium.copy(
                fontFamily = FrauncesFamily,
                fontStyle = FontStyle.Italic,
                color = Gold,
                fontSize = 16.sp,
            ),
        )
    }
}

@Composable
private fun SetCoin(label: String, owned: Boolean, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier,
        contentAlignment = Alignment.Center,
    ) {
        if (owned) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .clip(CircleShape)
                    .background(
                        Brush.radialGradient(
                            colors = listOf(Gold300, Gold, Gold700, GoldDeep),
                            center = Offset(0.35f, 0.32f),
                            radius = 200f,
                        ),
                    )
                    .border(1.dp, Gold.copy(alpha = 0.4f), CircleShape),
            )
        } else {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .clip(CircleShape)
                    .background(Color.White.copy(alpha = 0.05f))
                    .border(1.dp, Color.White.copy(alpha = 0.25f), CircleShape),
            )
        }
        Text(
            text = label,
            style = MaterialTheme.typography.titleSmall.copy(
                fontFamily = FrauncesFamily,
                fontStyle = FontStyle.Italic,
                fontWeight = FontWeight.Medium,
                color = if (owned) Indigo900 else Color.White.copy(alpha = 0.3f),
                fontSize = 13.sp,
            ),
            textAlign = TextAlign.Center,
        )
        if (owned) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .offset(x = (-2).dp, y = 2.dp)
                    .size(14.dp)
                    .clip(CircleShape)
                    .background(Indigo900)
                    .border(1.dp, Gold, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "✓",
                    style = MaterialTheme.typography.labelSmall.copy(
                        color = Gold,
                        fontSize = 9.sp,
                    ),
                )
            }
        }
    }
}
