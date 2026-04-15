# Pipeline de détection unifié — YOLO11 + Hough + rerank ArcFace

> Session du 2026-04-15. Reprend là où `yolo11-handoff-scan-debug.md` s'arrêtait ("YOLO11 déployé, debug à venir") et acte l'architecture de détection côté Android pour la Phase 1 du scan.

## TL;DR

Le détecteur de forme dans l'app Eurio n'est plus **YOLO seul**. C'est un pipeline à 3 étages :

```
Frame caméra (1440×1920, portrait)
    │
    ├─ Étage 1 : Detection (en parallèle)
    │     ├─ YOLO11-nano (letterbox 320×320, conf ≥ 0.40, NMS IoU 0.45)
    │     └─ OpenCV HoughCircles (radius 8-30% short side, top-5)
    │     ↓
    │     Merge + dedup IoU > 0.60 (YOLO gagne sur les overlaps)
    │     ↓
    │     Candidats finaux (cap 5, triés par confidence desc)
    │
    ├─ Étage 2 : Rerank ArcFace
    │     Pour chaque candidat : crop (padding 25% Hough / 10% YOLO)
    │                            → CoinRecognizer.infer() → cosine sim au catalog
    │     Décision :
    │       top1 > 0.20 ET (top1 > 0.55 OU top1−top2 > 0.08) → accepté
    │       sinon → rejet du frame
    │
    └─ Étage 3 : Frame consensus (affichage)
          Ring buffer des 5 derniers top-1 (class names)
          Affichage stable tant qu'une classe sort ≥ 3/5 fois
          Sticky : la card reste visible même sur misses transitoires
```

