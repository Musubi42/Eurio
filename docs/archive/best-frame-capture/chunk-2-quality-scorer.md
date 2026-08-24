# Chunk 2 — Frame quality scorer

> Calcule à chaque frame de scan un score qualité multi-critères et
> l'expose au HUD du debug-bar. Pas encore de sélection best-frame
> (chunk-3) — juste la mesure et l'affichage.

## Pré-requis

- Chunk 1 livré et auditté (DebugBar + HUD coquille fonctionnelle).

## Goal

À chaque tick analyzer (≈ 2.5 fps) qui produit une bbox détectée et un
crop normalisé 224×224, on calcule un `FrameScore` avec :

- **Sharpness** (variance Laplacien) sur le crop 224 grayscale
- **Exposure** (moyenne luminance dans le disc + pénalité clipping)
- **Completeness** (% du cercle Hough dans la frame, marge bord)
- **Motion** (optionnel, désactivé par défaut) : delta du centre bbox
  vs frame n-1, normalisé par le rayon

Chaque sous-score est dans `[0, 1]`. Le score agrégé est une moyenne
pondérée. Le HUD update en temps réel : badges sharp / exp / comp /
agg + indicateur pass/fail vs les seuils absolus configurés dans la
debug-bar.

À la fin du chunk-2, **les scores sont calculés et visibles mais
n'influencent encore aucune décision**. Le pipeline scan continue de
fonctionner exactement comme avant (chunk-3 branchera la sélection).

## Scope

**Dans le chunk** :

- `FrameQualityScorer` (Kotlin pure object) : 4 fonctions de scoring
  + 1 fonction d'agrégation.
- `FrameScore` data class (promotion du placeholder du chunk-1 vers
  `domain/scan/quality/`).
- `ScoringPolicy` data class : poids et seuils, alimentée par
  `DebugScanConfig`.
- Wiring dans `CoinAnalyzer` : computer le score après normalisation,
  publier dans `_hudState.lastFrameScore`.
- Tests unitaires : 3 fixtures (frame nette, floue, sous-exposée) +
  edge cases (bbox au bord, rayon nul).
- Mise à jour `ScanHud.kt` du chunk-1 pour afficher les vraies
  valeurs au lieu des placeholders.

**Hors chunk** :

- Le rolling buffer N=5 (chunk-3).
- La logique "early-stop quand on passe les gates" (chunk-3).
- L'effet du score sur la state machine (chunk-6).
- Les seuils calibrés sur 50 captures bench (chunk-7).

## Architecture

```
CoinAnalyzer.analyzeFrame(imageProxy)
  │
  ├─ detector.detect() ────────────────> Detections
  │                                          │
  ├─ pickPrimaryDetection(Detections)        │
  │       │                                  │
  │       └────────────────> primary Detection (bbox + radius)
  │
  ├─ SnapNormalizer.normalize(bitmap, bbox) ──> NormalizedCrop (224×224)
  │
  ├─ NEW: FrameQualityScorer.score(
  │           crop = NormalizedCrop,
  │           detection = primary Detection,
  │           sourceSize = bitmap size,
  │           previousCenter = lastDetectionCenter,   // for motion
  │           policy = scoringPolicyFrom(debugConfig)
  │       ) ──> FrameScore
  │
  ├─ recognizer.embed(NormalizedCrop) ──> embedding
  │
  ├─ matcher.topK(embedding) ──> arcface matches
  │
  ├─ consensus.add(top1) ──> consensus state
  │
  └─ NEW: hudState.update(
         lastFrameScore = score,
         arcfaceTop3 = matches.take(3),
         timings = perStageTimings
     )
```

