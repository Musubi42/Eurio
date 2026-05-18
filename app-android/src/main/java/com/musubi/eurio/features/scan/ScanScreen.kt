package com.musubi.eurio.features.scan

import android.Manifest
import android.content.pm.PackageManager
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
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
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.musubi.eurio.features.scan.components.Coin3DTuneFab
import com.musubi.eurio.features.scan.components.Coin3DTuning
import com.musubi.eurio.features.scan.components.Coin3DTuningPanel
import com.musubi.eurio.features.scan.components.Coin3DViewer
import kotlinx.coroutines.delay
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
import com.musubi.eurio.features.scan.components.ScanCarouselNav
import com.musubi.eurio.features.scan.components.ScanDebugModeToggle
import com.musubi.eurio.features.scan.components.ScanDebugOverlay
import com.musubi.eurio.features.scan.components.CaptureGuideOverlay
import com.musubi.eurio.features.scan.components.CaptureSnapResultLayer
import com.musubi.eurio.features.scan.components.PhotoGuideOverlay
import com.musubi.eurio.features.scan.components.PhotoSnapResultLayer
import com.musubi.eurio.features.scan.components.ScanDetectingLayer
import com.musubi.eurio.features.scan.components.ScanFailureLayer
import com.musubi.eurio.features.scan.components.ScanIdleLayer
import com.musubi.eurio.features.scan.debug.BenchProtocolActions
import com.musubi.eurio.features.scan.debug.BenchProtocolHeader
import com.musubi.eurio.features.scan.debug.DebugBarLauncher
import com.musubi.eurio.features.scan.debug.ScanHud
import com.musubi.eurio.features.scan.debug.ScanLockOverlay
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
    val carouselMode by viewModel.carouselMode.collectAsStateWithLifecycle()
    val carouselCoin by viewModel.carouselCurrent.collectAsStateWithLifecycle()
    val streakCount by viewModel.streakCount.collectAsStateWithLifecycle()
    val debugData by viewModel.debugData.collectAsStateWithLifecycle()
    val recordMode by viewModel.recordMode.collectAsStateWithLifecycle()
    val recordedFrameCount by viewModel.recordedFrameCount.collectAsStateWithLifecycle()
    val photoMode by viewModel.photoMode.collectAsStateWithLifecycle()
    val photoSnap by viewModel.photoSnap.collectAsStateWithLifecycle()
    val photoLiveCircleFound by viewModel.photoLiveCircleFound.collectAsStateWithLifecycle()
    val captureMode by viewModel.captureMode.collectAsStateWithLifecycle()
    val captureProgress by viewModel.captureProgress.collectAsStateWithLifecycle()
    val benchProtocol by viewModel.benchProtocolState.collectAsStateWithLifecycle()

    val snackbarHostState = remember { SnackbarHostState() }

    // Live PBR/exposure tuning, only meaningful in carousel debug mode. The
    // panel is collapsed by default; opening it doesn't reset the values so
    // the user can compare current vs default by toggling the FAB.
    var tuning by remember { mutableStateOf(Coin3DTuning.Default) }
    var tunePanelOpen by remember { mutableStateOf(false) }

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
            val showSnapResult = photoMode && photoSnap != null

            // In carousel mode the live camera + ML pipeline is bypassed —
            // unmounting CameraPreview both stops onFrame() and releases the
            // camera so battery/heat don't burn while debugging.
            //
            // Photo-mode snap result, in contrast, keeps the camera mounted
            // underneath the result overlay (PhotoSnapResultLayer paints an
            // opaque Ink background that covers the preview). This way AF
            // and AE keep converging while the user inspects the result —
            // tapping "reset" returns to a warm preview instead of a cold
            // restart, which previously produced blurry/dim re-snaps.
            if (!carouselMode) {
                CameraPreview(
                    onFrame = { image -> viewModel.onFrame(image) },
                    onCameraReady = { camera, imageCapture ->
                        viewModel.attachCamera(camera, imageCapture)
                    },
                    onCameraReleased = { viewModel.detachCamera() },
                    modifier = Modifier.fillMaxSize(),
                )
            }

            // State-driven layer (suppressed when a snap result is on screen).
            if (!showSnapResult) when (val s = state) {
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
                        tuning = tuning,
                        modifier = Modifier.fillMaxSize(),
                    )
                    var cardVisible by remember(s.coin.eurioId) { mutableStateOf(false) }
                    LaunchedEffect(s.coin.eurioId) {
                        delay(400)
                        cardVisible = true
                    }
                    // Carousel mode = clean 3D viewer only — the AcceptedCard
                    // would obscure the coin and clash with the bottom carousel
                    // nav, so we suppress it here.
                    if (cardVisible && !carouselMode) {
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

            if (debugMode && carouselMode) {
                ScanCarouselNav(
                    coin = carouselCoin,
                    onPrev = { viewModel.onCarouselPrev() },
                    onNext = { viewModel.onCarouselNext() },
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(bottom = EurioSpacing.s6),
                )

                // Tune FAB sits bottom-right above the carousel nav. When open,
                // the sliders panel floats above the FAB.
                Column(
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .padding(end = EurioSpacing.s3, bottom = 88.dp),
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                ) {
                    if (tunePanelOpen) {
                        Coin3DTuningPanel(
                            tuning = tuning,
                            onChange = { tuning = it },
                            onReset = { tuning = Coin3DTuning.Default },
                        )
                    }
                    Coin3DTuneFab(
                        open = tunePanelOpen,
                        onClick = { tunePanelOpen = !tunePanelOpen },
                    )
                }
            }

            if (debugMode) {
                ScanDebugModeToggle(
                    carouselActive = carouselMode,
                    onClick = { viewModel.toggleCarouselMode() },
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = 80.dp),
                )
            }

            // Already-owned inline hint (small thumbnail near the top bar) —
            // suppressed in carousel mode where the vault state is irrelevant.
            (state as? ScanUiState.Accepted)?.takeIf { it.alreadyOwned && !carouselMode }?.let { s ->
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
                // Chunk-6.3 — graphical overlay reads the shadow state
                // machine so each sub-state renders with a distinct color
                // (Locking pulse / Capturing fill / Identifying secondary
                // / Aborted error). The legacy abortEvents flow still
                // drives the per-frame red flash for trigger aborts.
                if (!carouselMode) {
                    ScanLockOverlay(
                        bbox = debugData.bbox,
                        shadowState = shadowState,
                        abortEvents = viewModel.abortEvents,
                        modifier = Modifier.fillMaxSize(),
                    )
                }
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
                    onStartBenchProtocol = { viewModel.startBenchProtocol() },
                )

                // Chunk-7b — guided bench protocol overlay. Top band shows
                // the current cell (coin × condition); bottom band exposes
                // Start / Done / Skip. Rendered above the debug HUD so
                // controls stay tappable.
                benchProtocol?.let { state ->
                    BenchProtocolHeader(
                        state = state,
                        onQuit = { viewModel.endBenchProtocol() },
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .padding(top = 200.dp),
                    )
                    BenchProtocolActions(
                        state = state,
                        onStart = { viewModel.startCurrentBenchCell() },
                        onDone = { viewModel.markCurrentBenchCellDone() },
                        onSkip = { viewModel.skipCurrentBenchCell() },
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .padding(bottom = 80.dp),
                    )
                }
            }

            if (debugMode && !carouselMode) {
                val snap = photoSnap
                val progress = captureProgress
                if (showSnapResult && snap != null) {
                    if (captureMode && progress != null) {
                        CaptureSnapResultLayer(
                            snap = snap,
                            progress = progress,
                            onRedo = { viewModel.onCaptureRedo() },
                            onNext = { viewModel.onCaptureNext() },
                        )
                    } else {
                        PhotoSnapResultLayer(snap = snap)
                    }
                } else if (photoMode && state !is ScanUiState.Accepted) {
                    PhotoGuideOverlay(circleFound = photoLiveCircleFound)
                }
                if (captureMode && progress != null && !showSnapResult) {
                    CaptureGuideOverlay(progress = progress)
                }
                ScanDebugOverlay(
                    data = debugData,
                    recording = recordMode,
                    recordedFrameCount = recordedFrameCount,
                    photoMode = photoMode,
                    hasSnapResult = showSnapResult,
                    captureMode = captureMode,
                    onRecordToggle = { viewModel.onRecordToggle() },
                    onPhotoToggle = { viewModel.onPhotoToggle() },
                    onSnap = { viewModel.onSnap() },
                    onReset = { viewModel.onSnapAgain() },
                    onCaptureToggle = { viewModel.onCaptureToggle() },
                )
            }
        }
    }
}

