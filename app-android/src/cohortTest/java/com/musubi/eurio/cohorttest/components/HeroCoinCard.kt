package com.musubi.eurio.cohorttest.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import androidx.compose.ui.platform.LocalContext
import com.musubi.eurio.cohorttest.CoinDisplay
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.FrauncesFamily
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold400
import com.musubi.eurio.ui.theme.Gold700
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.GoldSoft
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.Paper

/**
 * Hero card showing the coin the user must pull from their pile and
 * snap. Mirrors the proto at `docs/design/prototype/scenes/cohort-test-live/`.
 *
 * Left: 76dp circular obverse thumbnail loaded from
 * [CoinDisplay.image_obverse_url] via Coil; falls back to a gold-gradient
 * coin token with the face value in Fraunces italic when no URL is
 * available (uncommon — circulation rows from Numista usually have one).
 *
 * Right: eyebrow with flag + country FR + year + denom, and the
 * (sometimes English) coin title in Fraunces.
 *
 * Below: the condition chip ([conditionLabel]).
 */
@Composable
fun HeroCoinCard(
    display: CoinDisplay,
    condition: String,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .shadow(2.dp, RoundedCornerShape(EurioRadii.lg), clip = false)
            .clip(RoundedCornerShape(EurioRadii.lg))
            .background(Paper)
            .border(1.dp, Gold.copy(alpha = 0.18f), RoundedCornerShape(EurioRadii.lg))
            .padding(
                horizontal = EurioSpacing.s5,
                vertical = EurioSpacing.s4,
            ),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s4),
            ) {
                CoinThumb(
                    imageUrl = display.image_obverse_url,
                    fallbackDenom = display.face_value_label,
                )
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                ) {
                    val flag = display.flag_emoji.takeIf { it.isNotEmpty() }
                    val eyebrow = listOfNotNull(
                        flag?.let { "$it ${display.country_fr}" }
                            ?: display.country_fr.takeIf { it.isNotEmpty() },
                        display.year?.toString(),
                        display.face_value_label.takeIf { it.isNotEmpty() },
                    ).joinToString(" · ")
                    if (eyebrow.isNotEmpty()) {
                        Text(
                            eyebrow.uppercase(),
                            style = EyebrowStyle.copy(color = Ink500),
                        )
                    }
                    Text(
                        display.title,
                        fontFamily = FrauncesFamily,
                        fontWeight = FontWeight.Medium,
                        fontStyle = FontStyle.Normal,
                        fontSize = 22.sp,
                        lineHeight = 26.sp,
                        color = Ink,
                    )
                }
            }
            ConditionChip(condition = condition)
        }
    }
}

@Composable
private fun CoinThumb(
    imageUrl: String?,
    fallbackDenom: String,
) {
    Box(
        modifier = Modifier
            .size(76.dp)
            .clip(CircleShape)
            .background(
                Brush.radialGradient(
                    0.0f to GoldSoft,
                    0.55f to Gold400,
                    1.0f to Gold700,
                ),
            )
            .border(
                BorderStroke(1.dp, GoldDeep.copy(alpha = 0.45f)),
                CircleShape,
            ),
        contentAlignment = Alignment.Center,
    ) {
        if (!imageUrl.isNullOrBlank()) {
            val ctx = LocalContext.current
            AsyncImage(
                model = ImageRequest.Builder(ctx)
                    .data(imageUrl)
                    .crossfade(true)
                    .build(),
                contentDescription = null,
                modifier = Modifier
                    .fillMaxSize()
                    .clip(CircleShape),
            )
        } else {
            Text(
                fallbackDenom.ifBlank { "€" },
                fontFamily = FrauncesFamily,
                fontStyle = FontStyle.Italic,
                fontWeight = FontWeight.Medium,
                fontSize = 20.sp,
                color = GoldDeep,
            )
        }
    }
}

private data class ConditionVisual(val emoji: String, val label: String)

private fun conditionVisual(condition: String): ConditionVisual = when (condition) {
    "bright" -> ConditionVisual("☀️", "Lumière vive")
    "dim" -> ConditionVisual("🌙", "Faible lumière")
    "tilt" -> ConditionVisual("📐", "Inclinée")
    "glare" -> ConditionVisual("✨", "Reflets")
    "inhand" -> ConditionVisual("✋", "En main")
    else -> ConditionVisual("•", condition)
}

@Composable
private fun ConditionChip(condition: String) {
    val v = conditionVisual(condition)
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(GoldSoft)
            .border(
                1.dp,
                Gold700.copy(alpha = 0.16f),
                RoundedCornerShape(EurioRadii.full),
            )
            .padding(horizontal = EurioSpacing.s3, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(v.emoji, fontSize = 14.sp, color = Color.Unspecified)
        Spacer(Modifier.width(0.dp))
        Text(
            v.label,
            color = Gold700,
            fontWeight = FontWeight.Medium,
            fontSize = 13.sp,
            lineHeight = 16.sp,
        )
    }
}
