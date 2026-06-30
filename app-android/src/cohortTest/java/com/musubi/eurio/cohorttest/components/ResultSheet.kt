package com.musubi.eurio.cohorttest.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.musubi.eurio.cohorttest.CoinDisplay
import com.musubi.eurio.cohorttest.TestResult
import com.musubi.eurio.ui.theme.Danger
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.FrauncesFamily
import com.musubi.eurio.ui.theme.Gold400
import com.musubi.eurio.ui.theme.Gold700
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.GoldSoft
import com.musubi.eurio.ui.theme.Indigo600
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink200
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.Ink700
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.MonoFamily
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.PaperSurface1
import com.musubi.eurio.ui.theme.Success
import com.musubi.eurio.ui.theme.Warning
import java.util.Locale

private enum class Verdict { Correct, Incorrect, Error }

/**
 * Bottom sheet that slides up over the camera + Snap CTA after a snap
 * lands. Mirrors the proto `.sheet`.
 *
 * Layout:
 *   - backdrop fade (tap to dismiss)
 *   - grabber pill at top
 *   - verdict band (Success/Danger/Warning gradient + icon + score)
 *   - "Tu visais" compact card (always)
 *   - "Le modèle a vu" compact card (only if incorrect and we have the
 *     predicted display in coinsDisplay)
 *   - expandable "Voir le top-3" with mono list
 *   - optional outlined "Refaire" (only when [result.error] != null)
 *   - filled "Test suivant →" CTA
 */
@Composable
fun ResultSheet(
    visible: Boolean,
    result: TestResult?,
    expected: CoinDisplay?,
    predictedDisplay: CoinDisplay?,
    onNext: () -> Unit,
    onRetry: (() -> Unit)?,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier.fillMaxSize()) {
        // Backdrop
        AnimatedVisibility(
            visible = visible && result != null,
            enter = fadeIn(animationSpec = tween(220)),
            exit = fadeOut(animationSpec = tween(180)),
            modifier = Modifier.fillMaxSize(),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.35f))
                    .clickable(onClick = onDismiss),
            )
        }

        // Sheet
        AnimatedVisibility(
            visible = visible && result != null,
            enter = slideInVertically(
                animationSpec = spring(
                    dampingRatio = 0.85f,
                    stiffness = 320f,
                ),
                initialOffsetY = { it },
            ),
            exit = slideOutVertically(
                animationSpec = tween(220),
                targetOffsetY = { it },
            ),
            modifier = Modifier.align(Alignment.BottomCenter),
        ) {
            if (result != null) {
                SheetContent(
                    result = result,
                    expected = expected,
                    predictedDisplay = predictedDisplay,
                    onNext = onNext,
                    onRetry = onRetry,
                )
            }
        }
    }
}

