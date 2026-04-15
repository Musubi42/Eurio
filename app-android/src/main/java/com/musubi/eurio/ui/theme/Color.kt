package com.musubi.eurio.ui.theme

import androidx.compose.ui.graphics.Color

// ─────────────────────────────────────────────────────────────────────────────
// Eurio design tokens — Compose mirror de shared/tokens.css
// Source de vérité : /shared/tokens.css (racine monorepo). Ne pas dériver.
// ─────────────────────────────────────────────────────────────────────────────

// Indigo scale (brand primary)
val Indigo50 = Color(0xFFEDEDF5)
val Indigo100 = Color(0xFFD8D9E8)
val Indigo200 = Color(0xFFB1B3D0)
val Indigo300 = Color(0xFF8A8DB8)
val Indigo400 = Color(0xFF5A5B8A)
val Indigo500 = Color(0xFF33346A)
val Indigo600 = Color(0xFF242556)
val Indigo700 = Color(0xFF1A1B4B) // BRAND primary
val Indigo800 = Color(0xFF14142F)
val Indigo900 = Color(0xFF0E0E1F)
val Indigo950 = Color(0xFF0B0C22)

// Gold scale (accents, moments)
val GoldSoft = Color(0xFFF5EBD3)
val Gold100 = Color(0xFFF5EBD3)
val Gold300 = Color(0xFFE0C688)
val Gold400 = Color(0xFFD9BF87)
val Gold = Color(0xFFC8A864) // canonical
val Gold500 = Color(0xFFC8A864)
val Gold600 = Color(0xFFB8974E)
val Gold700 = Color(0xFFA7883F)
val GoldDeep = Color(0xFF8F7637)

// Surfaces & ink — préfixe Paper pour éviter le shadow avec le Composable
// androidx.compose.material3.Surface.
val PaperSurface = Color(0xFFFAFAF8)
val PaperSurface1 = Color(0xFFF4F3EE)
val PaperSurface2 = Color(0xFFECEBE4)
val PaperSurface3 = Color(0xFFE2E0D6)
val Paper = Color(0xFFF5F3EC)

val Ink = Color(0xFF0E0E1F)
val InkSoft = Color(0xFF14142A)
val Ink700 = Color(0xFF2A2B3F)
val Ink500 = Color(0xFF55566C)
val Ink400 = Color(0xFF7A7B90)
val Ink300 = Color(0xFFA6A7B6)
val Ink200 = Color(0xFFC8C9D4)

// Neutral grays
val Gray50 = Color(0xFFF2F2EE)
val Gray100 = Color(0xFFE4E4DE)
val Gray200 = Color(0xFFC9C9C1)
val Gray300 = Color(0xFFA6A69E)
val Gray400 = Color(0xFF8B8B85)
val Gray500 = Color(0xFF6B6B66)
val Gray600 = Color(0xFF5A5A58)
val Gray700 = Color(0xFF3A3A44)
val Gray800 = Color(0xFF26262F)
val Gray900 = Color(0xFF14141A)

// Semantic
val Success = Color(0xFF2FA971)
val Warning = Color(0xFFD88A2D)
val Danger = Color(0xFFD14343)
val DebugRed = Color(0xFFD14343) // LED pastille badge version
