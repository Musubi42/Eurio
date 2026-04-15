package com.musubi.eurio.ui.nav

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import com.musubi.eurio.features.coffre.CoffreScreen
import com.musubi.eurio.features.profil.ProfilScreen
import com.musubi.eurio.features.scan.ScanScreen

@Composable
fun EurioNavHost(
    navController: NavHostController,
    modifier: Modifier = Modifier,
) {
    NavHost(
        navController = navController,
        startDestination = EurioDestinations.SCAN,
        modifier = modifier,
    ) {
        composable(EurioDestinations.SCAN) {
            ScanScreen(navController = navController)
        }
        composable(EurioDestinations.COFFRE) {
            CoffreScreen(navController = navController)
        }
        composable(EurioDestinations.PROFIL) {
            ProfilScreen(navController = navController)
        }
    }
}
