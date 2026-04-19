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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
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
import com.musubi.eurio.ui.theme.Indigo900
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.Success

// Proto parity: docs/design/prototype/scenes/onboarding-2.html
@Composable
fun OnboardingSlide2Page(
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
            // Top bar
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                EurioWordmark()
                OnboardingSkipButton(label = "Passer", onClick = onSkip)
            }

            Spacer(Modifier.height(EurioSpacing.s6))

            FakeVaultCard(modifier = Modifier.fillMaxWidth())

            Spacer(Modifier.height(EurioSpacing.s6))

            RecentCoinsPreview(modifier = Modifier.fillMaxWidth())

            Spacer(Modifier.height(EurioSpacing.s5))

            OnboardingPagerDots(
                pageCount = 3,
                currentIndex = 1,
                modifier = Modifier.fillMaxWidth().padding(bottom = EurioSpacing.s4),
            )

            OnboardingCopyBlock(
                eyebrow = "Étape 2 sur 3",
                title = "À quoi ressemblera ton coffre.",
                body = "Chaque pièce prend place dans ton coffre local. Voilà à quoi ça ressemblera quand tu l'auras rempli.",
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
                    label = "Suivant",
                    onClick = onNext,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun FakeVaultCard(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier,
    ) {
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
                .border(
                    1.dp,
                    Gold.copy(alpha = 0.45f),
                    RoundedCornerShape(EurioRadii.xl),
                )
                .padding(EurioSpacing.s5),
        ) {
            Text(
                text = "TON COFFRE · APERÇU",
                style = MonoBadgeStyle.copy(
                    color = Color.White.copy(alpha = 0.5f),
                    letterSpacing = 1.8.sp,
                ),
            )
            Spacer(Modifier.height(EurioSpacing.s2))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "86,40 €",
                    style = MaterialTheme.typography.displaySmall.copy(
                        fontFamily = FrauncesFamily,
                        fontStyle = FontStyle.Italic,
                        color = PaperSurface,
                        fontSize = 44.sp,
                    ),
                )
                Spacer(Modifier.width(EurioSpacing.s3))
                DeltaPill(text = "▲ 12 %")
            }
            Spacer(Modifier.height(EurioSpacing.s4))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(1.dp)
                    .background(Gold.copy(alpha = 0.25f)),
            )
            Spacer(Modifier.height(EurioSpacing.s4))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                StatCell(value = "24", label = "Pièces")
                StatDivider()
                StatCell(value = "7", label = "Pays")
                StatDivider()
                StatCell(value = "3", label = "Séries")
            }
        }

        // "Exemple · aperçu" tag peeking above the card top border
        Box(
            modifier = Modifier
                .align(Alignment.TopStart)
                .offset(x = 20.dp, y = (-10).dp)
                .clip(RoundedCornerShape(EurioRadii.full))
                .background(com.musubi.eurio.ui.theme.Indigo800)
                .border(
                    1.dp,
                    Gold.copy(alpha = 0.45f),
                    RoundedCornerShape(EurioRadii.full),
                )
                .padding(horizontal = 10.dp, vertical = 2.dp),
        ) {
            Text(
                text = "EXEMPLE · APERÇU",
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
private fun StatCell(value: String, label: String, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier,
    ) {
        Text(
            text = value,
            style = MaterialTheme.typography.titleLarge.copy(
                fontFamily = FrauncesFamily,
                color = PaperSurface,
                fontSize = 22.sp,
            ),
        )
        Spacer(Modifier.height(2.dp))
        Text(
            text = label.uppercase(),
            style = MonoBadgeStyle.copy(
                color = Color.White.copy(alpha = 0.45f),
                fontSize = 9.sp,
                letterSpacing = 1.4.sp,
            ),
        )
    }
}

@Composable
private fun StatDivider() {
    Box(
        modifier = Modifier
            .width(1.dp)
            .height(28.dp)
            .background(Color.White.copy(alpha = 0.1f)),
    )
}

@Composable
private fun DeltaPill(text: String) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(Success.copy(alpha = 0.18f))
            .padding(horizontal = 9.dp, vertical = 3.dp),
    ) {
        Text(
            text = text,
            style = MonoBadgeStyle.copy(
                color = Success,
                fontSize = 10.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 0.6.sp,
            ),
        )
    }
}

@Composable
private fun RecentCoinsPreview(modifier: Modifier = Modifier) {
    val cells = listOf(
        "🇫🇷" to "2€",
        "🇩🇪" to "1€",
        "🇪🇸" to "50c",
        "🇮🇹" to "20c",
        "🇵🇹" to "10c",
        "🇧🇬" to "2€",
    )
    Column(modifier = modifier) {
        Text(
            text = "AJOUTÉES RÉCEMMENT · EXEMPLE",
            style = MonoBadgeStyle.copy(
                color = Color.White.copy(alpha = 0.45f),
                letterSpacing = 1.8.sp,
            ),
        )
        Spacer(Modifier.height(EurioSpacing.s3))
        // 3×2 grid
        Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3)) {
            for (row in 0 until 2) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
                ) {
                    for (col in 0 until 3) {
                        val (flag, value) = cells[row * 3 + col]
                        CoinCell(
                            flag = flag,
                            value = value,
                            modifier = Modifier
                                .weight(1f)
                                .aspectRatio(1f),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun CoinCell(flag: String, value: String, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .clip(CircleShape)
            .background(
                Brush.radialGradient(
                    colors = listOf(Gold300, Gold, Gold700, GoldDeep),
                    center = Offset(0.35f, 0.32f),
                    radius = 200f,
                ),
            )
            .border(1.dp, Gold.copy(alpha = 0.35f), CircleShape),
    ) {
        Text(
            text = flag,
            style = MaterialTheme.typography.labelSmall,
            fontSize = 12.sp,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(4.dp),
        )
        Text(
            text = value,
            style = MaterialTheme.typography.titleLarge.copy(
                fontFamily = FrauncesFamily,
                fontStyle = FontStyle.Italic,
                fontWeight = FontWeight.Medium,
                color = Indigo900,
                fontSize = if (value.length <= 2) 18.sp else 13.sp,
            ),
            modifier = Modifier.align(Alignment.Center),
            textAlign = TextAlign.Center,
        )
    }
}
