package com.musubi.eurio.features.profil

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController

// Placeholder Phase 0. Phase 5 hydrate grade + streak + badges + stats + réglages.
@Composable
fun ProfilScreen(navController: NavHostController) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "Profil · Phase 5",
            style = MaterialTheme.typography.headlineMedium,
        )
    }
}
