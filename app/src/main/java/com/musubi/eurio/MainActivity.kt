package com.musubi.eurio

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.RectF
import android.os.Bundle
import android.os.Environment
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.musubi.eurio.data.CoinDetail
import com.musubi.eurio.data.SupabaseCoinClient
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.CoinDetector
import com.musubi.eurio.ml.CoinMatch
import com.musubi.eurio.ml.CoinRecognizer
import com.musubi.eurio.ml.EmbeddingMatcher
import com.musubi.eurio.ml.ScanResult
import com.musubi.eurio.ui.theme.EurioTheme
import coil.compose.AsyncImage
import kotlinx.coroutines.launch
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {

    private var cameraGranted by mutableStateOf(false)

    // Scan state
    private var scanResult by mutableStateOf<ScanResult?>(null)
    private var coinDetail by mutableStateOf<CoinDetail?>(null)
    private var mlStatus by mutableStateOf("Loading model...")
    private var lastFetchedClass: String? = null

    // ML components (initialized once)
    private var coinRecognizer: CoinRecognizer? = null
    private var coinDetector: CoinDetector? = null
    private var embeddingMatcher: EmbeddingMatcher? = null
    private var coinAnalyzer: CoinAnalyzer? = null

    // Debug toggles
    private var useYolo by mutableStateOf(true)
    private var useArcFace by mutableStateOf(true)
    private var hasDetector by mutableStateOf(false)

    // Debug capture count
    private var captureCount by mutableStateOf(0)

    private val analysisExecutor = Executors.newSingleThreadExecutor()

    private val cameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        cameraGranted = granted
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        initMl()
        refreshCaptureCount()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED
        ) {
            cameraGranted = true
        } else {
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }

        setContent {
            EurioTheme {
                Box(modifier = Modifier.fillMaxSize()) {
                    if (cameraGranted && coinRecognizer != null) {
                        ScanCameraPreview()
                    } else if (!cameraGranted) {
                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                            Text("Camera permission required")
                        }
                    }

                    // YOLO bounding box overlay
                    scanResult?.let { result ->
                        if (result.detected && result.detectionBbox != null && result.frameWidth > 0) {
                            YoloBboxOverlay(
                                bbox = result.detectionBbox,
                                frameWidth = result.frameWidth,
                                frameHeight = result.frameHeight,
                                confidence = result.detectionConfidence,
                            )
                        }
                    }

                    // Result overlay
                    ScanOverlay(
                        scanResult = scanResult,
                        coinDetail = coinDetail,
                        mlStatus = mlStatus,
                        useYolo = useYolo,
                        useArcFace = useArcFace,
                        hasDetector = hasDetector,
                        captureCount = captureCount,
                        onToggleYolo = {
                            useYolo = it
                            coinAnalyzer?.useDetector = it
                        },
                        onToggleArcFace = {
                            useArcFace = it
                            coinAnalyzer?.useEmbeddings = it
                        },
                        onCapture = ::captureDebugLog,
                        onClearCaptures = ::clearCaptures,
                    )
                }
            }
        }
    }

    private fun initMl() {
        try {
            val start = System.currentTimeMillis()
            coinRecognizer = CoinRecognizer(this)

            // Load embedding matcher if in arcface/embed mode
            val r = coinRecognizer!!
            if (r.meta.mode == "arcface" || r.meta.mode == "embed") {
                embeddingMatcher = EmbeddingMatcher(this)
            }

            // Load detector if available (optional — falls back to full-frame)
            try {
                coinDetector = CoinDetector(this)
                hasDetector = true
                Log.d("Eurio", "Coin detector loaded")
            } catch (e: Exception) {
                hasDetector = false
                Log.d("Eurio", "No detector model, using full-frame analysis")
            }

            val elapsed = System.currentTimeMillis() - start
            val detectorStr = if (coinDetector != null) " + detector" else ""
            val matcherStr = if (embeddingMatcher != null) " + matcher (${embeddingMatcher!!.coinCount} coins)" else ""
            mlStatus = "ML ready — ${r.meta.mode}$matcherStr$detectorStr, ${elapsed}ms load"
            Log.d("Eurio", mlStatus)
        } catch (e: Exception) {
            mlStatus = "ML error: ${e.message}"
            Log.e("Eurio", "ML init failed", e)
        }
    }

    private fun onScanResult(result: ScanResult) {
        scanResult = result

        val topMatch = result.matches.firstOrNull() ?: return
        // Only fetch from Supabase if the top match changed
        if (topMatch.className != lastFetchedClass) {
            lastFetchedClass = topMatch.className
            fetchCoinDetail(topMatch.className)
        }
    }

    private fun fetchCoinDetail(className: String) {
        lifecycleScope.launch {
            val coins = SupabaseCoinClient.getAllCoins()
            // Match by checking if the coin name contains keywords from the class name
            // For now, we use a simple heuristic — the catalog class names map to Numista entries
            coinDetail = coins.firstOrNull { coin ->
                classMatchesCoin(className, coin)
            }
        }
    }

    /**
     * Match class name (Numista ID) to Supabase coin entry.
     */
    private fun classMatchesCoin(className: String, coin: CoinDetail): Boolean {
        // Class names are Numista IDs (e.g. "135", "226447")
        val numistaId = className.toIntOrNull()
        if (numistaId != null && coin.numista_id == numistaId) return true
        // Legacy fallback: slug-based matching
        val parts = className.lowercase().split("_")
        val country = coin.country.lowercase()
        return parts.any { it.length > 2 && country.contains(it) }
    }

    @Composable
    fun ScanCameraPreview() {
        val recognizer = coinRecognizer ?: return

        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                PreviewView(ctx).apply {
                    val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)
                    cameraProviderFuture.addListener({
                        val cameraProvider = cameraProviderFuture.get()

                        val preview = Preview.Builder().build().also {
                            it.surfaceProvider = surfaceProvider
                        }

                        val imageAnalysis = ImageAnalysis.Builder()
                            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                            .build()
                            .also {
                                it.setAnalyzer(
                                    analysisExecutor,
                                    CoinAnalyzer(
                                        recognizer = recognizer,
                                        matcher = embeddingMatcher,
                                        detector = coinDetector,
                                        onResult = ::onScanResult,
                                        analyzeIntervalMs = 300L,
                                    ).also { coinAnalyzer = it }
                                )
                            }

                        try {
                            cameraProvider.unbindAll()
                            cameraProvider.bindToLifecycle(
                                this@MainActivity,
                                CameraSelector.DEFAULT_BACK_CAMERA,
                                preview,
                                imageAnalysis,
                            )
                        } catch (e: Exception) {
                            Log.e("Eurio", "Camera bind failed", e)
                        }
                    }, ContextCompat.getMainExecutor(ctx))
                }
            }
        )
    }

    private fun getDebugDir() =
        getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS)?.resolve("eurio_debug")

    private fun refreshCaptureCount() {
        val dir = getDebugDir() ?: return
        captureCount = if (dir.exists()) {
            dir.listFiles { f -> f.name.startsWith("capture_") && f.extension == "txt" }?.size ?: 0
        } else 0
    }

    private fun clearCaptures() {
        val dir = getDebugDir() ?: return
        if (dir.exists()) {
            dir.listFiles()?.forEach { it.delete() }
        }
        captureCount = 0
        Toast.makeText(this, "Captures cleared", Toast.LENGTH_SHORT).show()
    }

    private fun captureDebugLog() {
        val result = scanResult ?: return
        val timestamp = java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.US).format(java.util.Date())
        val dir = getDebugDir()
        dir?.mkdirs()

        // Tell the analyzer to save the next camera frame + crop (with synced timestamp)
        coinAnalyzer?.captureDir = dir
        coinAnalyzer?.captureTimestamp = timestamp
        coinAnalyzer?.captureNextFrame = true

        // Build filenames that will be created
        val frameFile = "frame_$timestamp.jpg"
        val cropFile = if (useYolo && result.detected) "crop_$timestamp.jpg" else null

        val logFile = dir?.resolve("capture_$timestamp.txt")
        val log = buildString {
            appendLine("=== Eurio Debug Capture ===")
            appendLine("Time: $timestamp")
            appendLine("Files: $frameFile${cropFile?.let { ", $it" } ?: ""}")
            appendLine("ML Status: $mlStatus")
            appendLine()
            appendLine("--- Toggles ---")
            appendLine("YOLO: ${if (useYolo) "ON" else "OFF"}")
            appendLine("ArcFace: ${if (useArcFace) "ON" else "OFF"}")
            appendLine()
            appendLine("--- Detection ---")
            appendLine("Detected: ${result.detected}")
            appendLine("Det Confidence: ${String.format("%.3f", result.detectionConfidence)}")
            appendLine("Det BBox: ${result.detectionBbox?.let { "[${it.left.toInt()},${it.top.toInt()},${it.right.toInt()},${it.bottom.toInt()}]" } ?: "null"}")
            appendLine("Frame: ${result.frameWidth}x${result.frameHeight}")
            appendLine("Crop: ${result.cropSize}")
            appendLine()
            appendLine("--- Identification ---")
            appendLine("Inference: ${result.inferenceTimeMs}ms")
            result.matches.forEachIndexed { i, m ->
                appendLine("  #${i+1} ${m.className} → ${String.format("%.3f", m.similarity)} (${(m.similarity*100).toInt()}%)")
            }
            appendLine()
            appendLine("--- Coin Detail ---")
            coinDetail?.let { d ->
                appendLine("Name: ${d.name}")
                appendLine("Country: ${d.country}")
                appendLine("Year: ${d.year}")
                appendLine("Value: ${d.face_value}€")
                appendLine("Type: ${d.type}")
                appendLine("Image: ${d.image_obverse_url}")
            } ?: appendLine("No detail fetched")
        }

        logFile?.writeText(log)
        captureCount++
        Log.d("Eurio", "Debug captured to: ${logFile?.absolutePath}")
        Toast.makeText(this, "Capture #$captureCount saved", Toast.LENGTH_SHORT).show()
    }

    override fun onDestroy() {
        super.onDestroy()
        coinRecognizer?.close()
        coinDetector?.close()
        analysisExecutor.shutdown()
    }
}