Le scorer est **pur** (pas d'I/O, pas de state) — testable en isolation.

## Fichiers à créer

| Fichier | Rôle |
|---|---|
| `domain/scan/quality/FrameScore.kt` | data class commune (déplace l'alias du chunk-1) |
| `domain/scan/quality/ScoringPolicy.kt` | data class poids + seuils |
| `ml/quality/FrameQualityScorer.kt` | object avec 4 fonctions de scoring + agrégation |
| `ml/quality/FrameQualityScorerTest.kt` | tests unitaires |
| `app-android/src/androidTest/.../FrameQualityScorerInstrumentedTest.kt` | tests avec OpenCV chargé (Laplacian via `org.opencv`) |

Note d'organisation : on place `FrameScore` et `ScoringPolicy` dans
`domain/scan/quality/` (réutilisable par d'autres surfaces, ex: bench
tooling), et l'implémentation `FrameQualityScorer` (qui dépend
d'OpenCV / Android) dans `ml/quality/`. Mêmes conventions que le
découpage actuel `domain/scan` vs `ml/`.

## Fichiers à modifier

| Fichier | Modification |
|---|---|
| `features/scan/debug/ScanHudState.kt` | Supprimer la déclaration locale de `FrameScore`, importer depuis `domain/scan/quality/` |
| `ml/CoinAnalyzer.kt` | Brancher le scoring après normalisation, publier dans `_hudState` |
| `features/scan/debug/ScanHud.kt` | Remplacer placeholders par badges live (sharp/exp/comp/agg + pass marks) |
| `features/scan/ScanViewModel.kt` | Construire `ScoringPolicy` depuis `DebugScanConfig` et le passer à `CoinAnalyzer` |

## FrameScore — schéma

```kotlin
data class FrameScore(
    val sharpness: Float,        // [0, 1] — normalisé depuis var(Laplacian)
    val sharpnessRaw: Float,     // valeur brute pour debug (variance non normalisée)
    val exposure: Float,         // [0, 1]
    val meanLuminance: Float,    // [0, 1] — pour debug HUD
    val clippingRatio: Float,    // [0, 1] — % pixels saturés (0 ou 255)
    val completeness: Float,     // [0, 1]
    val motion: Float?,          // [0, 1] ou null si désactivé
    val aggregate: Float,        // [0, 1] — somme pondérée selon policy
    val passes: GatesResult,     // detail pass/fail par dimension
)

data class GatesResult(
    val sharpness: Boolean,
    val exposure: Boolean,
    val completeness: Boolean,
    val motion: Boolean?,
    val all: Boolean,             // ✓ si tous les gates actifs passent
)
```

`sharpnessRaw` et `meanLuminance` / `clippingRatio` sont gardés pour
que le HUD puisse afficher des valeurs interprétables (un humain
comprend mieux "variance = 142" que "0.71"), et pour le replay (chunk-7).

## ScoringPolicy — schéma

```kotlin
data class ScoringPolicy(
    // Poids agrégation
    val wSharpness: Float = 0.5f,
    val wExposure: Float = 0.2f,
    val wCompleteness: Float = 0.2f,
    val wMotion: Float = 0.1f,

    // Seuils absolus (gates pass/fail)
    val sharpnessMin: Float = 80f,           // variance Laplacian brut
    val exposureBandHalfWidth: Float = 0.2f, // |mean − 0.5| max
    val clippingMax: Float = 0.01f,          // 1% max de pixels saturés
    val completenessMin: Float = 0.95f,      // marge ≥ 5% du rayon
    val motionMax: Float = 0.05f,            // delta center ≤ 5% rayon
    val motionEnabled: Boolean = false,

    // Normalisation sharpness brute → [0, 1]
    val sharpnessNormalizationCeiling: Float = 400f,
)

fun ScoringPolicy.Companion.fromDebugConfig(config: DebugScanConfig): ScoringPolicy =
    ScoringPolicy(
        sharpnessMin = config.sharpnessMin,
        exposureBandHalfWidth = config.exposureBandHalfWidth,
        completenessMin = config.completenessMin,
        motionEnabled = config.motionEnabled,
        // poids restent aux défauts pour le moment
    )
```

## Algos détaillés

### Sharpness

```
1. crop_gray = cv.cvtColor(crop_bgr, COLOR_BGR2GRAY)
2. mask = crop_gray > 5   // exclure le fond noir du masque circulaire
3. lap = cv.Laplacian(crop_gray, CV_64F, ksize = 3)
4. lap_inside = lap[mask]
5. raw = lap_inside.var()
6. sharpness = clamp(raw / sharpnessNormalizationCeiling, 0, 1)
7. passes = raw >= sharpnessMin
```

**Pourquoi exclure le fond noir** : depuis le chunk de normalisation
(`SnapNormalizer.kt`), le crop 224 a un masque circulaire noir
au-delà du rayon de la pièce. Inclure ces zéros dans la variance
gonflerait artificiellement le score quand la pièce remplit moins de
disc. On mesure la netteté **sur la pièce uniquement**.

### Exposure

```
1. crop_gray = ... (réutilise du sharpness)
2. mask = crop_gray > 5
3. mean = crop_gray[mask].mean() / 255.0
4. clipping_dark = (crop_gray[mask] < 4).sum() / mask.sum()
5. clipping_bright = (crop_gray[mask] > 251).sum() / mask.sum()
6. clipping = clipping_dark + clipping_bright
7. band_distance = abs(mean - 0.5) / exposureBandHalfWidth
8. exposure_band_score = max(0, 1 - band_distance)
9. clipping_score = max(0, 1 - clipping / clippingMax)
10. exposure = (exposure_band_score + clipping_score) / 2
11. passes = (band_distance <= 1) AND (clipping <= clippingMax)
```

### Completeness

```
1. Inputs: Hough output (cx, cy, r) en coordonnées de la frame source,
   et dimensions (W, H) de la frame source.
2. left_margin = (cx - r) / r
3. right_margin = (W - cx - r) / r
4. top_margin = (cy - r) / r
5. bottom_margin = (H - cy - r) / r
6. min_margin = min(left, right, top, bottom)
7. completeness = clamp((min_margin + 0.05) / 0.10, 0, 1)
   // marge ≥ 5% → score 1; marge -5% (= 5% du disc coupé) → score 0
8. passes = completeness >= completenessMin
```

Conséquence : un disc parfaitement centré, marge 10%+, donne 1.0. Un
disc qui touche le bord (marge 0) donne 0.5. Un disc rogné de 5% donne
0.0.

### Motion (optionnel)

```
1. Inputs: previous_center, current_center (en pixels), radius
2. delta = euclidean(current_center, previous_center) / radius
3. motion_score = clamp(1 - delta / motionMax, 0, 1)
4. passes = delta <= motionMax
```

Si `previousCenter` est null (première frame depuis trigger) :
`motion = 1.0, passes = true`.

### Agrégation

```
weights_active = {
    sharpness: wSharpness,
    exposure: wExposure,
    completeness: wCompleteness,
}
if motionEnabled:
    weights_active[motion] = wMotion

total_w = sum(weights_active.values())
aggregate = sum(score[k] * w / total_w for k, w in weights_active.items())
```

Donc le poids motion n'est compté que s'il est activé — `wMotion = 0.1`
ne pèse pas dans l'agrégation si `motionEnabled = false`.

## Wiring dans CoinAnalyzer

```kotlin
class CoinAnalyzer(
    // ... existing deps
    private val scorer: FrameQualityScorer,
    private val scoringPolicyFlow: StateFlow<ScoringPolicy>,
    private val hudState: MutableStateFlow<ScanHudState>,
) {
    private var lastDetectionCenter: PointF? = null

    fun analyzeFrame(imageProxy: ImageProxy) {
        val t0 = elapsedRealtimeNanos()
        val bitmap = imageProxy.toBitmap()
        val detections = detector.detect(bitmap, conf = 0.40f)
        val tDetect = (elapsedRealtimeNanos() - t0) / 1_000_000

        val primary = pickPrimary(detections) ?: run {
            hudState.update { it.copy(machineState = "Idle", lastFrameScore = null) }
            lastDetectionCenter = null
            return
        }

        val tNorm0 = elapsedRealtimeNanos()
        val crop = SnapNormalizer.normalize(bitmap, primary.bbox) ?: return
        val tNorm = (elapsedRealtimeNanos() - tNorm0) / 1_000_000

        val tScore0 = elapsedRealtimeNanos()
        val score = scorer.score(
            crop = crop,
            hough = primary.houghOutput,
            sourceSize = bitmap.size(),
            previousCenter = lastDetectionCenter,
            policy = scoringPolicyFlow.value,
        )
        val tScore = (elapsedRealtimeNanos() - tScore0) / 1_000_000
        lastDetectionCenter = primary.center

        // ArcFace + consensus comme aujourd'hui...

        hudState.update {
            it.copy(
                lastFrameScore = score,
                timings = TimingBreakdown(
                    detectMs = tDetect,
                    normalizeMs = tNorm,
                    scoreMs = tScore,
                    arcfaceMs = tArcface,
                ),
            )
        }
    }
}
```

## HUD — update affichage

Les badges qualité dans `ScanHud.kt` :

```
┌─────────────────────────────────────────────────────────────────┐
│ Detecting · sharp 142✓ · exp 0.48✓ · comp 1.00✓ · agg 0.84      │
└─────────────────────────────────────────────────────────────────┘
```

- `sharp 142✓` : valeur brute Laplacian variance, ✓ si passe le seuil
- `exp 0.48✓` : mean luminance (0.50 = parfait), ✓ si dans la bande
  et clipping OK
- `comp 1.00✓` : completeness normalisée (1.0 = disc largement dans
  frame), ✓ si ≥ seuil
- `agg 0.84` : score agrégé, sans pass mark (c'est une vue d'ensemble)

Code couleur :
- ✓ vert (`tertiary` token M3)
- ✗ rouge (`error` token M3)
- Texte semi-transparent quand `machineState == Idle` (pas de frame
  active à scorer)

## Tests unitaires

`FrameQualityScorerTest` couvre :

| Fixture | Attendu |
|---|---|
| Crop synthétique : carré noir avec disc gris uni 128 | sharpness ≈ 0 (uniforme), exposure ≈ 0.99 (centre band), passes.sharpness = false |
| Crop synthétique : disc avec texte clair | sharpness > 100, passes.sharpness = true |
| Crop sous-exposé : tous pixels du disc à 30/255 | exposure faible (band distance + clipping_dark), passes.exposure = false |
| Crop sur-exposé : 5% pixels à 255 | clipping > clippingMax, passes.exposure = false |
| Hough (cx=100, cy=100, r=80) dans frame 200×200 | completeness ≈ 0 (touche bord), passes.completeness = false |
| Hough (cx=100, cy=100, r=50) dans frame 200×200 | completeness = 1, passes.completeness = true |
| Motion : previousCenter = (100,100), current = (102,100), r=50 | delta = 0.04, motion_score ≈ 0.2 si motionMax=0.05 |
| previousCenter null | motion = 1, passes.motion = true |

Tests **instrumented** (Android) requis pour la sharpness car
`cv.Laplacian` n'est pas trivialement portable JVM-pure. Le test
construit un Bitmap synthétique et appelle le scorer comme dans le
pipeline réel.

## Acceptance criteria

**Fonctionnel** :
- [ ] Le HUD affiche 4 badges live (sharp / exp / comp / agg) à chaque
      frame où une bbox est détectée.
- [ ] Les pass marks (✓ / ✗) collent aux seuils configurés dans la
      debug-bar : bouger un slider met à jour les pass marks à la
      prochaine frame.
- [ ] Quand aucune bbox n'est détectée, les badges deviennent
      semi-transparents (état Idle).
- [ ] Le score motion est masqué dans le HUD si `motionEnabled = false`.
- [ ] Aucune décision du pipeline n'est encore influencée par le
      score : Idle / Detecting / Accepted se comportent comme avant.

**Perf** :
- [ ] Sur Pixel 9a, le scoring ajoute < 15 ms par frame analyzer
      (mesurable via le badge `score` du HUD timing row).
- [ ] Pas de régression sur la latence de la fiche pièce (toujours
      ≈ 2 s du premier consensus à l'affichage).

**Tests** :
- [ ] Tests unitaires + instrumented passent localement et en CI.
- [ ] Couverture du scorer : 100% des branches (les 4 sous-scores +
      l'agrégation).

**Code quality** :
- [ ] `FrameQualityScorer` est un `object` Kotlin ou une `class`
      stateless — pas de state mutable interne (state vit dans
      `CoinAnalyzer`).
- [ ] Aucun appel I/O ni Android-spécifique dans `domain/scan/quality/`.
      L'impl Android (`ml/quality/`) wrappe OpenCV.

## Questions ouvertes à trancher pendant l'implem

1. **Normalisation sharpness ceiling à 400** — c'est une valeur
   placeholder, calibrée empiriquement sur literature. À retuner sur
   les premières captures réelles. Pas de problème, on l'expose dans
   `ScoringPolicy`.
2. **Cas crop normalisé invalide** (NULL/empty) — soit on retourne un
   `FrameScore.failed` avec tout à 0, soit on skip le HUD update. Mon
   vote : `FrameScore.failed` pour ne pas perdre la trace dans le
   record JSONL futur.
3. **Mesure motion sur center bbox vs center Hough** — légèrement
   différent. Mon vote : center Hough (plus stable, sub-pixel preserved
   côté Python ; même propriété attendue côté Kotlin si SnapNormalizer
   l'expose).
4. **Clipping bright à 251 vs 255** — la marge à 4 unités absorbe le
   bruit JPEG / YUV. Acceptable mais peut être tuné si on observe trop
   de false positives clipping sur des reflets non saturés.
5. **Inclure un sous-score `texture_richness`** (gradient density dans
   le disc) en plus de sharpness ? Plus orthogonal à motion blur, capte
   mieux les pièces flat-relief. À évaluer après les premiers benchs —
   pas pour ce chunk.

## Mémoires & règles liées

- `feedback_no_debt` — pas de fallback silencieux : un crop invalide
  produit un `FrameScore` explicite, pas un null balayé sous le tapis.
- D7 du `decisions.md` — mesures concrètes : Laplacian variance,
  exposure, completeness, motion. Ce chunk les implémente fidèlement.
- D8 du `decisions.md` — early-stop sur seuils absolus + fallback :
  les `passes` du `FrameScore` portent l'info, mais l'utilisation
  (early-stop) est faite au chunk-3.
- D9 du `decisions.md` — `aggregate` n'est jamais exposé à l'user
  comme grade. Reste un signal interne.
- CLAUDE.md R2 (tokens) — le code couleur HUD utilise `tertiary` /
  `error` du M3 colorScheme, pas de hex hardcodé.
