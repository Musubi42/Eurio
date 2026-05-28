package com.musubi.eurio.features.scan

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.musubi.eurio.features.scan.components.Coin3DViewer
import kotlinx.coroutines.delay
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import com.musubi.eurio.features.scan.components.CameraPreview
import com.musubi.eurio.features.scan.components.ScanAcceptedCard
import com.musubi.eurio.features.scan.components.ScanDebugOverlay
import com.musubi.eurio.features.scan.components.ScanDetectingLayer
import com.musubi.eurio.features.scan.components.ScanFailureLayer
import com.musubi.eurio.features.scan.components.ScanIdleLayer
import com.musubi.eurio.features.scan.debug.DebugBarLauncher
import com.musubi.eurio.features.scan.debug.ScanHud
import com.musubi.eurio.features.scan.debug.ScanLockOverlay
import com.musubi.eurio.BuildConfig
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Ink

/**
 * Top-level composable for the Scan destination.
 *
 * Responsibilities:
 *  - Hosts the CameraX preview + ImageAnalysis pipeline (lifecycle-bound).
 *  - Observes [ScanViewModel.state] and renders the matching layer.
 *  - Handles already-owned feedback via a Snackbar.
 *  - Overlays the debug panels when [ScanViewModel.debugMode] is true.
 *
 * The ViewModel is injected, not created internally: integration wires a
 * Factory that supplies the three repositories and a [com.musubi.eurio.ml.CoinAnalyzer]
 * instance whose onResult has been bound to [ScanViewModel.onScanResult].
 */
