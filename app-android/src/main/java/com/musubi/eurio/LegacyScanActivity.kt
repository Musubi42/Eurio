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
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
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
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import org.opencv.android.OpenCVLoader
import com.musubi.eurio.data.CoinDetail
import com.musubi.eurio.data.SupabaseCoinClient
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.CoinDetector
import com.musubi.eurio.ml.CoinMatch
import com.musubi.eurio.ml.CoinRecognizer
import com.musubi.eurio.ml.Detection
import com.musubi.eurio.ml.DetectionSource
import com.musubi.eurio.ml.EmbeddingMatcher
import com.musubi.eurio.ml.ScanResult
import com.musubi.eurio.ui.theme.EurioTheme
import coil.compose.AsyncImage
import kotlinx.coroutines.launch
import java.util.concurrent.Executors

class LegacyScanActivity : ComponentActivity() {

    companion object {
        // Consensus window for stable identification display (see plan, fix ④).
        private const val CONSENSUS_WINDOW = 5
        private const val CONSENSUS_THRESHOLD = 3
    }

    private var cameraGranted by mutableStateOf(false)

    // Scan state
    private var scanResult by mutableStateOf<ScanResult?>(null)
    private var coinDetail by mutableStateOf<CoinDetail?>(null)
    private var mlStatus by mutableStateOf("Loading model...")
    private var lastFetchedClass: String? = null

    // Frame consensus for stable identification (fix ④)
    private val recentMatches = ArrayDeque<String?>()  // null = miss/reject
    private var consensusClass by mutableStateOf<String?>(null)  // sticky
    private var consensusSimilarity by mutableStateOf(0f)

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

        // Initialize OpenCV native libs before any ML component uses them (Hough fallback).
        if (!OpenCVLoader.initLocal()) {
            Log.e("Eurio", "OpenCV init failed — Hough fallback unavailable")
        } else {
            Log.d("Eurio", "OpenCV initialized")
        }

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

                    // Detection bounding box overlay (YOLO or Hough, all candidates + selected)
                    scanResult?.let { result ->
                        if (result.detected && result.frameWidth > 0) {
                            YoloBboxOverlay(
                                detections = result.detections,
                                selectedIndex = result.selectedDetectionIndex,
                                frameWidth = result.frameWidth,
                                frameHeight = result.frameHeight,
                            )
                        }
                    }

