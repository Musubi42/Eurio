package com.musubi.eurio.features.scan

import android.Manifest
import android.content.pm.PackageManager
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CameraAlt
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import com.musubi.eurio.features.scan.components.ScanAcceptedCard
import com.musubi.eurio.features.scan.components.ScanDebugOverlay
import com.musubi.eurio.features.scan.components.ScanDetectingLayer
import com.musubi.eurio.features.scan.components.ScanFailureLayer
import com.musubi.eurio.features.scan.components.ScanIdleLayer
import androidx.compose.ui.graphics.Brush
import com.musubi.eurio.BuildConfig
import com.musubi.eurio.ParityFlags
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Ink
import java.util.concurrent.Executors

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
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val debugMode by viewModel.debugMode.collectAsStateWithLifecycle()
    val streakCount by viewModel.streakCount.collectAsStateWithLifecycle()
    val debugData by viewModel.debugData.collectAsStateWithLifecycle()

    val snackbarHostState = remember { SnackbarHostState() }

    // Show the "déjà dans ton coffre" snackbar when state becomes Accepted
    // with alreadyOwned=true.
    LaunchedEffect(state) {
        val s = state
        if (s is ScanState.Accepted && s.alreadyOwned) {
            snackbarHostState.showSnackbar(
                message = "Déjà dans ton coffre — continue",
            )
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
                modifier = Modifier.fillMaxSize(),
            )

            // State-driven layer
            when (val s = state) {
                is ScanState.Idle -> ScanIdleLayer()
                is ScanState.Detecting -> ScanDetectingLayer()
                is ScanState.Accepted -> {
                    ScanAcceptedCard(
                        coin = s.coin,
                        confidence = s.confidence,
                        onDetail = { onOpenCoinDetail(s.coin.eurioId) },
                        onAddToVault = { viewModel.onAddToVault() },
                        onDismiss = { viewModel.onDismissCard() },
                        modifier = Modifier.align(Alignment.BottomCenter),
                    )
                }
                is ScanState.NotIdentified -> {
                    // UX decision: scan is continuous like a QR scanner.
                    // NotIdentified is never emitted by the VM — this branch
                    // is kept as a no-op for sealed class exhaustiveness.
                    ScanIdleLayer()
                }
                is ScanState.Failure -> {
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

            // Already-owned inline hint (small thumbnail near the top bar)
            (state as? ScanState.Accepted)?.takeIf { it.alreadyOwned }?.let { s ->
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

            if (debugMode) {
                ScanDebugOverlay(
                    data = debugData,
                    onDump = { viewModel.onCaptureClicked() },
                    onDumps = {},
                    onReplay = {},
                    onFreeze = {},
                    onForce = {},
                    onEmbed = {},
                    onStats = {},
                )
            }
        }
    }
}

@Composable
private fun CameraPreview(
    onFrame: (androidx.camera.core.ImageProxy) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (BuildConfig.DEBUG && ParityFlags.mockCamera) {
        MockCameraPreview(modifier = modifier)
        return
    }

    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }

    // Bail out if the user hasn't granted CAMERA; the permission flow is
    // handled at the Activity level (MainActivity).
    val hasPermission = remember {
        ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
    }

    if (!hasPermission) {
        Box(
            modifier = modifier.background(Ink),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "Autorisation caméra requise",
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White.copy(alpha = 0.7f),
            )
        }
        return
    }

    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            PreviewView(ctx).also { previewView ->
                val providerFuture = ProcessCameraProvider.getInstance(ctx)
                providerFuture.addListener(
                    {
                        val provider = providerFuture.get()
                        val preview = Preview.Builder().build().also {
                            it.surfaceProvider = previewView.surfaceProvider
                        }
                        val analysis = ImageAnalysis.Builder()
                            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                            .build()
                            .also { it.setAnalyzer(executor) { image -> onFrame(image) } }
                        try {
                            provider.unbindAll()
                            provider.bindToLifecycle(
                                lifecycleOwner,
                                CameraSelector.DEFAULT_BACK_CAMERA,
                                preview,
                                analysis,
                            )
                        } catch (_: Exception) {
                            // Swallow — the outer Scaffold will re-render on
                            // next composition and retry. A persistent bind
                            // failure should surface via ScanState.Failure,
                            // but that plumbing lives at integration time.
                        }
                    },
                    ContextCompat.getMainExecutor(ctx),
                )
            }
        },
    )

    DisposableEffect(lifecycleOwner) {
        onDispose {
            executor.shutdown()
            ProcessCameraProvider.getInstance(context).get().unbindAll()
        }
    }
}

@Composable
private fun MockCameraPreview(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier.background(
            brush = Brush.verticalGradient(
                colors = listOf(Color(0xFF1a1a2e), Color(0xFF16213e)),
            ),
        ),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Icon(
                Icons.Outlined.CameraAlt,
                contentDescription = null,
                modifier = Modifier.size(48.dp),
                tint = Color.White.copy(alpha = 0.3f),
            )
            Text(
                "Mock Camera",
                color = Color.White.copy(alpha = 0.3f),
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}
