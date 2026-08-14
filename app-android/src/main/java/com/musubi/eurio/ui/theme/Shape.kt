// ─────────────────────────────────────────────────────────────────────────────
// AUTO-GENERATED from shared/tokens.css — DO NOT EDIT MANUALLY.
// Run `go-task tokens:generate` (or `node scripts/generate_tokens.mjs`)
// after editing shared/tokens.css to regenerate this file.
// See docs/design/_shared/parity-rules.md §R1.
// ─────────────────────────────────────────────────────────────────────────────

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
    val r2xl = 32.dp
    val full = 999.dp
    val device = 54.dp
}

val EurioShapes = Shapes(
    extraSmall = RoundedCornerShape(EurioRadii.xs),
    small = RoundedCornerShape(EurioRadii.sm),
    medium = RoundedCornerShape(EurioRadii.md),
    large = RoundedCornerShape(EurioRadii.lg),
    extraLarge = RoundedCornerShape(EurioRadii.xl),
)
