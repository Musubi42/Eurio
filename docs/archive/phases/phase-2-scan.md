# Phase 2 — Scan MVP

> Objectif : l'utilisateur ouvre l'app, pointe sa caméra sur une pièce, et le résultat s'affiche en < 3 secondes. Tout tourne on-device.

---

## 2.1 — Pipeline de scan (Kotlin natif)

### Architecture

```
CameraX (flux vidéo continu)
  ↓
ImageAnalysis.Analyzer (callback sur chaque frame)
  ↓
Étape 1 : Preprocessing (Kotlin)
  → Center crop (zone centrale du frame)
  → Resize 224×224
  → Conversion Bitmap → ByteBuffer normalisé (ImageNet mean/std)
  ↓
Étape 2 : Inférence TFLite (SDK natif)
  → Interpreter.run(input, output)
  → Output : embedding 256-dim (FloatArray)
  ↓
Étape 3 : Matching (Kotlin)
  → Cosine similarity vs base locale d'embeddings
  → Tri par score décroissant
  ↓
Étape 4 : Résultat → UI via StateFlow
  → Confiance > 0.90 : match direct
  → 0.75-0.90 : top 3 suggestions
  → < 0.75 : "Non identifié"
```

### Code Kotlin — CameraX + TFLite

```kotlin
// ml/CoinDetector.kt
class CoinDetector(
    private val embedder: CoinEmbedder,
    private val matcher: EmbeddingMatcher
) : ImageAnalysis.Analyzer {

    private val _result = MutableStateFlow<ScanResult>(ScanResult.Scanning)
    val result: StateFlow<ScanResult> = _result

    override fun analyze(imageProxy: ImageProxy) {
        val bitmap = imageProxy.toBitmap()

        // 1. Center crop + resize
        val cropped = cropAndResize(bitmap, 224)

        // 2. Embedding
        val embedding = embedder.extract(cropped)

        // 3. Matching
        val matches = matcher.findMatches(embedding)

        // 4. Résultat
        _result.value = when {
            matches.first().similarity > 0.90f ->
                ScanResult.Identified(matches.first())
            matches.first().similarity > 0.75f ->
                ScanResult.Suggestions(matches.take(3))
            else ->
                ScanResult.NotIdentified
        }

        imageProxy.close()
    }
}

// ml/CoinEmbedder.kt
class CoinEmbedder(context: Context) {
    private val interpreter: Interpreter

    init {
        val model = FileUtil.loadMappedFile(context, "models/eurio_embedder_v1.tflite")
        val options = Interpreter.Options().apply {
            numThreads = 4
            // addDelegate(GpuDelegate())  // Optionnel : GPU acceleration
        }
        interpreter = Interpreter(model, options)
    }

    fun extract(bitmap: Bitmap): FloatArray {
        val input = preprocessBitmap(bitmap)  // → ByteBuffer 1×3×224×224
        val output = Array(1) { FloatArray(256) }
        interpreter.run(input, output)
        return normalize(output[0])  // L2 normalize
    }
}

// ml/EmbeddingMatcher.kt
class EmbeddingMatcher(context: Context) {
    private val embeddings: List<CoinEmbedding>  // Chargé depuis assets/data/embeddings_v1.json

    fun findMatches(query: FloatArray): List<MatchResult> {
        return embeddings
            .map { coin ->
                MatchResult(
                    coin = coin,
                    similarity = cosineSimilarity(query, coin.embedding)
                )
            }
            .sortedByDescending { it.similarity }
    }
}
```

### Throttling

Le scan n'a pas besoin de tourner à 30 fps. Limiter à ~5 analyses/seconde :

```kotlin
val imageAnalysis = ImageAnalysis.Builder()
    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
    .build()

// Le STRATEGY_KEEP_ONLY_LATEST + le temps d'inférence (~10ms)
// donne naturellement un throttle raisonnable
```

---

## 2.2 — UI du scan (Jetpack Compose)

### Écran principal

```kotlin
@Composable
fun ScanScreen(viewModel: ScanViewModel) {
    val scanResult by viewModel.scanResult.collectAsStateWithLifecycle()

    Box(modifier = Modifier.fillMaxSize()) {
        // 1. Preview caméra (plein écran)
        CameraPreview(
            analyzer = viewModel.coinDetector,
            modifier = Modifier.fillMaxSize()
        )

        // 2. Overlay guide circulaire
        CircleGuideOverlay(
            state = scanResult,
            modifier = Modifier.fillMaxSize()
        )

        // 3. Bottom sheet résultat
        when (val result = scanResult) {
            is ScanResult.Identified -> CoinResultSheet(result.match)
            is ScanResult.Suggestions -> SuggestionsSheet(result.matches)
            is ScanResult.NotIdentified -> NotIdentifiedBanner()
            is ScanResult.Scanning -> ScanningIndicator()
        }
    }
}
```

