package com.musubi.eurio.features.scan.components

import android.Manifest
import android.content.pm.PackageManager
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CameraAlt
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.musubi.eurio.BuildConfig
import com.musubi.eurio.ParityFlags
import com.musubi.eurio.ui.theme.Ink
import java.util.concurrent.Executors

/**
 * CameraX preview + ImageAnalysis (+ optional ImageCapture) wiring, lifecycle
 * bound to the host composable. Extrait de ScanScreen pour être réutilisé par
 * les écrans /dev/capture, /dev/photo, /dev/bench (refacto 2026-05-28).
 *
 * @param onFrame appelée pour chaque frame analyzed (sur l'executor camera).
 * @param onCameraReady appelée une fois après le bindToLifecycle réussi.
 *        L'ImageCapture peut être null si le 3-usecase combo n'est pas
 *        supporté sur ce device (fallback YUV).
 * @param onCameraReleased appelée quand DisposableEffect.onDispose s'exécute.
 */
@Composable
fun CameraPreview(
    onFrame: (ImageProxy) -> Unit,
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
                            onCameraReady(camera, boundImageCapture)
                        } catch (_: Exception) {
                            // Bind failure surfaces via the host's state machine.
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
            // PAS de `provider.unbindAll()` ici : chaque NavBackStackEntry a
            // son propre LifecycleOwner, et CameraX libère automatiquement
            // les usecases du lifecycle qui passe à DESTROYED. Appeler
            // unbindAll() ici détruirait les usecases déjà bindés par une
            // autre route mountée en parallèle pendant la transition de nav
            // (cas /scan ↔ /dev/capture vu après le refacto 2026-05-28).
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
