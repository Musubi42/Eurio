package com.musubi.eurio.ui.nav

import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.LayoutDirection

// Shape custom pour la bottom bar : rectangle plein avec un cutout
// demi-cercle au top-center, pour accueillir le FAB scan en "notch".
//
// Le FAB, de rayon `notchRadius`, vient se loger dans ce creux avec un
// petit margin radial (`notchMargin`). Le haut du bar (y=0) est coupé
// sur une longueur 2·(notchRadius + notchMargin) et remplacé par un arc
// qui plonge de hauteur (notchRadius + notchMargin) vers l'intérieur.
//
// Spec visuelle : demi-cercle parfait, pas de courbes de raccord en S.
// Si un jour on veut adoucir la jonction, remplacer par un path à 3 arcs
// (gauche quadrant + cradle + droite quadrant) façon Material Components.
class NotchedBarShape(
    private val notchRadius: Dp,
    private val notchMargin: Dp,
) : Shape {
    override fun createOutline(
        size: Size,
        layoutDirection: LayoutDirection,
        density: Density,
    ): Outline {
        val rPx = with(density) { notchRadius.toPx() }
        val mPx = with(density) { notchMargin.toPx() }
        val effR = rPx + mPx
        val cx = size.width / 2f

        val path = Path().apply {
            moveTo(0f, 0f)
            lineTo(cx - effR, 0f)
            // Arc demi-cercle descendant : start point (cx - effR, 0),
            // passes through (cx, effR), ends at (cx + effR, 0).
            // Compose y-down → sweep négatif pour aller 180° → 90° → 0°
            // en passant par le bas du cercle (y = +effR, inside the bar).
            arcTo(
                rect = Rect(
                    left = cx - effR,
                    top = -effR,
                    right = cx + effR,
                    bottom = effR,
                ),
                startAngleDegrees = 180f,
                sweepAngleDegrees = -180f,
                forceMoveTo = false,
            )
            lineTo(size.width, 0f)
            lineTo(size.width, size.height)
            lineTo(0f, size.height)
            close()
        }
        return Outline.Generic(path)
    }
}
