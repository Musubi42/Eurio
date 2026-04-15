package com.musubi.eurio.features.coffre

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController

// Placeholder Phase 0. Phases 2-4 hydratent les 3 sous-vues (Mes pièces, Sets, Catalogue).
@Composable
fun CoffreScreen(navController: NavHostController) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "Coffre · Phases 2-4",
            style = MaterialTheme.typography.headlineMedium,
        )
    }
}