@Composable
private fun SheetContent(
    result: TestResult,
    expected: CoinDisplay?,
    predictedDisplay: CoinDisplay?,
    onNext: () -> Unit,
    onRetry: (() -> Unit)?,
) {
    val verdict = when {
        result.error != null -> Verdict.Error
        // Maille design_group : le modèle prédit des labels de classe
        // (COALESCE(design_group_id, eurio_id)). Un top-1 qui résout au même
        // groupe que la pièce visée EST correct. isCorrectEq subsume le match
        // strict (areEquivalent(x,x)=true) et l'équivalence design_group ;
        // c'est l'intention d'EquivalenceMap, qui retombe en strict si le
        // bundle n'a pas de carte d'équivalence.
        result.isCorrectEq -> Verdict.Correct
        else -> Verdict.Incorrect
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .shadow(20.dp, RoundedCornerShape(topStart = EurioRadii.xl, topEnd = EurioRadii.xl), clip = false)
            .clip(RoundedCornerShape(topStart = EurioRadii.xl, topEnd = EurioRadii.xl))
            .background(PaperSurface)
            .padding(bottom = EurioSpacing.s6),
    ) {
        // Grabber
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = EurioSpacing.s2, bottom = EurioSpacing.s1),
            contentAlignment = Alignment.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(width = 38.dp, height = 4.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(Ink200),
            )
        }

        VerdictBand(verdict = verdict, similarity = result.similarityTop1)

        Column(
            modifier = Modifier.padding(horizontal = EurioSpacing.s4),
            verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        ) {
            Spacer(Modifier.height(EurioSpacing.s4))
            if (expected != null) {
                CompareRow(label = "Tu visais", display = expected)
            }
            if (verdict == Verdict.Incorrect && predictedDisplay != null) {
                CompareRow(label = "Le modèle a vu", display = predictedDisplay)
            }
            Top3Section(result = result)
        }

        Spacer(Modifier.height(EurioSpacing.s5))

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = EurioSpacing.s4),
            horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        ) {
            if (onRetry != null && result.error != null) {
                OutlinedPillButton(
                    label = "Refaire",
                    onClick = onRetry,
                    modifier = Modifier.weight(1f),
                )
            }
            FilledPillButton(
                label = "Test suivant →",
                onClick = onNext,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun VerdictBand(verdict: Verdict, similarity: Float?) {
    val (gradient, icon, label, sub) = when (verdict) {
        Verdict.Correct -> Quad(
            Brush.linearGradient(listOf(Color(0xFF2FA971), Color(0xFF218A5C))),
            "✓",
            "Correct",
            "top-1 · arcface",
        )
        Verdict.Incorrect -> Quad(
            Brush.linearGradient(listOf(Color(0xFFC84444), Color(0xFFA33636))),
            "✗",
            "Incorrect",
            "top-1 ne matche pas",
        )
        Verdict.Error -> Quad(
            Brush.linearGradient(listOf(Color(0xFFD88A2D), Color(0xFFB36F1F))),
            "⚠",
            "Erreur d'inférence",
            "aucun match retourné",
        )
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(
                horizontal = EurioSpacing.s4,
                vertical = EurioSpacing.s2,
            )
            .clip(RoundedCornerShape(EurioRadii.md))
            .background(gradient)
            .padding(horizontal = EurioSpacing.s4, vertical = EurioSpacing.s3),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(CircleShape)
                .background(Color.White.copy(alpha = 0.18f))
                .border(1.dp, Color.White.copy(alpha = 0.35f), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                icon,
                color = Color.White,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(
                label,
                color = Color.White,
                fontFamily = FrauncesFamily,
                fontWeight = FontWeight.Medium,
                fontSize = 18.sp,
            )
            Text(
                sub,
                color = Color.White.copy(alpha = 0.85f),
                style = MonoBadgeStyle.copy(fontSize = 10.sp),
            )
        }
        Column(horizontalAlignment = Alignment.End) {
            Text(
                similarityText(similarity),
                color = Color.White,
                fontFamily = MonoFamily,
                fontWeight = FontWeight.Medium,
                fontSize = 22.sp,
            )
            Text(
                "SIMILARITÉ",
                color = Color.White.copy(alpha = 0.78f),
                style = MonoBadgeStyle.copy(fontSize = 9.sp),
            )
        }
    }
}

private fun similarityText(s: Float?): String {
    if (s == null) return "—"
    return String.format(Locale.FRENCH, "%.3f", s)
}

@Composable
private fun CompareRow(label: String, display: CoinDisplay) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.md))
            .background(PaperSurface1)
            .border(1.dp, Color.Black.copy(alpha = 0.04f), RoundedCornerShape(EurioRadii.md))
            .padding(EurioSpacing.s3),
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        Text(
            label.uppercase(),
            style = MonoBadgeStyle.copy(color = Ink500, fontSize = 10.sp),
        )
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        ) {
            MiniCoinThumb(imageUrl = display.image_obverse_url)
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    display.eyebrow_compact.uppercase(),
                    style = MonoBadgeStyle.copy(color = Ink500, fontSize = 10.sp),
                )
                Text(
                    display.title,
                    fontFamily = FrauncesFamily,
                    fontWeight = FontWeight.Medium,
                    fontSize = 16.sp,
                    lineHeight = 19.sp,
                    color = Ink,
                )
            }
        }
    }
}