// ---------------------------------------------------------------------------
// UI Overlay
// ---------------------------------------------------------------------------

@Composable
fun YoloBboxOverlay(
    bbox: RectF,
    frameWidth: Int,
    frameHeight: Int,
    confidence: Float,
) {
    Canvas(modifier = Modifier.fillMaxSize()) {
        // Scale bbox from frame coordinates to canvas coordinates
        // Camera preview fills the screen, so we scale proportionally
        val scaleX = size.width / frameWidth
        val scaleY = size.height / frameHeight

        val left = bbox.left * scaleX
        val top = bbox.top * scaleY
        val right = bbox.right * scaleX
        val bottom = bbox.bottom * scaleY

        val color = when {
            confidence > 0.7f -> Color(0xFF4CAF50)  // green
            confidence > 0.5f -> Color(0xFFFF9800)  // orange
            else -> Color(0xFFF44336)                // red
        }

        // Draw bounding box
        drawRect(
            color = color,
            topLeft = Offset(left, top),
            size = Size(right - left, bottom - top),
            style = Stroke(width = 3f),
        )
    }
}

@Composable
fun ScanOverlay(
    scanResult: ScanResult?,
    coinDetail: CoinDetail?,
    mlStatus: String,
    useYolo: Boolean,
    useArcFace: Boolean,
    hasDetector: Boolean,
    captureCount: Int = 0,
    onToggleYolo: (Boolean) -> Unit,
    onToggleArcFace: (Boolean) -> Unit,
    onCapture: () -> Unit = {},
    onClearCaptures: () -> Unit = {},
) {
    Box(modifier = Modifier.fillMaxSize()) {
        // Top: identified coin info
        AnimatedVisibility(
            visible = scanResult != null && scanResult.matches.isNotEmpty(),
            enter = fadeIn(),
            exit = fadeOut(),
            modifier = Modifier.align(Alignment.TopCenter),
        ) {
            scanResult?.let { result ->
                val topMatch = result.matches.firstOrNull()
                if (topMatch != null) {
                    CoinResultCard(
                        match = topMatch,
                        detail = coinDetail,
                        modifier = Modifier
                            .padding(top = 60.dp, start = 16.dp, end = 16.dp),
                    )
                }
            }
        }

        // Bottom: debug info + toggles
        DebugPanel(
            scanResult = scanResult,
            mlStatus = mlStatus,
            useYolo = useYolo,
            useArcFace = useArcFace,
            hasDetector = hasDetector,
            captureCount = captureCount,
            onToggleYolo = onToggleYolo,
            onToggleArcFace = onToggleArcFace,
            onCapture = onCapture,
            onClearCaptures = onClearCaptures,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 32.dp, start = 16.dp, end = 16.dp),
        )
    }
}