Le tout tourne à 2.5 fps (400 ms d'interval), pipeline ~200 ms par frame.

## Pourquoi ce pipeline (et pas juste YOLO)

Le modèle YOLO11-nano entraîné le 2026-04-15 sur les datasets Roboflow (OwnSoft + YoloCOIN, voir `yolo11-handoff-scan-debug.md`) marche très bien dans sa distribution d'entraînement (studio, table plate, fond propre) — val mAP50 = 0.995. Mais les captures debug en conditions réelles ont montré un **domain shift massif** :

| Scénario | YOLO seul |
|---|---|
| Pièce seule sur laptop/carton | ✅ 87-92% |
| Pièces multiples sur carton | ⚠️ détecte 1/4 à 2/4 |
| **Pièce tenue dans la main** | ❌ 0 détection |
| **Pièce sur bureau avec câbles** | ❌ 0 détection |

Les datasets Roboflow n'ont jamais vu de main humaine ni de fond encombré. Aucun tuning/retraining de YOLO sur ces mêmes données ne peut corriger ça — il faudra collecter des frames réelles et annoter (prochaine itération, non faite ici).

En attendant, **OpenCV HoughCircles** a été ajouté comme second détecteur. Un algorithme classique, déterministe, qui ne connaît rien des pièces — juste "trouve-moi les cercles" — mais fonctionne sur n'importe quel fond/éclairage car il ne dépend pas d'un training set. Ses faux positifs (bords de laptop, porte-clés, boutons ronds) sont rattrapés par l'étage 2.

## Étage 1 — Detection (YOLO + Hough)

### YOLO11-nano

Fichier : `app-android/src/main/java/com/musubi/eurio/ml/CoinDetector.kt`
Modèle : `app-android/src/main/assets/models/coin_detector.tflite` (10 MB, float32)

**Letterbox critique** : l'ancien code faisait `Bitmap.createScaledBitmap(bitmap, 320, 320, true)` qui stretchait un 1440×1920 portrait en 320×320, écrasant les pièces en ellipses verticales → YOLO ne les reconnaissait plus (out of distribution). La preprocessing correcte :

```kotlin
val scale = min(320f / srcW, 320f / srcH)
val newW = (srcW * scale).roundToInt()
val newH = (srcH * scale).roundToInt()
val padX = (320 - newW) / 2f
val padY = (320 - newH) / 2f
// Canvas 320×320 rempli gris 114/255/114 (convention Ultralytics) + bitmap centré
```

Les coords de sortie sont inversées proportionnellement :
```kotlin
val cx = (raw[0][idx] - padX) / scale
val cy = (raw[1][idx] - padY) / scale
// ...
```

**Output tensor shape** : `[1, 5, 2100]` (4 bbox + 1 conf × 2100 anchors à imgsz 320). Confirmé au runtime, pas de divergence YOLO11 vs YOLOv8 ici.

**NMS côté Kotlin** : greedy, IoU 0.45. Pas dans le tflite (export avec `nms=False`).

### Hough Circle Transform

Intégré via `org.opencv:opencv:4.10.0` (Maven Central depuis OpenCV 4.9). Taille : ~25 MB de libs natives arm64-v8a uniquement (`abiFilters.add("arm64-v8a")` dans `build.gradle.kts` — les modèles Android récents sont 100% arm64).

**Paramètres** (tunés sur captures réelles, pas sur littérature) :
- Downscale : short side à 640 px (speed, rescaling inverse après)
- Preprocessing : gray + median blur 5×5 (aide Canny sans tuer les petits cercles)
- `HOUGH_GRADIENT`, dp=1.0
- `minDist = 25% short side` (on veut plusieurs candidats proches possibles)
- `param1 = 100` (Canny high threshold)
- `param2 = 28` (accumulator, un peu bas pour la recall)
- `minRadius = 8% short side`
- `maxRadius = 30% short side`
- **Hard ceiling** : tout cercle détecté avec radius fraction > 0.30 est rejeté à la main (protection anti-laptop/écran/bord de table)

**Scoring des candidats** :
```
score = (r / shortSide) * 2 − (dist_to_center / diagonal)
```
Priorise les cercles grands et centrés, qui correspondent à l'UX attendue (scan single-coin, user approche la pièce au centre du frame). Ce scoring **n'est pas final** — c'est juste un pré-tri qui décide qui va dans le top-5 quand Hough renvoie plus de 5 cercles. Le vrai choix se fait à l'étage 2.

**Synthetic confidence** pour Hough : `(0.50 + score * 0.3).coerceIn(0.40, 0.85)`. N'est là que pour l'affichage overlay et le rapport debug — ne pilote aucune décision. Ne jamais comparer directement à une confidence YOLO (échelles différentes).

### Merge + dedup

Les deux détecteurs tournent **toujours en parallèle** sur chaque frame (pas de fallback). Leurs résultats sont mergés :

```kotlin
val merged = ArrayList<Detection>(yoloKept)
for (hough in houghKept) {
    val overlapsYolo = yoloKept.any { iou(it.bbox, hough.bbox) > 0.60f }
    if (!overlapsYolo) merged.add(hough)
}
val final = merged.sortedByDescending { it.confidence }.take(5)
```

**YOLO gagne** lors d'overlap parce qu'il a une notion sémantique de "pièce" (entraîné sur coins). Hough n'a que la géométrie. Quand les deux voient le même cercle, on garde la bbox YOLO.

Quand YOLO échoue, Hough rattrape. Quand YOLO réussit, Hough peut quand même ajouter des candidats qu'il n'a pas vus (objets occultés, éclairage étrange) — qui seront triés par l'étage 2.

## Étage 2 — Rerank ArcFace (spread-based)

Fichier : `app-android/src/main/java/com/musubi/eurio/ml/CoinAnalyzer.kt`

### Pourquoi un rerank

Après l'étage 1 on a jusqu'à 5 candidats. Certains sont des vraies pièces, d'autres des faux cercles (doigt, ombre, bouton, bord d'objet). La **géométrie seule ne suffit pas** : un porte-clé rond peut avoir un meilleur score géométrique qu'une vraie pièce dans la même frame (cas observé dans les captures du 2026-04-15).

La sémantique vient du modèle ArcFace déjà chargé pour l'identification (`CoinRecognizer` + `EmbeddingMatcher`). On réutilise ce modèle pour **classer chaque candidat** et choisir celui dont l'embedding ressemble le plus à une pièce connue. C'est gratuit architecturalement — aucun nouveau modèle à charger.

### Flow