                    // Result overlay
                    ScanOverlay(
                        scanResult = scanResult,
                        consensusClass = consensusClass,
                        consensusSimilarity = consensusSimilarity,
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

        // Update sliding window (null = frame with no accepted detection)
        val topClass = result.matches.firstOrNull()?.className
        recentMatches.addLast(topClass)
        while (recentMatches.size > CONSENSUS_WINDOW) recentMatches.removeFirst()

        // Compute consensus: class that appears ≥ CONSENSUS_THRESHOLD times in the window.
        val counts = recentMatches.filterNotNull().groupingBy { it }.eachCount()
        val newConsensus = counts.entries
            .filter { it.value >= CONSENSUS_THRESHOLD }
            .maxByOrNull { it.value }
            ?.key

        // Sticky: only switch when a NEW consensus is reached; never clear to null.
        if (newConsensus != null && newConsensus != consensusClass) {
            consensusClass = newConsensus
            if (newConsensus != lastFetchedClass) {
                lastFetchedClass = newConsensus
                fetchCoinDetail(newConsensus)
            }
        }

        // Keep consensusSimilarity fresh for the displayed class
        if (topClass != null && topClass == consensusClass) {
            consensusSimilarity = result.matches.first().similarity
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

                        // Target 720×1280 analysis resolution. The default CameraX picks
                        // something like 480×640 which leaves coins at ~70px after letterbox —
                        // too small for reliable YOLO detection.
                        val resolutionSelector = ResolutionSelector.Builder()
                            .setResolutionStrategy(
                                ResolutionStrategy(
                                    android.util.Size(720, 1280),
                                    ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER,
                                )
                            )
                            .build()

                        val imageAnalysis = ImageAnalysis.Builder()
                            .setResolutionSelector(resolutionSelector)
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
                                this@LegacyScanActivity,
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
        val humanTime = java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss", java.util.Locale.US).format(java.util.Date())
        val dir = getDebugDir()
        dir?.mkdirs()

        // Tell the analyzer to save the next camera frame + crop (with synced timestamp)
        coinAnalyzer?.captureDir = dir
        coinAnalyzer?.captureTimestamp = timestamp
        coinAnalyzer?.captureNextFrame = true

        val detectorModel = coinDetector?.modelPath ?: "—"
        val identifierModel = coinRecognizer?.modelPath ?: "—"
        val identifierMode = coinRecognizer?.meta?.mode ?: "—"
        val matcherCoins = embeddingMatcher?.coinCount

        val logFile = dir?.resolve("capture_$timestamp.txt")
        val log = buildString {
            appendLine("=== Eurio Debug Capture ===")
            appendLine("Date: $humanTime")
            appendLine("Capture ID: $timestamp")
            appendLine()
            appendLine("--- Fichiers ---")
            appendLine("Frame brute     : frame_$timestamp.jpg")
            appendLine("Frame annotée   : frame_annotated_$timestamp.jpg")
            if (result.detected) {
                appendLine("Crop (pièce)    : crop_$timestamp.jpg")
            }
            appendLine()
            appendLine("--- Configuration ML ---")
            appendLine("YOLO (détection de forme pièce)             : ${if (useYolo && hasDetector) "ON" else "OFF"} — $detectorModel")
            val idState = if (useArcFace) "ON" else "OFF"
            val matcherSuffix = matcherCoins?.let { ", $it pièces" } ?: ""
            appendLine("$identifierMode (identification avers pièce) : $idState — $identifierModel$matcherSuffix")
            appendLine("ML status       : $mlStatus")
            appendLine("Seuil détection : 0.40 (conf) / IoU 0.45 (NMS)")
            appendLine()
            appendLine("--- Image source ---")
            appendLine("Frame           : ${result.frameWidth}x${result.frameHeight}")
            appendLine("Camera target   : 720x1280 (ResolutionSelector)")
            appendLine("Letterbox       : scale=${"%.3f".format(result.letterboxScale)} padX=${result.letterboxPadX} padY=${result.letterboxPadY}")
            appendLine()
            appendLine("--- YOLO — détection de forme pièce ---")
            appendLine("Temps inférence (interpreter) : ${result.yoloInferenceMs}ms")
            appendLine("Temps total (preprocess+NMS)  : ${result.yoloTotalMs}ms")
            appendLine("Candidats bruts (>0.40)       : ${result.rawYoloCount}")
            appendLine("Conservés après NMS           : ${result.yoloKeptCount}")
            if (result.rawYoloCount == 0) {
                appendLine("→ YOLO n'a trouvé aucun candidat")
            }
            appendLine()
            appendLine("--- Hough Circle Transform (OpenCV, parallèle à YOLO) ---")
            if (!result.houghRan) {
                appendLine("Statut : non exécuté (désactivé ou OpenCV init ratée)")
            } else {
                appendLine("Statut                         : EXÉCUTÉ (toujours en parallèle de YOLO)")
                appendLine("Paramètres                     : radius 8-30% short side, minDist=25%, maxR ceiling=30%")
                appendLine("Temps OpenCV HoughCircles      : ${result.houghInferenceMs}ms")
                appendLine("Cercles conservés              : ${result.houghKeptCount}")
            }
            appendLine()
            appendLine("--- Merge YOLO ∪ Hough ---")
            appendLine("YOLO kept      : ${result.yoloKeptCount}")
            appendLine("Hough kept     : ${result.houghKeptCount}")
            appendLine("Dedup (Hough écartés car IoU>0.6 avec YOLO) : ${result.mergeDedupCount}")
            appendLine("Candidats finaux après cap (5) : ${result.detections.size}")
            appendLine()
            appendLine("--- Rerank ArcFace (spread-based decision) ---")
            appendLine("Temps total rerank : ${result.rerankMs}ms")
            appendLine("Règle             : top1 > ${CoinAnalyzer.RERANK_TOP1_MIN} ET (top1 > ${CoinAnalyzer.RERANK_CONFIDENT_ALONE} OU spread > ${CoinAnalyzer.RERANK_SPREAD_MIN})")
            if (result.detections.isEmpty()) {
                appendLine("→ Aucun candidat à rerank (YOLO et Hough vides)")
            } else {
                appendLine("Similarities par candidat :")
                result.detections.forEachIndexed { i, det ->
                    val top1 = result.rerankSimilaritiesTop1.getOrNull(i) ?: 0f
                    val top2 = result.rerankSimilaritiesTop2.getOrNull(i) ?: 0f
                    val spread = top1 - top2
                    val marker = if (i == result.selectedDetectionIndex) " ← SÉLECTIONNÉ" else ""
                    val b = det.bbox
                    val size = "${(b.right - b.left).toInt()}x${(b.bottom - b.top).toInt()}"
                    appendLine(
                        "  #${i + 1} [${det.source}] geom=${"%.2f".format(det.confidence)} " +
                            "top1=${"%.3f".format(top1)} top2=${"%.3f".format(top2)} spread=${"%.3f".format(spread)} " +
                            "size=${size}$marker"
                    )
                }
                appendLine("Décision : ${result.rerankDecisionReason}")
            }
            appendLine()
            appendLine("--- $identifierMode — identification d'avers de pièce ---")
            appendLine("Modèle          : $identifierModel")
            appendLine("Mode            : $identifierMode")
            appendLine("Temps inférence : ${result.identificationInferenceMs}ms (= rerank total, winner réutilise)")
            appendLine("Pipeline total  : ${result.totalInferenceMs}ms")
            val padPct = when (result.bestDetection?.source) {
                DetectionSource.HOUGH -> 25
                DetectionSource.YOLO -> 10
                null -> 0
            }
            appendLine("Crop utilisé    : ${if (result.cropSize.isNotEmpty()) "${result.cropSize} (padding ${padPct}%)" else "— (pas de détection retenue)"}")
            if (result.matches.isEmpty()) {
                appendLine("→ Aucun match (rerank rejeté ou pas de détection)")
            } else {
                appendLine("Top matches du winner :")
                result.matches.forEachIndexed { i, m ->
                    appendLine("  #${i + 1} Numista ${m.className} → similarity=${"%.3f".format(m.similarity)} (${(m.similarity * 100).toInt()}%)")
                }
            }
            appendLine()
            appendLine("--- Frame consensus (fenêtre=$CONSENSUS_WINDOW, seuil=$CONSENSUS_THRESHOLD) ---")
            val bufferStr = recentMatches.joinToString(", ") { it ?: "miss" }
            appendLine("Buffer récent   : [$bufferStr]")
            val consensusCounts = recentMatches.filterNotNull().groupingBy { it }.eachCount()
            if (consensusCounts.isEmpty()) {
                appendLine("Consensus       : aucun (buffer vide ou que des miss)")
            } else {
                val sortedCounts = consensusCounts.entries.sortedByDescending { it.value }
                appendLine("Comptes         : ${sortedCounts.joinToString(", ") { "${it.key}=${it.value}/$CONSENSUS_WINDOW" }}")
                appendLine("Consensus actif : ${consensusClass ?: "aucun (seuil pas atteint)"}")
                appendLine("Sim affichée    : ${"%.3f".format(consensusSimilarity)}")
            }
            appendLine()
            appendLine("--- Détail pièce (Supabase) ---")
            coinDetail?.let { d ->
                appendLine("Nom             : ${d.name}")
                appendLine("Pays            : ${d.country}")
                appendLine("Année           : ${d.year ?: "—"}")
                appendLine("Valeur faciale  : ${d.face_value?.let { "${it}€" } ?: "—"}")
                appendLine("Type            : ${d.type ?: "—"}")
                appendLine("Image avers     : ${d.image_obverse_url ?: "—"}")
            } ?: appendLine("→ Aucun détail récupéré (pas de match Supabase)")
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
    detections: List<Detection>,
    selectedIndex: Int,
    frameWidth: Int,
    frameHeight: Int,
) {
    if (detections.isEmpty() || frameWidth == 0) return
    Canvas(modifier = Modifier.fillMaxSize()) {
        val scaleX = size.width / frameWidth
        val scaleY = size.height / frameHeight

        detections.forEachIndexed { index, det ->
            val bbox = det.bbox
            val left = bbox.left * scaleX
            val top = bbox.top * scaleY
            val right = bbox.right * scaleX
            val bottom = bbox.bottom * scaleY

            val color = when {
                det.confidence > 0.7f -> Color(0xFF4CAF50)
                det.confidence > 0.5f -> Color(0xFFFF9800)
                else -> Color(0xFFF44336)
            }
            // Selected detection = thicker stroke
            val strokeW = if (index == selectedIndex) 8f else 4f

            drawRect(
                color = color,
                topLeft = Offset(left, top),
                size = Size(right - left, bottom - top),
                style = Stroke(width = strokeW),
            )

            val label = "${det.source} ${(det.confidence * 100).toInt()}%"
            val textPaint = android.graphics.Paint().apply {
                this.color = android.graphics.Color.WHITE
                textSize = 38f
                isAntiAlias = true
                typeface = android.graphics.Typeface.DEFAULT_BOLD
            }
            val bgPaint = android.graphics.Paint().apply {
                this.color = color.toArgb()
                style = android.graphics.Paint.Style.FILL
                isAntiAlias = true
            }
            val textWidth = textPaint.measureText(label)
            val pad = 8f
            val labelBottom = (top - pad).coerceAtLeast(38f + pad * 2)
            val labelTop = labelBottom - 38f - pad * 2
            drawContext.canvas.nativeCanvas.apply {
                drawRect(left, labelTop, left + textWidth + pad * 2, labelBottom, bgPaint)
                drawText(label, left + pad, labelBottom - pad, textPaint)
            }
        }
    }
}

@Composable
fun ScanOverlay(
    scanResult: ScanResult?,
    consensusClass: String?,
    consensusSimilarity: Float,
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
        // Top: identified coin info — driven by the consensus (sticky across misses)
        AnimatedVisibility(
            visible = consensusClass != null,
            enter = fadeIn(),
            exit = fadeOut(),
            modifier = Modifier.align(Alignment.TopCenter),
        ) {
            consensusClass?.let { className ->
                CoinResultCard(
                    match = CoinMatch(className, consensusSimilarity),
                    detail = coinDetail,
                    modifier = Modifier
                        .padding(top = 60.dp, start = 16.dp, end = 16.dp),
                )
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

            // Detection info (unified YOLO+Hough + rerank)
            val yoloInfo = if (scanResult.detected) {
                val best = scanResult.bestDetection!!
                val b = best.bbox
                "${best.source}: ${(best.confidence * 100).toInt()}% bbox=[${b.left.toInt()},${b.top.toInt()},${b.right.toInt()},${b.bottom.toInt()}]"
            } else if (useYolo) {
                val yK = scanResult.yoloKeptCount
                val hK = scanResult.houghKeptCount
                val rej = if (scanResult.rerankRejectedAll) " (rerank rejected)" else ""
                "DET: miss (yolo=$yK hough=$hK)$rej"
            } else {
                "DET: OFF"
            }
            val detTimingStr = if (scanResult.houghRan) {
                "yolo=${scanResult.yoloInferenceMs}ms hough=${scanResult.houghInferenceMs}ms"
            } else {
                "yolo=${scanResult.yoloInferenceMs}ms"
            }
            Text(
                text = "$detTimingStr rerank=${scanResult.rerankMs}ms total=${scanResult.totalInferenceMs}ms | $yoloInfo",
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
