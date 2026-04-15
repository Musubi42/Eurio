package com.musubi.eurio

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.musubi.eurio.ui.components.ScanFab
import com.musubi.eurio.ui.nav.BarHeight
import com.musubi.eurio.ui.nav.EurioBottomBar
import com.musubi.eurio.ui.nav.EurioDestinations
import com.musubi.eurio.ui.nav.EurioNavHost
import com.musubi.eurio.ui.theme.EurioTheme

// Host activity unique. Phase 0 = nav shell M3 notched :
//   Box {
//     Scaffold { bottomBar = EurioBottomBar (notched Surface) ; content = NavHost }
//     ScanFab  (overlay au-dessus, descend dans le notch)
//   }
// Le FAB est rendu en overlay plutôt que via Scaffold.floatingActionButton pour
// avoir un contrôle précis de sa position dans le creux de la bottom bar.
// Phase 1+ hydrate chaque destination.
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            EurioTheme {
                val navController = rememberNavController()
                val backStackEntry by navController.currentBackStackEntryAsState()
                val currentRoute = backStackEntry?.destination?.route

                Box(modifier = Modifier.fillMaxSize()) {
                    Scaffold(
                        modifier = Modifier.fillMaxSize(),
                        bottomBar = {
                            EurioBottomBar(
                                currentRoute = currentRoute,
                                onTabSelected = { route ->
                                    navController.navigate(route) {
                                        launchSingleTop = true
                                        popUpTo(EurioDestinations.SCAN) {
                                            saveState = true
                                        }
                                        restoreState = true
                                    }
                                },
                            )
                        },
                    ) { innerPadding ->
                        EurioNavHost(
                            navController = navController,
                            modifier = Modifier.padding(innerPadding),
                        )
                    }

                    // FAB scan overlay — aligné bottom center, remonté pour que
                    // son centre tombe ~4dp sous le top de la navbar, soit
                    // niché dans le creux demi-lune du notch.
                    // offset vertical = -(BarHeight - FAB.radius - 4dp bottom inset)
                    //                 = -(76 - 32 - 4) = -40dp
                    ScanFab(
                        onClick = {
                            navController.navigate(EurioDestinations.SCAN) {
                                launchSingleTop = true
                                popUpTo(EurioDestinations.SCAN) { inclusive = true }
                            }
                        },
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .navigationBarsPadding()
                            .offset(y = -(BarHeight - 32.dp - 4.dp)),
                    )
                }
            }
        }
    }
}
