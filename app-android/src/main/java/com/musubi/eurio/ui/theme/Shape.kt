package com.musubi.eurio.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.ui.unit.dp

// Mirror de --radius-* dans shared/tokens.css
object EurioRadii {
    val xs = 6.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
    val xxl = 32.dp
    val full = 999.dp
}

val EurioShapes = Shapes(
    extraSmall = RoundedCornerShape(EurioRadii.xs),
    small = RoundedCornerShape(EurioRadii.sm),
    medium = RoundedCornerShape(EurioRadii.md),
    large = RoundedCornerShape(EurioRadii.lg),
    extraLarge = RoundedCornerShape(EurioRadii.xl),
)
