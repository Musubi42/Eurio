package com.musubi.eurio.features.dev

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import com.musubi.eurio.EurioApp
import com.musubi.eurio.data.repository.CoinViewData
import com.musubi.eurio.features.scan.components.Coin3DViewer

// Phase 0–2 du portage 3D viewer (cf. docs/coin-3d-viewer/porting-android.md).
// Host minimal pour itérer sur Coin3DViewer en dehors du scan flow. À retirer
// quand le carousel debug intégré sera fonctionnel (Phase 4).
//
// Charge la pièce-test 226447 (2 € DE 2020 "Kniefall von Warschau") depuis Room
// pour exercer le pipeline texture (Phase 2b). Les premières frames affichent le
// fallback flat-color le temps que Coil télécharge les photos.
private const val SANDBOX_NUMISTA_ID = "226447"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Coin3DSandboxScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as EurioApp
    var coin by remember { mutableStateOf<CoinViewData?>(null) }

    LaunchedEffect(SANDBOX_NUMISTA_ID) {
        coin = app.coinRepository.resolveByClassifierName(SANDBOX_NUMISTA_ID)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Coin 3D Sandbox") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .background(Color(0xFF15151C)),
        ) {
            Coin3DViewer(
                eurioId = coin?.eurioId,
                obverseImageUrl = coin?.imageObverseUrl,
                reverseImageUrl = coin?.imageReverseUrl,
                obverseMeta = coin?.obversePhotoMeta,
                reverseMeta = coin?.reversePhotoMeta,
                modifier = Modifier.fillMaxSize(),
                flipKey = coin?.eurioId,
            )
        }
    }
}
