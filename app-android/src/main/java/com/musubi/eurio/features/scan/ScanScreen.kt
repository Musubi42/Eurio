package com.musubi.eurio.features.scan

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.navigation.NavHostController
import com.musubi.eurio.ui.theme.Ink

// Placeholder Phase 0. Phase 1 migre la pipeline viewfinder/ML/card post-scan
// depuis LegacyScanActivity dans cet écran.
@Composable
fun ScanScreen(navController: NavHostController) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Ink),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "Scan · Phase 1",
            color = Color.White,
        )
    }
}