### Guide circulaire (overlay)

```kotlin
@Composable
fun CircleGuideOverlay(state: ScanResult, modifier: Modifier) {
    Canvas(modifier = modifier) {
        val center = Offset(size.width / 2, size.height / 2)
        val radius = size.width * 0.35f

        // Fond semi-transparent autour du cercle
        // Cercle guide
        val color = when (state) {
            is ScanResult.Scanning -> Color.White.copy(alpha = 0.5f)
            is ScanResult.Identified -> Color.Green.copy(alpha = 0.8f)
            is ScanResult.NotIdentified -> Color.Red.copy(alpha = 0.6f)
            else -> Color.White.copy(alpha = 0.5f)
        }

        drawCircle(
            color = color,
            radius = radius,
            center = center,
            style = Stroke(width = 3.dp.toPx())
        )
    }
}
```

### Bottom sheet résultat

```
┌──────────────────────────────────────┐
│  2€ Commémorative Allemagne 2006     │
│  Schleswig-Holstein (Holstentor)     │
│                                       │
│  [Image ref]  Valeur estimée : 4,20€ │
│               Rareté : Peu courante   │
│               Tirage : 30 000 000     │
│                                       │
│  [ Ajouter au Coffre ]  [ Rescanner ] │
└──────────────────────────────────────┘
```

---

## 2.3 — Gestion des permissions

```kotlin
// Demande de permission caméra au premier lancement
val cameraPermission = rememberLauncherForActivityResult(
    ActivityResultContracts.RequestPermission()
) { granted ->
    if (granted) {
        // Ouvrir la caméra
    } else {
        // Afficher un écran explicatif
    }
}

// Si permission refusée :
// → Afficher "Eurio a besoin de la caméra pour scanner tes pièces"
// → Bouton "Ouvrir les paramètres"
```

---

## 2.4 — Cycle de vie caméra

Points critiques à gérer :
- Libérer la caméra quand l'app passe en background (`ON_STOP`)
- Rebinder quand l'app revient (`ON_START`)
- Stopper l'analyzer quand on navigue vers un autre écran
- CameraX gère tout ça automatiquement via `LifecycleOwner` — c'est un des avantages du natif

```kotlin
// CameraX se bind au lifecycle automatiquement
cameraProvider.bindToLifecycle(
    lifecycleOwner,       // Le lifecycle de l'Activity/Fragment
    cameraSelector,
    preview,
    imageAnalysis         // L'analyzer se stoppe/reprend automatiquement
)
```

---

## 2.5 — Debounce du résultat

Pour éviter le "flickering" (le résultat change à chaque frame) :

```kotlin
// Ne mettre à jour le résultat que si :
// 1. Le même match est trouvé sur N frames consécutives (ex: 3)
// 2. OU si la confiance dépasse un seuil très élevé (> 0.95)

class StabilizedDetector(private val detector: CoinDetector) {
    private var lastMatch: String? = null
    private var matchCount = 0
    private val requiredCount = 3

    fun processResult(result: ScanResult): ScanResult {
        if (result is ScanResult.Identified) {
            if (result.match.coinId == lastMatch) {
                matchCount++
            } else {
                lastMatch = result.match.coinId
                matchCount = 1
            }
            return if (matchCount >= requiredCount || result.match.similarity > 0.95f) {
                result
            } else {
                ScanResult.Scanning
            }
        }
        lastMatch = null
        matchCount = 0
        return result
    }
}
```

---

## 2.6 — Livrables Phase 2

- [ ] `CoinDetector` : CameraX analyzer fonctionnel
- [ ] `CoinEmbedder` : extraction d'embedding via TFLite
- [ ] `EmbeddingMatcher` : cosine similarity, base locale
- [ ] Écran scan : preview caméra + overlay guide
- [ ] Bottom sheet résultat (identifié / suggestions / non identifié)
- [ ] Debounce des résultats (stabilisation)
- [ ] Gestion permissions caméra
- [ ] Bouton "Ajouter au Coffre" (stockage Phase 3)
- [ ] Test en conditions réelles sur les 10 pièces POC (Pixel 9a)

---

## 2.7 — Critères de succès

| Métrique | Cible |
|---|---|
| Taux de reconnaissance (10 pièces POC) | > 80% |
| Temps scan → résultat | < 3 secondes |
| Faux positifs (mauvaise pièce, haute confiance) | < 5% |
| Crashes | 0 |
| Battery drain (scan continu 5 min) | < 5% |

---

## Durée estimée

**10-14 jours**
- 3-4 jours : pipeline CameraX + TFLite + matching
- 3-4 jours : UI scan (Compose overlay, bottom sheet, animations)
- 2-3 jours : stabilisation, debounce, edge cases
- 2-3 jours : tests conditions réelles + itérations