@Composable
fun CoinResultCard(
    match: CoinMatch,
    detail: CoinDetail?,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(Color.Black.copy(alpha = 0.75f))
            .padding(12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // Coin image from Numista
        val imageUrl = detail?.image_obverse_url
        if (imageUrl != null) {
            AsyncImage(
                model = imageUrl,
                contentDescription = detail.name,
                modifier = Modifier
                    .height(80.dp)
                    .width(80.dp)
                    .clip(RoundedCornerShape(12.dp)),
            )
        }

        Column(modifier = Modifier.weight(1f)) {
            // Coin name
            Text(
                text = detail?.name ?: "Coin #${match.className}",
                color = Color.White,
                fontSize = 18.sp,
                fontWeight = FontWeight.Bold,
                maxLines = 2,
            )

            if (detail != null) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = buildString {
                        append(detail.country)
                        detail.year?.let { append(" · $it") }
                        detail.face_value?.let { append(" · ${it}€") }
                    },
                    color = Color.White.copy(alpha = 0.8f),
                    fontSize = 14.sp,
                )
                detail.type?.let { type ->
                    Text(
                        text = type.replaceFirstChar { it.uppercase() },
                        color = Color.White.copy(alpha = 0.6f),
                        fontSize = 12.sp,
                    )
                }
            }

            Spacer(modifier = Modifier.height(6.dp))

            // Confidence
            val confidenceColor = when {
                match.similarity > 0.85f -> Color(0xFF4CAF50)
                match.similarity > 0.70f -> Color(0xFFFF9800)
                else -> Color(0xFFF44336)
            }
            Text(
                text = "Confidence: ${(match.similarity * 100).toInt()}%",
                color = confidenceColor,
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

@Composable
fun DebugPanel(
    scanResult: ScanResult?,
    mlStatus: String,
    useYolo: Boolean,
    useArcFace: Boolean,
    hasDetector: Boolean,
    captureCount: Int = 0,
    onToggleYolo: (Boolean) -> Unit,
    onToggleArcFace: (Boolean) -> Unit,
    onCapture: () -> Unit,
    onClearCaptures: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(Color.Black.copy(alpha = 0.6f))
            .padding(12.dp),
    ) {
        // Toggles + capture row
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                ToggleChip(
                    label = "YOLO",
                    checked = useYolo,
                    enabled = hasDetector,
                    onToggle = onToggleYolo,
                )
                ToggleChip(
                    label = "ArcFace",
                    checked = useArcFace,
                    onToggle = onToggleArcFace,
                )
            }
            // Capture button + count/clear
            Row(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "CAPTURE",
                    color = Color(0xFFFF5722),
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .background(Color(0xFFFF5722).copy(alpha = 0.2f))
                        .clickable { onCapture() }
                        .padding(horizontal = 12.dp, vertical = 6.dp),
                )
                if (captureCount > 0) {
                    Text(
                        text = "$captureCount \u00D7",
                        color = Color.White.copy(alpha = 0.7f),
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier
                            .clip(RoundedCornerShape(8.dp))
                            .background(Color.White.copy(alpha = 0.15f))
                            .clickable { onClearCaptures() }
                            .padding(horizontal = 8.dp, vertical = 6.dp),
                    )
                }
            }
        }

        Spacer(modifier = Modifier.height(6.dp))

        Text(
            text = mlStatus,
            color = Color.White.copy(alpha = 0.4f),
            fontSize = 8.sp,
        )

        if (scanResult != null) {
            Spacer(modifier = Modifier.height(4.dp))

            // YOLO detection info
            val yoloInfo = if (scanResult.detected && scanResult.detectionBbox != null) {
                val b = scanResult.detectionBbox
                "YOLO: ${String.format("%.0f%%", scanResult.detectionConfidence * 100)} bbox=[${b.left.toInt()},${b.top.toInt()},${b.right.toInt()},${b.bottom.toInt()}] crop=${scanResult.cropSize}"
            } else if (useYolo) {
                "YOLO: no detection"
            } else {
                "YOLO: OFF"
            }
            Text(
                text = "${scanResult.inferenceTimeMs}ms | $yoloInfo",
                color = Color.White.copy(alpha = 0.5f),
                fontSize = 8.sp,
            )

            // Matches
            Spacer(modifier = Modifier.height(2.dp))
            scanResult.matches.forEach { m ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        text = m.className,
                        color = Color.White.copy(alpha = 0.4f),
                        fontSize = 9.sp,
                        modifier = Modifier.weight(1f),
                    )
                    Text(
                        text = String.format("%.1f%%", m.similarity * 100),
                        color = Color.White.copy(alpha = 0.4f),
                        fontSize = 9.sp,
                    )
                }
            }
        }
    }
}

@Composable
fun ToggleChip(
    label: String,
    checked: Boolean,
    enabled: Boolean = true,
    onToggle: (Boolean) -> Unit,
) {
    val bgColor = when {
        !enabled -> Color.White.copy(alpha = 0.1f)
        checked -> Color(0xFF4CAF50).copy(alpha = 0.3f)
        else -> Color.White.copy(alpha = 0.15f)
    }
    val textColor = when {
        !enabled -> Color.White.copy(alpha = 0.3f)
        checked -> Color(0xFF4CAF50)
        else -> Color.White.copy(alpha = 0.6f)
    }

    Text(
        text = if (checked) "$label ON" else "$label OFF",
        color = textColor,
        fontSize = 11.sp,
        fontWeight = FontWeight.Medium,
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(bgColor)
            .then(
                if (enabled) {
                    Modifier.clickable { onToggle(!checked) }
                } else Modifier
            )
            .padding(horizontal = 12.dp, vertical = 6.dp),
    )
}
