package com.musubi.eurio.cohorttest.components

import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.musubi.eurio.features.scan.components.PhotoGuideOverlay
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ui.theme.Danger
import com.musubi.eurio.ui.theme.GoldSoft
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Success
import java.util.concurrent.Executors

/**
 * Square camera viewfinder. Hosts the CameraX preview, the shared
 * [PhotoGuideOverlay] (vignette + ring), the live REC indicator, the
 * detection pill, and 4 thin gold corner brackets. The ring color is
 * driven by [detected]; the activity feeds it from
 * `CoinAnalyzer.onPhotoLiveDetection`.
 */
@Composable
fun DetectionViewfinder(
    detected: Boolean,
    analyzer: CoinAnalyzer,
    modifier: Modifier = Modifier,
    size: androidx.compose.ui.unit.Dp = 300.dp,
) {
    Box(
        modifier = modifier.fillMaxWidth(),
        contentAlignment = Alignment.Center,
    ) {
        ViewfinderInner(
            detected = detected,
            analyzer = analyzer,
            modifier = Modifier
                .size(size)
                .background(Color.Black),
        )
    }
}

@Composable
private fun ViewfinderInner(
    detected: Boolean,
    analyzer: CoinAnalyzer,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier) {
        CohortCameraPreview(
            analyzer = analyzer,
            modifier = Modifier.fillMaxSize(),
        )
        PhotoGuideOverlay(
            circleFound = detected,
            modifier = Modifier.fillMaxSize(),
        )

        // Corner brackets — 2 lines each, hand-drawn via drawBehind.
        Box(modifier = Modifier.fillMaxSize().padding(14.dp)) {
            CornerBrackets()
        }

        // Top-left REC blink + model id.
        Row(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(start = 18.dp, top = 18.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            BlinkingRecDot()
            Text(
                "LIVE · ARCFACE",
                style = MonoBadgeStyle.copy(
                    color = Color.White.copy(alpha = 0.55f),
                    fontSize = 10.sp,
                ),
            )
        }

        // Top-right detection pill.
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(end = 18.dp, top = 18.dp),
        ) {
            AnimatedVisibility(
                visible = detected,
                enter = fadeIn(animationSpec = tween(200)) +
                    slideInHorizontally(animationSpec = tween(220)) { it / 2 },
                exit = fadeOut(animationSpec = tween(160)) +
                    slideOutHorizontally(animationSpec = tween(180)) { it / 2 },
            ) {
                Row(
                    modifier = Modifier
                        .clip(RoundedCornerShape(999.dp))
                        .background(Success.copy(alpha = 0.22f))
                        .border(
                            1.dp,
                            Success.copy(alpha = 0.55f),
                            RoundedCornerShape(999.dp),
                        )
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    PulsingDot(color = Success)
                    Text(
                        "Pièce détectée",
                        color = Color(0xFFECFAF3),
                        fontSize = 12.sp,
                    )
                }
            }
        }
    }
}

@Composable
private fun CornerBrackets() {
    val color = GoldSoft.copy(alpha = 0.35f)
    Box(
        modifier = Modifier
            .fillMaxSize()
            .drawBehind {
                val len = 18.dp.toPx()
                val sw = 1.5.dp.toPx()
                val w = size.width
                val h = size.height
                // Top-left
                drawLine(color, Offset(0f, 0f), Offset(len, 0f), sw, StrokeCap.Square)
                drawLine(color, Offset(0f, 0f), Offset(0f, len), sw, StrokeCap.Square)
                // Top-right
                drawLine(color, Offset(w - len, 0f), Offset(w, 0f), sw, StrokeCap.Square)
                drawLine(color, Offset(w, 0f), Offset(w, len), sw, StrokeCap.Square)
                // Bottom-left
                drawLine(color, Offset(0f, h - len), Offset(0f, h), sw, StrokeCap.Square)
                drawLine(color, Offset(0f, h), Offset(len, h), sw, StrokeCap.Square)
                // Bottom-right
                drawLine(color, Offset(w - len, h), Offset(w, h), sw, StrokeCap.Square)
                drawLine(color, Offset(w, h - len), Offset(w, h), sw, StrokeCap.Square)
            },
    )
}

@Composable
private fun BlinkingRecDot() {
    val transition = rememberInfiniteTransition(label = "rec")
    val a by transition.animateFloat(
        initialValue = 1f,
        targetValue = 0.25f,
        animationSpec = infiniteRepeatable(
            animation = tween(820),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "rec-alpha",
    )
    Box(
        modifier = Modifier
            .size(7.dp)
            .clip(CircleShape)
            .background(Danger.copy(alpha = a)),
    )
}

@Composable
private fun PulsingDot(color: Color) {
    val transition = rememberInfiniteTransition(label = "live-dot")
    val scale by transition.animateFloat(
        initialValue = 0.85f,
        targetValue = 1.15f,
        animationSpec = infiniteRepeatable(
            animation = tween(700),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "scale",
    )
    Box(
        modifier = Modifier.size(10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size((6 * scale).dp)
                .clip(CircleShape)
                .background(color),
        )
    }
}

@Composable
private fun CohortCameraPreview(
    analyzer: CoinAnalyzer,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }

    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            PreviewView(ctx).also { previewView ->
                // SurfaceView (default) is rendered on its own window layer
                // and punches through the Compose composition, leaking the
                // camera feed past the parent Box's bounds. TextureView is
                // a regular View, properly clipped by Compose.
                previewView.implementationMode =
                    PreviewView.ImplementationMode.COMPATIBLE
                val providerFuture = ProcessCameraProvider.getInstance(ctx)
                providerFuture.addListener({
                    val provider = providerFuture.get()
                    val preview = Preview.Builder().build().also {
                        it.surfaceProvider = previewView.surfaceProvider
                    }
                    val analysis = ImageAnalysis.Builder()
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build()
                        .also { it.setAnalyzer(executor) { image -> analyzer.analyze(image) } }
                    try {
                        provider.unbindAll()
                        provider.bindToLifecycle(
                            lifecycleOwner,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            analysis,
                        )
                    } catch (e: Exception) {
                        android.util.Log.e("LiveTests", "Camera bind failed", e)
                    }
                }, ContextCompat.getMainExecutor(ctx))
            }
        },
    )

    DisposableEffect(lifecycleOwner) {
        onDispose {
            executor.shutdown()
            runCatching { ProcessCameraProvider.getInstance(context).get().unbindAll() }
        }
    }
}