@Composable
private fun CameraPreview(
    onFrame: (androidx.camera.core.ImageProxy) -> Unit,
    onCameraReady: (Camera, ImageCapture?) -> Unit = { _, _ -> },
    onCameraReleased: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    if (BuildConfig.IS_QA && ParityFlags.mockCamera) {
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
                        // Chunk-5c — try the full 3-usecase combo (Preview +
                        // ImageAnalysis + ImageCapture). On devices where
                        // that's unsupported, fall back to 2-usecase and
                        // signal the YUV path via imageCapture = null.
                        val imageCapture = ImageCapture.Builder()
                            .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
                            .setJpegQuality(95)
                            .build()
                        try {
                            provider.unbindAll()
                            val camera = try {
                                provider.bindToLifecycle(
                                    lifecycleOwner,
                                    CameraSelector.DEFAULT_BACK_CAMERA,
                                    preview,
                                    analysis,
                                    imageCapture,
                                )
                            } catch (e: IllegalArgumentException) {
                                // 3-usecase combo unsupported → fall back to
                                // 2-usecase (YUV fallback wired in 5d).
                                provider.unbindAll()
                                provider.bindToLifecycle(
                                    lifecycleOwner,
                                    CameraSelector.DEFAULT_BACK_CAMERA,
                                    preview,
                                    analysis,
                                ).also { _ ->
                                    android.util.Log.w(
                                        "Eurio",
                                        "3-usecase bind failed (${e.message}), YUV fallback active",
                                    )
                                }
                            }
                            val boundImageCapture =
                                if (provider.isBound(imageCapture)) imageCapture else null
                            // Hand the Camera instance to the ViewModel so the
                            // best-frame lock controller (chunk-4) can drive
                            // AE/AF/AWB lock via Camera2Interop. Released in
                            // DisposableEffect.onDispose below.
                            onCameraReady(camera, boundImageCapture)
                        } catch (_: Exception) {
                            // Swallow — the outer Scaffold will re-render on
                            // next composition and retry. A persistent bind
                            // failure should surface via ScanUiState.Failure,
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
            onCameraReleased()
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