@Composable
fun ScanScreen(
    viewModel: ScanViewModel,
    versionName: String,
    onOpenCoinDetail: (String) -> Unit,
    onOpenDevTool: ((com.musubi.eurio.features.scan.debug.DevTool) -> Unit)? = null,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val debugMode by viewModel.debugMode.collectAsStateWithLifecycle()
    val streakCount by viewModel.streakCount.collectAsStateWithLifecycle()
    val debugData by viewModel.debugData.collectAsStateWithLifecycle()
    val recordMode by viewModel.recordMode.collectAsStateWithLifecycle()
    val recordedFrameCount by viewModel.recordedFrameCount.collectAsStateWithLifecycle()

    val snackbarHostState = remember { SnackbarHostState() }

    // Show the "déjà dans ton coffre" snackbar when state becomes Accepted
    // with alreadyOwned=true.
    LaunchedEffect(state) {
        val s = state
        if (s is ScanUiState.Accepted && s.alreadyOwned) {
            snackbarHostState.showSnackbar(
                message = "Déjà dans ton coffre — continue",
            )
        }
    }

    // Chunk-5d — D17 "Belle prise" snackbar with one-tap revert.
    // ShowSnackbar suspends until the user dismisses or taps the action;
    // viewModel.onRevertPromotion is called only on the action branch.
    LaunchedEffect(viewModel) {
        viewModel.snackbarEvents.collect { event ->
            when (event) {
                is ScanSnackbarEvent.PrimaryPromoted -> {
                    val result = snackbarHostState.showSnackbar(
                        message = "Belle prise · en faire la photo de référence ?",
                        actionLabel = "Annuler",
                        withDismissAction = true,
                        duration = androidx.compose.material3.SnackbarDuration.Long,
                    )
                    if (result == androidx.compose.material3.SnackbarResult.ActionPerformed) {
                        viewModel.onRevertPromotion(event)
                    }
                }
            }
        }
    }


    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        containerColor = Color.Transparent,
    ) { insets ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Ink)
                .padding(insets),
        ) {
            CameraPreview(
                onFrame = { image -> viewModel.onFrame(image) },
                onCameraReady = { camera, imageCapture ->
                    viewModel.attachCamera(camera, imageCapture)
                },
                onCameraReleased = { viewModel.detachCamera() },
                modifier = Modifier.fillMaxSize(),
            )

            when (val s = state) {
                is ScanUiState.Idle -> ScanIdleLayer()
                is ScanUiState.Detecting -> ScanDetectingLayer()
                is ScanUiState.Accepted -> {
                    // Discovery moment (Phase 5) : the 3D viewer fills the
                    // screen behind the AcceptedCard and plays a flip on every
                    // new coin. The card slides in 400 ms later — the flip is
                    // still mid-rotation when the card arrives, which reads as
                    // "the coin lands and the sheet catches it".
                    Coin3DViewer(
                        eurioId = s.coin.eurioId,
                        obverseImageUrl = s.coin.imageObverseUrl,
                        reverseImageUrl = s.coin.imageReverseUrl,
                        obverseMeta = s.coin.obversePhotoMeta,
                        reverseMeta = s.coin.reversePhotoMeta,
                        flipKey = s.coin.eurioId,
                        modifier = Modifier.fillMaxSize(),
                    )
                    var cardVisible by remember(s.coin.eurioId) { mutableStateOf(false) }
                    LaunchedEffect(s.coin.eurioId) {
                        delay(400)
                        cardVisible = true
                    }
                    if (cardVisible) {
                        ScanAcceptedCard(
                            coin = s.coin,
                            confidence = s.confidence,
                            onDetail = { onOpenCoinDetail(s.coin.eurioId) },
                            onAddToVault = { viewModel.onAddToVault() },
                            onDismiss = { viewModel.onDismissCard() },
                            modifier = Modifier.align(Alignment.BottomCenter),
                        )
                    }
                }
                is ScanUiState.NotIdentified -> {
                    // UX decision: scan is continuous like a QR scanner.
                    // NotIdentified is never emitted by the VM — this branch
                    // is kept as a no-op for sealed class exhaustiveness.
                    ScanIdleLayer()
                }
                is ScanUiState.Failure -> {
                    ScanFailureLayer(
                        reason = s.reason,
                        onRetry = { viewModel.onDismissCard() },
                    )
                }
            }

            // Top bar overlay
            ScanTopBar(
                versionName = versionName,
                streakCount = streakCount,
                onVersionBadgeTap = { viewModel.onVersionBadgeTap() },
                modifier = Modifier.align(Alignment.TopCenter),
            )

            // Already-owned inline hint (small thumbnail near the top bar).
            (state as? ScanUiState.Accepted)?.takeIf { it.alreadyOwned }?.let { s ->
                Row(
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = EurioSpacing.s11),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        modifier = Modifier
                            .size(32.dp)
                            .clip(CircleShape)
                            .background(Color.Black.copy(alpha = 0.55f)),
                    ) {
                        if (s.coin.imageObverseUrl != null) {
                            AsyncImage(
                                model = s.coin.imageObverseUrl,
                                contentDescription = s.coin.nameFr,
                                modifier = Modifier.fillMaxSize().clip(CircleShape),
                            )
                        }
                    }
                }
            }

            // Best-frame capture chunk-1 — debug-only HUD + DBG FAB. Compiled
            // out (dead-code-eliminated by R8 when min-enabled) in release via
            // the BuildConfig.DEBUG guard. See docs/best-frame-capture/chunk-1.
            if (BuildConfig.DEBUG) {
                val hudState by viewModel.hudState.collectAsStateWithLifecycle()
                val shadowState by viewModel.scanMachineState.collectAsStateWithLifecycle()
                ScanLockOverlay(
                    bbox = debugData.bbox,
                    shadowState = shadowState,
                    abortEvents = viewModel.abortEvents,
                    modifier = Modifier.fillMaxSize(),
                )
                ScanHud(
                    state = hudState,
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = 120.dp),
                )
                DebugBarLauncher(
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .padding(end = EurioSpacing.s3, bottom = EurioSpacing.s3),
                    onOpenDevTool = onOpenDevTool,
                )
            }

            if (debugMode) {
                ScanDebugOverlay(
                    data = debugData,
                    recording = recordMode,
                    recordedFrameCount = recordedFrameCount,
                    onRecordToggle = { viewModel.onRecordToggle() },
                )
            }
        }
    }
}

// CameraPreview + MockCameraPreview ont été extraits dans
// features/scan/components/CameraPreview.kt pour être réutilisés par les
// écrans /dev/* (refacto 2026-05-28).