@Composable
private fun MiniCoinThumb(imageUrl: String?) {
    Box(
        modifier = Modifier
            .size(48.dp)
            .clip(CircleShape)
            .background(
                Brush.radialGradient(
                    0.0f to GoldSoft,
                    0.55f to Gold400,
                    1.0f to Gold700,
                ),
            )
            .border(1.dp, GoldDeep.copy(alpha = 0.3f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        if (!imageUrl.isNullOrBlank()) {
            coil.compose.AsyncImage(
                model = imageUrl,
                contentDescription = null,
                modifier = Modifier
                    .fillMaxSize()
                    .clip(CircleShape),
            )
        } else {
            Text(
                "€",
                fontFamily = FrauncesFamily,
                fontStyle = FontStyle.Italic,
                color = GoldDeep,
                fontSize = 16.sp,
            )
        }
    }
}

@Composable
private fun Top3Section(result: TestResult) {
    var expanded by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2)) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(EurioRadii.md))
                .border(1.dp, Color.Black.copy(alpha = 0.10f), RoundedCornerShape(EurioRadii.md))
                .clickable { expanded = !expanded }
                .padding(horizontal = EurioSpacing.s3, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                if (expanded) "Masquer le top-3" else "Voir le top-3",
                color = Ink700,
                fontWeight = FontWeight.Medium,
                fontSize = 13.sp,
            )
            Text(
                "▾",
                color = Ink500,
                fontFamily = MonoFamily,
                fontSize = 14.sp,
                modifier = Modifier.rotate(if (expanded) 180f else 0f),
            )
        }
        AnimatedVisibility(
            visible = expanded,
            enter = expandVertically(animationSpec = tween(260)) + fadeIn(),
            exit = shrinkVertically(animationSpec = tween(220)) + fadeOut(),
        ) {
            Top3List(result = result)
        }
    }
}

@Composable
private fun Top3List(result: TestResult) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.md))
            .background(PaperSurface1),
    ) {
        if (result.predictedTop3.isEmpty()) {
            Row(modifier = Modifier.padding(EurioSpacing.s3)) {
                Text(
                    "—  inference returned no matches",
                    fontFamily = MonoFamily,
                    fontSize = 11.5.sp,
                    color = Ink400,
                )
            }
            return@Column
        }
        result.predictedTop3.forEachIndexed { i, m ->
            val isMatch = m.eurioId == result.expectedEurioId
            val rowBg = if (isMatch) Success.copy(alpha = 0.06f) else Color.Transparent
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(rowBg)
                    .padding(horizontal = EurioSpacing.s3, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "#${i + 1}",
                    color = Ink400,
                    fontFamily = MonoFamily,
                    fontSize = 11.5.sp,
                )
                Spacer(Modifier.width(EurioSpacing.s3))
                Text(
                    m.eurioId,
                    color = if (isMatch) Success else Ink700,
                    fontFamily = MonoFamily,
                    fontWeight = if (isMatch) FontWeight.Medium else FontWeight.Normal,
                    fontSize = 11.5.sp,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                )
                Text(
                    (if (isMatch) "✓ " else "") +
                        String.format(Locale.FRENCH, "%.3f", m.similarity),
                    color = if (isMatch) Success else Ink700,
                    fontFamily = MonoFamily,
                    fontSize = 11.5.sp,
                )
            }
        }
    }
}

@Composable
private fun FilledPillButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .height(56.dp)
            .shadow(16.dp, RoundedCornerShape(EurioRadii.full), clip = false)
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(Brush.verticalGradient(listOf(Indigo600, Indigo700)))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = Color.White,
            fontWeight = FontWeight.SemiBold,
            fontSize = 15.sp,
        )
    }
}

@Composable
private fun OutlinedPillButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .height(56.dp)
            .clip(RoundedCornerShape(EurioRadii.full))
            .border(1.dp, Indigo700.copy(alpha = 0.4f), RoundedCornerShape(EurioRadii.full))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = Indigo700,
            fontWeight = FontWeight.SemiBold,
            fontSize = 15.sp,
        )
    }
}

private data class Quad(
    val gradient: Brush,
    val icon: String,
    val label: String,
    val sub: String,
)
