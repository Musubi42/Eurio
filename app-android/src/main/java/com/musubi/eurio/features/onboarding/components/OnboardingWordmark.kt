package com.musubi.eurio.features.onboarding.components

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.musubi.eurio.ui.theme.FrauncesFamily
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.PaperSurface

// Reusable "Eurio" wordmark with italic gold "io" tail. Matches the proto's
// onboarding-*-brand selector (Fraunces, indigo surface color on the plain
// part, gold italic on "io").
@Composable
fun EurioWordmark(
    modifier: Modifier = Modifier,
    fontSize: TextUnit = 18.sp,
    baseColor: Color = PaperSurface,
) {
    Text(
        text = wordmark(baseColor),
        modifier = modifier,
        style = MaterialTheme.typography.titleLarge.copy(
            fontFamily = FrauncesFamily,
            fontSize = fontSize,
            letterSpacing = (-0.02).em,
        ),
    )
}

private fun wordmark(baseColor: Color): AnnotatedString = buildAnnotatedString {
    withStyle(SpanStyle(color = baseColor)) { append("Eur") }
    withStyle(SpanStyle(color = Gold, fontStyle = FontStyle.Italic)) { append("io") }
}