Pour chaque candidat :
1. Crop avec padding adapté à la source :
   - `HOUGH → 0.25` (Hough accroche souvent le disque intérieur des bimétalliques → il faut padding généreux pour capturer l'anneau extérieur)
   - `YOLO → 0.10` (bbox déjà tight par le modèle)
2. `recognizer.infer(crop)` → embedding 256d
3. `matcher.match(embedding, topK=3)` → `List<CoinMatch>` (className, cosine similarity)
4. On retient `top1`, `top2`, et la liste complète.

Puis on choisit le candidat avec le plus haut `top1`.

### Décision : spread-based

Pas un simple seuil absolu sur `top1`. Le seuil pur `top1 > 0.15` laissait passer des faux positifs où ArcFace donnait 0.40-0.55 sur un doigt (bruit structurel avec seulement 5 classes entraînées).

**Règle finale** :
```
absolute_ok     = top1 > 0.20          // plancher absolu, rejette garbage total
confident_alone = top1 > 0.55          // top1 assez haut, spread pas nécessaire
clear_winner    = top1 > 0.20 ET (top1 − top2) > 0.08
accepted        = absolute_ok ET (confident_alone OR clear_winner)
```

Les constantes sont dans `CoinAnalyzer.Companion` (`RERANK_TOP1_MIN`, `RERANK_CONFIDENT_ALONE`, `RERANK_SPREAD_MIN`). Elles sont calibrées sur très peu de captures et **doivent être retunées** quand on aura plus de données.

**Pourquoi le spread** : une vraie pièce donne un gagnant net (ex : top1=0.73, top2=0.28, spread=0.45). Un faux cercle donne des matches tous moyens et serrés (ex : top1=0.44, top2=0.38, spread=0.06). L'écart est plus discriminant que la valeur absolue.

**Pourquoi le `confident_alone`** : deux pièces très similaires du catalog (ex : 1€ France vs 1€ Italie) peuvent toutes deux matcher fort → spread faible mais top1 réel. On ne veut pas les rejeter.

### Coût

`Ncandidats × ~15 ms` d'inférence ArcFace. Typiquement 3-5 candidats → 45-75 ms par frame. Le winner réutilise ses matches déjà calculés (pas de 2e inférence). `identificationInferenceMs` dans `ScanResult` = `rerankMs` par construction.

## Étage 3 — Frame consensus (affichage stable)

Fichier : `app-android/src/main/java/com/musubi/eurio/MainActivity.kt`

Le problème UX : à 2.5 fps, chaque frame est un nouveau jugement ArcFace qui peut hésiter entre 2-3 classes proches. Sans lissage, la card affichée clignote entre "Italie", "France", "Allemagne" toutes les 400 ms.

### Ring buffer de 5 frames

```kotlin
private val recentMatches = ArrayDeque<String?>()  // null = miss
private var consensusClass by mutableStateOf<String?>(null)
private var consensusSimilarity by mutableStateOf(0f)

// À chaque onScanResult :
recentMatches.addLast(result.matches.firstOrNull()?.className)
while (recentMatches.size > CONSENSUS_WINDOW) recentMatches.removeFirst()

val counts = recentMatches.filterNotNull().groupingBy { it }.eachCount()
val newConsensus = counts.entries
    .filter { it.value >= CONSENSUS_THRESHOLD }  // ≥ 3/5
    .maxByOrNull { it.value }?.key

if (newConsensus != null && newConsensus != consensusClass) {
    consensusClass = newConsensus  // switch
    if (newConsensus != lastFetchedClass) fetchCoinDetail(newConsensus)
}
// Sticky : sinon on ne touche pas à consensusClass
```

**Fenêtre = 5**, **seuil = 3** (majorité simple sur ~2 secondes à 2.5 fps).

### Sticky display

`consensusClass` n'est **jamais remis à null**. Il change uniquement quand un nouveau consensus apparaît. Conséquences :
- Miss transitoire (1-2 frames) : card reste affichée
- User bouge la caméra : card reste sur la dernière identifiée stable jusqu'à ce qu'une nouvelle soit confirmée sur 3 frames
- Transition entre 2 pièces : ~1.2 s de délai (le temps que 3 nouvelles frames s'accordent)

C'est volontaire : **stabilité > réactivité**. Cohérent avec l'UX cible "scan comme un QR code — tu poses, ça lit, c'est stable".

### Côté Supabase fetch

Le déclencheur du fetch `CoinDetail` est la transition de `consensusClass`, pas chaque frame. `lastFetchedClass` garde trace de la dernière valeur pour déduper. Pas de hammering Supabase.

## Observabilité — rapport debug enrichi

Le bouton "CAPTURE" écrit maintenant un `capture_TS.txt` avec :

- **Fichiers** : raw frame, frame annotée (toutes bboxes + selected thicker), crop utilisé
- **Configuration ML** : YOLO on/off + modèle, mode ArcFace + nombre de classes, seuils
- **Image source** : résolution caméra, letterbox params
- **YOLO** : raw count, kept après NMS, timings
- **Hough** : statut, params, kept count, timings
- **Merge** : counts YOLO/Hough, dedup count, candidats finaux
- **Rerank** : règle, top1/top2/spread par candidat avec marker `← SÉLECTIONNÉ`, décision finale ("ACCEPTED top1=X ≥ 0.55 (confident_alone)" ou "REJECTED top1=X spread=Y (mid-range without spread)")
- **Identification** : modèle, padding utilisé (10% ou 25%), top 3 matches
- **Consensus** : buffer récent, comptes par classe, classe active, similarity affichée
- **Supabase detail** : nom, pays, année, valeur, type, URL image avers

Plus l'overlay dessine toutes les détections (sélectionnée en trait épais + label `YOLO 89%` ou `HOUGH 63%`) — en direct pour debug visuel.

Pull local via `go-task android:pull-debug` (sous-dossier horodaté sous `debug_pull/`).

## Ce qui est acté / ce qui reste

### Acté dans cette session

- ✅ Letterbox YOLO (fix essentiel)
- ✅ Multi-détection + NMS côté Kotlin
- ✅ Camera `ResolutionSelector` 720×1280 (le device donne 1440×1920 effectif)
- ✅ OpenCV + HoughCircles en parallèle de YOLO (pas fallback)
- ✅ Merge + dedup IoU 0.6
- ✅ Rerank ArcFace spread-based sur tous les candidats
- ✅ Frame consensus 5/3 sticky
- ✅ Rapport debug complet + overlay live multi-bbox
- ✅ Interval 400 ms (2.5 fps)
- ✅ Taskfile `go-task android:*`

### Limites connues, à adresser plus tard

1. **Calibration des seuils rerank** : `RERANK_TOP1_MIN=0.20`, `RERANK_CONFIDENT_ALONE=0.55`, `RERANK_SPREAD_MIN=0.08` sont calibrés sur 3 captures. Tuner quand on aura 50+ captures annotées manuellement "coin / not coin".

2. **ArcFace n'a que 5 classes** : la décision spread-based fonctionne mieux avec plus de classes. Quand on scale le catalog ArcFace à 50+, spread deviendra encore plus discriminant.

3. **Fine-tuning YOLO sur données réelles** : la vraie sortie long-terme. L'infra debug capture collecte déjà les frames. Process à mettre en place :
   - Exporter `frame_*.jpg` + `capture_*.txt` vers un dataset
   - Utiliser Hough+ArcFace du pipeline actuel comme pré-annotations weak
   - Valider/corriger à la main (~30 min pour 100 frames)
   - Retrain YOLO11n 50 epochs depuis `best.pt`
   - Le pipeline devient robuste → Hough peut disparaître ou rester en ceinture+bretelles

4. **OpenCV taille APK** : +25 MB. Si l'APK final doit être slim pour release, envisager un build OpenCV stripped (imgproc + core uniquement, sans calib3d/features2d/etc).

5. **Hough cercles trop petits** : `minRadius = 8%` rejette les pièces filmées de loin. À voir si c'est gênant en pratique.

6. **Latence à 2.5 fps** : pipeline ~200 ms. Si un device plus lent descend à 300+ ms, l'UX se dégrade. À benchmarker sur Pixel 9a (test rig actuel) puis un mid-range Samsung.

## Fichiers touchés dans cette session

| Fichier | Rôle |
|---|---|
| `app-android/build.gradle.kts` | Ajout dep OpenCV 4.10.0 + abiFilter arm64-v8a |
| `app-android/src/main/java/com/musubi/eurio/ml/CoinDetector.kt` | Letterbox, multi-détection YOLO, Hough+merge, NMS, DetectionBatch |
| `app-android/src/main/java/com/musubi/eurio/ml/CoinAnalyzer.kt` | Rerank universel spread-based, ScanResult enrichi, drawYoloOverlay multi-bbox |
| `app-android/src/main/java/com/musubi/eurio/ml/CoinEmbedder.kt` | `modelPath` exposé publiquement (pour rapport debug) |
| `app-android/src/main/java/com/musubi/eurio/MainActivity.kt` | OpenCV init, ResolutionSelector, YoloBboxOverlay live multi-bbox, consensus state, rapport debug complet |
| `Taskfile.yml` + `app-android/Taskfile.yml` | Commandes go-task pour build/install/run/logs/pull-debug |
| `.gitignore` | `debug_pull/` exclu |

## Références croisées

- `yolo11-handoff-scan-debug.md` : état de départ de cette session (YOLO11 déployé, debug à faire)
- `yolo11-train-commands.md` : commandes pour retrain quand on aura collecté des données réelles
- `yolo-detection-findings.md` : pre-mortem des datasets Roboflow
- `arcface-few-shot.md` : design de l'identification ArcFace (étage 2)
