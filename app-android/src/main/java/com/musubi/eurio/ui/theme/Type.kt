package com.musubi.eurio.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// TODO Phase 1+: charger les fonts custom (Fraunces, Inter Tight, JetBrains Mono)
// depuis res/font/ une fois les fichiers .ttf ajoutés. Pour l'instant on utilise
// les stacks système qui donnent un rendu proche sur Android (serif pour display,
// sans-serif pour UI, monospace pour debug).
private val DisplayFamily = FontFamily.Serif
private val UiFamily = FontFamily.SansSerif
val MonoFamily = FontFamily.Monospace

val EurioTypography = Typography(
    displayLarge = TextStyle(
        fontFamily = DisplayFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 60.sp,
        lineHeight = 66.sp,
    ),
    displayMedium = TextStyle(
        fontFamily = DisplayFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 40.sp,
        lineHeight = 44.sp,
    ),
    displaySmall = TextStyle(
        fontFamily = DisplayFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 32.sp,
        lineHeight = 36.sp,
    ),
    headlineLarge = TextStyle(
        fontFamily = DisplayFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 24.sp,
        lineHeight = 28.sp,
    ),
    headlineMedium = TextStyle(
        fontFamily = DisplayFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 20.sp,
        lineHeight = 24.sp,
    ),
    headlineSmall = TextStyle(
        fontFamily = UiFamily,
        fontWeight = FontWeight.SemiBold,
        fontSize = 18.sp,
        lineHeight = 22.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = UiFamily,
        fontWeight = FontWeight.SemiBold,
        fontSize = 18.sp,
        lineHeight = 22.sp,
    ),
    titleMedium = TextStyle(
        fontFamily = UiFamily,
        fontWeight = FontWeight.SemiBold,
        fontSize = 16.sp,
        lineHeight = 20.sp,
    ),
    titleSmall = TextStyle(
        fontFamily = UiFamily,
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        lineHeight = 18.sp,
    ),
    bodyLarge = TextStyle(
        fontFamily = UiFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 23.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = UiFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp,
    ),
    bodySmall = TextStyle(
        fontFamily = UiFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 16.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = UiFamily,
        fontWeight = FontWeight.Medium,
        fontSize = 14.sp,
        lineHeight = 18.sp,
    ),
    labelMedium = TextStyle(
        fontFamily = UiFamily,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = UiFamily,
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        lineHeight = 14.sp,
    ),
)

val EyebrowStyle = TextStyle(
    fontFamily = MonoFamily,
    fontWeight = FontWeight.Medium,
    fontSize = 10.sp,
    letterSpacing = 0.22.sp,
)

val MonoBadgeStyle = TextStyle(
    fontFamily = MonoFamily,
    fontWeight = FontWeight.Medium,
    fontSize = 10.sp,
    letterSpacing = 0.4.sp,
)
