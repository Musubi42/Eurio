package com.musubi.eurio.features.onboarding.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.clickable
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.FrauncesFamily
import com.musubi.eurio.ui.theme.InterTightFamily
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.MonoBadgeStyle

// "Passer" skip pill used by all 3 tutorial slides + the permission "Annuler".
@Composable
fun OnboardingSkipButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(Color.White.copy(alpha = 0.08f))
            .border(1.dp, Color.White.copy(alpha = 0.14f), RoundedCornerShape(EurioRadii.full))
            .clickable(onClick = onClick)
            .defaultMinSize(minHeight = 36.dp)
            .padding(horizontal = EurioSpacing.s4, vertical = EurioSpacing.s2),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall.copy(
                color = Color.White.copy(alpha = 0.85f),
                fontSize = 12.sp,
                fontWeight = FontWeight.Medium,
            ),
        )
    }
}

// 3-dot pager used below the hero on slides 1/2/3. The active dot is longer
// (28×2) and gold; inactive dots are 18×2 and white-ish-12%.
@Composable
fun OnboardingPagerDots(
    pageCount: Int,
    currentIndex: Int,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        repeat(pageCount) { i ->
            val isActive = i == currentIndex
            Box(
                modifier = Modifier
                    .height(2.dp)
                    .width(if (isActive) 28.dp else 18.dp)
                    .clip(RoundedCornerShape(1.dp))
                    .background(if (isActive) Gold else Color.White.copy(alpha = 0.18f)),
            )
        }
    }
}

// Gold pill CTA ("Commencer", "Suivant", "C'est parti"). Full-width, 56dp tall,
// with an optional trailing arrow glyph. Uses native Row + clickable to match
// the proto's flat style (no M3 Button elevation).
@Composable
fun OnboardingPrimaryButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    trailingGlyph: String? = "→",
) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.lg))
            .background(Gold)
            .clickable(onClick = onClick)
            .defaultMinSize(minHeight = 56.dp)
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s4),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.titleMedium.copy(
                fontFamily = InterTightFamily,
                color = com.musubi.eurio.ui.theme.Indigo900,
                fontWeight = FontWeight.SemiBold,
                fontSize = 16.sp,
            ),
        )
        if (trailingGlyph != null) {
            Spacer(Modifier.width(EurioSpacing.s2))
            Text(
                text = trailingGlyph,
                style = MaterialTheme.typography.titleMedium.copy(
                    color = com.musubi.eurio.ui.theme.Indigo900,
                    fontSize = 16.sp,
                ),
            )
        }
    }
}

// Round 48dp back arrow ("←") used on slides 2 & 3 left of the primary CTA.
@Composable
fun OnboardingBackButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .size(48.dp)
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(Color.White.copy(alpha = 0.06f))
            .border(1.dp, Color.White.copy(alpha = 0.14f), RoundedCornerShape(EurioRadii.full))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "←",
            style = MaterialTheme.typography.titleLarge.copy(
                color = Color.White.copy(alpha = 0.85f),
                fontSize = 20.sp,
            ),
        )
    }
}

// "Étape N sur 3" eyebrow + Fraunces italic h1 + body paragraph block shared
// by slides 1/2/3.
@Composable
fun OnboardingCopyBlock(
    eyebrow: String,
    title: String,
    body: String,
    modifier: Modifier = Modifier,
    titleFontSize: androidx.compose.ui.unit.TextUnit = 34.sp,
) {
    androidx.compose.foundation.layout.Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = eyebrow.uppercase(),
            style = MonoBadgeStyle.copy(
                color = Color.White.copy(alpha = 0.5f),
            ),
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(EurioSpacing.s3))
        Text(
            text = title,
            style = MaterialTheme.typography.displaySmall.copy(
                fontFamily = FrauncesFamily,
                fontStyle = FontStyle.Italic,
                color = PaperSurface,
                fontSize = titleFontSize,
                lineHeight = (titleFontSize.value * 1.1f).sp,
            ),
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(EurioSpacing.s3))
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium.copy(
                color = Color.White.copy(alpha = 0.65f),
                fontSize = 14.sp,
                lineHeight = 20.sp,
            ),
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = EurioSpacing.s4),
        )
    }
}
