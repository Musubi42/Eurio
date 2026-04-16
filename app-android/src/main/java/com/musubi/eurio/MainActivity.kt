package com.musubi.eurio

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.musubi.eurio.ui.components.ScanFab
import com.musubi.eurio.ui.nav.BarHeight
import com.musubi.eurio.ui.nav.EurioBottomBar
import com.musubi.eurio.ui.nav.EurioDestinations
import com.musubi.eurio.ui.nav.EurioNavHost
import com.musubi.eurio.ui.theme.EurioTheme
import kotlinx.coroutines.flow.first
import org.json.JSONObject

// Host activity unique. Phase 0 = nav shell M3 notched :
//   Box {
//     Scaffold { bottomBar = EurioBottomBar (notched Surface) ; content = NavHost }
//     ScanFab  (overlay au-dessus, descend dans le notch)
//   }
// Le FAB est rendu en overlay plutôt que via Scaffold.floatingActionButton pour
// avoir un contrôle précis de sa position dans le creux de la bottom bar.
// Phase 1+ hydrate chaque destination.
object ParityFlags {
    var mockCamera: Boolean = false
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            EurioTheme {
                val navController = rememberNavController()
                val backStackEntry by navController.currentBackStackEntryAsState()

                // Debug-only: handle eurio:// deep links for parity viewer
                if (BuildConfig.DEBUG) {
                    LaunchedEffect(Unit) {
                        handleParityDeepLink(intent, navController)
                    }
                }
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

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
    }

    private suspend fun handleParityDeepLink(intent: Intent?, navController: NavHostController) {
        val uri = intent?.data ?: return
        if (uri.scheme != "eurio") return

        when (uri.host) {
            "parity" -> {
                val action = uri.pathSegments?.firstOrNull()
                if (action == "seed") {
                    val fixture = uri.getQueryParameter("fixture") ?: return
                    val app = application as EurioApp
                    // Wait for catalog bootstrap so FK constraints are satisfied
                    app.bootstrapState.first { it == BootstrapState.Ready }
                    try {
                        seedFromFixture(fixture, app)
                    } catch (e: Exception) {
                        Log.e("Eurio", "[parity] Seed failed for fixture=$fixture", e)
                    }
                }
            }
            "scene" -> {
                val sceneId = uri.pathSegments?.firstOrNull() ?: return
                ParityFlags.mockCamera = uri.getQueryParameter("mock_camera") == "true"
                val route = resolveSceneRoute(sceneId) ?: run {
                    Log.w("Eurio", "[parity] Unknown scene: $sceneId")
                    return
                }
                Log.d("Eurio", "[parity] Deep link → scene=$sceneId route=$route mockCamera=${ParityFlags.mockCamera}")
                navController.navigate(route) {
                    launchSingleTop = true
                }
            }
        }
    }

    private suspend fun seedFromFixture(fixtureName: String, app: EurioApp) {
        val path = "fixtures/preset-$fixtureName.json"
        val jsonText = assets.open(path).bufferedReader().readText()
        val root = JSONObject(jsonText)
        val collection = root.getJSONArray("collection")
        val entries = (0 until collection.length()).map { i ->
            val item = collection.getJSONObject(i)
            com.musubi.eurio.data.local.entities.VaultEntryEntity(
                coinEurioId = item.getString("eurioId"),
                scannedAt = item.getLong("addedAt"),
                source = com.musubi.eurio.domain.ScanSource.MANUAL_ADD,
                confidence = null,
                notes = if (item.isNull("note")) null else item.getString("note"),
            )
        }
        val dao = app.database.vaultDao()
        dao.clearAll()
        dao.insertAll(entries)
        Log.i("Eurio", "[parity] Seeded vault with ${entries.size} entries from '$fixtureName'")
    }

    companion object {
        private val SCENE_ROUTE_MAP = mapOf(
            // Scan states — all land on the scan destination
            "scan-idle" to EurioDestinations.SCAN,
            "scan-detecting" to EurioDestinations.SCAN,
            "scan-matched" to EurioDestinations.SCAN,
            "scan-not-identified" to EurioDestinations.SCAN,
            "scan-failure" to EurioDestinations.SCAN,
            "scan-debug" to EurioDestinations.SCAN,
            // Coffre
            "vault-home" to EurioDestinations.COFFRE,
            "vault-empty" to EurioDestinations.COFFRE,
            "vault-filters" to EurioDestinations.COFFRE,
            "vault-search" to EurioDestinations.COFFRE,
            "vault-remove-confirm" to EurioDestinations.COFFRE,
            "vault-sets-list" to EurioDestinations.COFFRE,
            "vault-catalog-map" to EurioDestinations.COFFRE,
            // Profil
            "profile" to EurioDestinations.PROFIL,
            "profile-achievements" to EurioDestinations.PROFIL,
            "profile-settings" to EurioDestinations.PROFIL,
        )

        private fun resolveSceneRoute(sceneId: String): String? = SCENE_ROUTE_MAP[sceneId]
    }
}
