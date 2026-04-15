package com.musubi.eurio.ui.nav

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountBalanceWallet
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// Bottom bar Eurio — Surface custom avec shape notched pour accueillir le
// FAB scan en "creux demi-lune". Shadow elevation pour la séparation
// visuelle d'avec le contenu des écrans.
//
// 2 onglets (Coffre gauche, Profil droite) dans un Row avec un Spacer
// central qui laisse la place au notch + FAB. Scalable à 4 onglets +
// FAB central plus tard sans refactor de la shape.
val BarHeight = 76.dp
val NotchRadius = 34.dp
val NotchMargin = 5.dp

@Composable
fun EurioBottomBar(
    currentRoute: String?,
    onTabSelected: (String) -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .navigationBarsPadding(),
        shape = NotchedBarShape(notchRadius = NotchRadius, notchMargin = NotchMargin),
        color = MaterialTheme.colorScheme.surface,
        contentColor = MaterialTheme.colorScheme.onSurface,
        shadowElevation = 10.dp,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(BarHeight)
                .padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            NavTab(
                label = BottomNavTab.COFFRE.labelFr,
                icon = Icons.Outlined.AccountBalanceWallet,
                selected = currentRoute == BottomNavTab.COFFRE.route,
                onClick = { onTabSelected(BottomNavTab.COFFRE.route) },
            )
            // Espace réservé pour le FAB scan rendu par Scaffold au-dessus,
            // largeur = diamètre notch (2·(r+margin)) + petit padding visuel.
            Spacer(Modifier.width((NotchRadius + NotchMargin) * 2 + 24.dp))
            NavTab(
                label = BottomNavTab.PROFIL.labelFr,
                icon = Icons.Outlined.Person,
                selected = currentRoute == BottomNavTab.PROFIL.route,
                onClick = { onTabSelected(BottomNavTab.PROFIL.route) },
            )
        }
    }
}

@Composable
private fun NavTab(
    label: String,
    icon: ImageVector,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val activeColor = MaterialTheme.colorScheme.primary
    val idleColor = MaterialTheme.colorScheme.onSurfaceVariant
    val tint = if (selected) activeColor else idleColor
    IconButton(
        onClick = onClick,
        modifier = Modifier
            .size(width = 64.dp, height = BarHeight)
            .semantics {
                role = Role.Tab
                this.selected = selected
            },
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.fillMaxSize(),
        ) {
            Icon(
                imageVector = icon,
                contentDescription = label,
                tint = tint,
                modifier = Modifier.size(24.dp),
            )
            Spacer(Modifier.height(2.dp))
            Text(
                text = label,
                color = tint,
                fontSize = 10.sp,
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}
