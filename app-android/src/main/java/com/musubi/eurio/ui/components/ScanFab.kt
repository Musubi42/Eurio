package com.musubi.eurio.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CropFree
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Indigo500
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Indigo800

// FAB scan central — circle 64dp avec gradient radial indigo et icône gold.
// Sans bordure : la séparation visuelle d'avec la bottom bar est assurée par
// le notch demi-lune dessiné par NotchedBarShape (margin radial inclus).
//
// Implémenté via Surface(onClick) M3 : ripple + sémantique + click feedback
// natifs, avec le gradient peint en background sur un Box interne.
@Composable
fun ScanFab(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val gradient = Brush.radialGradient(
        colors = listOf(Indigo500, Indigo700, Indigo800),
        radius = 110f,
    )
    Surface(
        onClick = onClick,
        modifier = modifier
            .size(64.dp)
            .shadow(
                elevation = 10.dp,
                shape = CircleShape,
                ambientColor = Indigo700,
                spotColor = Indigo700,
            )
            .semantics {
                role = Role.Button
                contentDescription = "Scanner une pièce"
            },
        shape = CircleShape,
        color = Color.Transparent,
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(gradient, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            // CropFree = cadre à coins en équerre (AF focus frame), orienté
            // "scan d'objet". Remplacement futur par un SVG custom "scan de
            // pièce" (Phase 1+).
            Icon(
                imageVector = Icons.Outlined.CropFree,
                contentDescription = null, // porté par le Surface
                tint = Gold,
                modifier = Modifier.size(30.dp),
            )
        }
    }
}
