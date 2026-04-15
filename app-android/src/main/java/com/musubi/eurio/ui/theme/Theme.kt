package com.musubi.eurio.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

// Light scheme = app défaut (le proto est light-first avec chrome dark ponctuel
// contrôlé au niveau des screens via overlay, pas via dark theme Material).
private val EurioLightColorScheme = lightColorScheme(
    primary = Indigo700,
    onPrimary = PaperSurface,
    primaryContainer = Indigo100,
    onPrimaryContainer = Indigo900,

    secondary = Gold,
    onSecondary = Ink,
    secondaryContainer = Gold100,
    onSecondaryContainer = GoldDeep,

    tertiary = Gold600,
    onTertiary = PaperSurface,

    background = PaperSurface,
    onBackground = Ink,

    surface = PaperSurface,
    onSurface = Ink,
    surfaceVariant = PaperSurface1,
    onSurfaceVariant = Ink500,
    surfaceContainer = PaperSurface1,
    surfaceContainerHigh = PaperSurface2,
    surfaceContainerHighest = PaperSurface3,

    outline = Gray200,
    outlineVariant = Gray100,

    error = Danger,
    onError = PaperSurface,
)

// Dark scheme — utilisé uniquement si l'OS force dark mode. Le scan overlay
// utilise un chrome dark ponctuel directement, sans switcher le ColorScheme.
private val EurioDarkColorScheme = darkColorScheme(
    primary = Gold,
    onPrimary = Indigo900,
    primaryContainer = Indigo700,
    onPrimaryContainer = Gold100,

    secondary = Gold400,
    onSecondary = Indigo900,

    tertiary = Indigo300,
    onTertiary = Indigo900,

    background = Indigo950,
    onBackground = PaperSurface,

    surface = Indigo900,
    onSurface = PaperSurface,
    surfaceVariant = Indigo800,
    onSurfaceVariant = Ink200,

    outline = Ink700,
    outlineVariant = Ink500,

    error = Danger,
    onError = PaperSurface,
)

@Composable
fun EurioTheme(
    darkTheme: Boolean = false, // défaut light, l'OS ne force pas
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) EurioDarkColorScheme else EurioLightColorScheme
    MaterialTheme(
        colorScheme = colorScheme,
        typography = EurioTypography,
        shapes = EurioShapes,
        content = content,
    )
}
