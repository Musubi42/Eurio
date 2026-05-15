# Chunk 1 — Debug-bar + HUD live

> Outil dev qui rend les chunks suivants benchables. Aucune ligne de
> production n'est touchée fonctionnellement — on ajoute uniquement de
> l'observabilité et des leviers temps-réel, conditionnés à
> `BuildConfig.DEBUG`.

## Pré-requis

Aucun. C'est le prérequis transverse des chunks 2-7.

## Goal

Permettre, sur un APK debug build :

1. **Sélectionner à chaud** la stratégie de trigger + ses paramètres,
   la taille du burst, le mode de capture, l'activation du lock AE/AF/AWB,
   les seuils des quality gates — sans rebuild.
2. **Observer en temps réel** ce que le pipeline fait : state machine,
   scores qualité de la frame courante et du best-frame, ArcFace top-3,
   timing par étape.
3. **Snapshot une session** : record JSONL + frames raw (opt-in toggle),
   pour replay à froid (chunk 7).

Sur un APK release, **rien de tout ça n'est shippé** : pas d'overlay,
pas de bottom-sheet, pas de classes inutiles dans le DEX. Vérifiable
via APK Analyzer.

## Scope

**Dans le chunk** :

- Composable `DebugBar` (bottom-sheet) + Composable `ScanHud` (overlay).
- `DebugScanConfig` data class + `DebugScanConfigStore` (en mémoire, pas DataStore).
- Hooks dans `ScanViewModel` pour exposer `StateFlow<DebugScanConfig>`
  et `StateFlow<ScanHudState>` — uniquement compilés si `BuildConfig.DEBUG`.
- Bouton flottant "DBG" qui ouvre le bottom-sheet, placement coin
  bas-droit de `ScanScreen`.
- HUD overlay en haut de l'écran (badges discrets noir transparent).

**Hors chunk** (fait dans les chunks suivants) :

- L'**effet** des leviers n'est pas câblé encore — un slider IoU_min
  bouge la valeur dans `DebugScanConfig`, mais le `BoxStabilityTrigger`
  qui le consomme n'existe pas tant que chunk-3 n'est pas livré. Idem
  pour les quality gates (chunk-2), AE/AF lock (chunk-4), etc.
- Le **replay** (chunk-7) lit les sessions enregistrées ici ; ce chunk
  livre uniquement le record, pas le replay.

Conséquence : à la fin du chunk-1, on a un debug-bar **fonctionnel mais
inerte** (sliders bougent, les valeurs s'affichent dans le HUD, mais ne
font rien encore). C'est voulu — ça permet d'auditer l'UI debug
isolément avant d'y brancher la logique.

## Architecture

```
ScanScreen.kt
├── CameraPreview (existant)
├── ScanHud (NOUVEAU, overlay top, BuildConfig.DEBUG only)
└── DebugBarLauncher (NOUVEAU, FAB "DBG" bottom-end, BuildConfig.DEBUG only)
    └── DebugBar (ModalBottomSheet, sliders + toggles + radios)
            ↓
        DebugScanConfigStore (singleton in-memory)
            ↓
        ScanViewModel.debugConfig: StateFlow<DebugScanConfig>
```

Le `DebugScanConfigStore` est exposé uniquement en debug build. En
release, `ScanViewModel.debugConfig` retourne `flowOf(DebugScanConfig())`
(défauts hard-codés), de sorte que le code de production lit la même
interface mais sans surface UI ni mutation.

## Fichiers à créer

| Fichier | Rôle |
|---|---|
| `features/scan/debug/DebugBar.kt` | Composable bottom-sheet avec tous les leviers |
| `features/scan/debug/ScanHud.kt` | Composable overlay avec badges live |
| `features/scan/debug/DebugScanConfig.kt` | data class config + defaults |
| `features/scan/debug/DebugScanConfigStore.kt` | Singleton in-memory MutableStateFlow |
| `features/scan/debug/ScanHudState.kt` | data class métriques temps-réel |
| `features/scan/debug/DebugBarLauncher.kt` | FAB "DBG" + remember showSheet state |

Les six fichiers sont sous `features/scan/debug/` — un sous-package
dédié, qu'on peut whitelister facilement dans une règle ProGuard
release pour shrink garanti.

## Fichiers à modifier

| Fichier | Modification |
|---|---|
| `features/scan/ScanScreen.kt` | Ajouter `ScanHud` + `DebugBarLauncher` overlay (gated `BuildConfig.DEBUG`) |
| `features/scan/ScanViewModel.kt` | Exposer `debugConfig` et `hudState` StateFlows (en debug : lit `Store` ; en release : flowOf défauts) |
| `app/build.gradle.kts` ou équivalent | Vérifier que `BuildConfig.DEBUG` est généré (déjà le cas par défaut Android) |
| ProGuard rules | Optionnel : règle `-assumenosideeffects` ou `-checkdiscard` sur `features.scan.debug.**` en release |

## DebugScanConfig — schéma

```kotlin
data class DebugScanConfig(
    // Trigger
    val triggerMode: TriggerMode = TriggerMode.OFF,
    val stabilityIouMin: Float = 0.7f,
    val stabilityNFrames: Int = 3,
    val yoloConfMin: Float = 0.50f,

    // Burst
    val burstSize: Int = 5,
    val rollingBufferEnabled: Boolean = true,

    // Lock
    val aeLockEnabled: Boolean = true,
    val afLockEnabled: Boolean = true,
    val awbLockEnabled: Boolean = true,

    // Quality gates (absolus pour early-stop)
    val sharpnessMin: Float = 80f,        // Laplacian variance
    val exposureBandHalfWidth: Float = 0.2f, // |mean − 0.5| < this
    val completenessMin: Float = 0.95f,   // marge bord ≥ 5%
    val motionEnabled: Boolean = false,

    // Capture
    val captureMode: CaptureMode = CaptureMode.PREVIEW_ONLY,

    // Record (chunk 7 consume)
    val recordEnabled: Boolean = false,
)

enum class TriggerMode { OFF, BOX_STABILITY, YOLO_CONFIDENCE, ARCFACE_CONSENSUS }
enum class CaptureMode { PREVIEW_ONLY, IMAGECAPTURE_FULL, BOTH_PARALLEL }
```

Les défauts encodent **le comportement actuel + best-frame désactivé**
(`triggerMode=OFF` → scan continu sans best-frame, identique à
aujourd'hui). Cela garantit qu'à la fin du chunk-1, l'app se comporte
exactement comme avant tant qu'on ne touche pas les sliders.

## ScanHudState — schéma

```kotlin
data class ScanHudState(
    val machineState: String = "Idle",        // libellé court
    val sinceTriggerMs: Long? = null,
    val lastFrameScore: FrameScore? = null,
    val bestFrameScore: FrameScore? = null,
    val bestFrameIndex: Int? = null,
    val arcfaceTop3: List<ArcfaceMatch> = emptyList(),
    val timings: TimingBreakdown = TimingBreakdown(),
)

data class FrameScore(
    val sharpness: Float,
    val exposure: Float,
    val completeness: Float,
    val aggregate: Float,
)

data class TimingBreakdown(
    val detectMs: Long = 0,
    val normalizeMs: Long = 0,
    val arcfaceMs: Long = 0,
    val scoreMs: Long = 0,
)
```

Toutes les valeurs sont alimentées par les chunks suivants. Au chunk-1,
le HUD affiche les défauts (mostly `0` / `null`) tant que rien n'est
câblé.

## UI — layout

**DebugBarLauncher (FAB)** : petit bouton flottant 48dp, coin bas-droit
de `ScanScreen`, libellé "DBG", couleur tertiaire M3. Visible uniquement
si `BuildConfig.DEBUG`. Tap → ouvre `DebugBar` en bottom-sheet.

**DebugBar (ModalBottomSheet)** : sections clairement séparées par
headers M3 :

```
┌─ DEBUG · best-frame capture ──────────────────┐
│                                               │
│ Trigger                                       │
│  ◉ OFF (continu actuel)                       │
│  ○ Box stability     IoU [══●═══════] 0.70   │
│                       N   [════●════] 3       │
│  ○ YOLO confidence   conf[═══●═════] 0.50    │
│  ○ ArcFace consensus                          │
│                                               │
│ Capture                                       │
│  ◉ Preview only                               │
│  ○ ImageCapture full                          │
│  ○ Both parallel                              │
│  Burst size [════●═══] 5                      │
│  Rolling buffer [✓]                           │
│                                               │
│ Lock                                          │
│  AE [✓]   AF [✓]   AWB [✓]                    │
│                                               │
│ Quality gates                                 │
│  Sharpness min     [══●═══════] 80            │
│  Exposure band     [══●═══════] 0.20          │
│  Completeness min  [════════●═] 0.95          │
│  Motion gate       [ ]                        │
│                                               │
│ Record                                        │
│  [ ] Record session (JSONL + frames)          │
│  [Reset to defaults]    [Close]               │
└───────────────────────────────────────────────┘
```

Sliders M3 standards, pas de custom rendering. Bottom-sheet
`SheetState(skipPartiallyExpanded = false)` pour qu'il puisse se replier
sans fermer.

**ScanHud (overlay top)** : row de badges semi-transparents en haut de
l'écran sous le status bar, lecture seule. Layout horizontal scrollable
si trop d'infos :

```
┌─────────────────────────────────────────────────────────────┐
│ Detecting  •  sharp 142  •  exp 0.48  •  comp 1.00  •  t+0.8s │
└─────────────────────────────────────────────────────────────┘
```

En cas de transition state, le badge state pulse ~200ms. ArcFace top-3 +
timings dans une seconde row qui apparaît au passage Identifying.

## ScanViewModel — wiring

```kotlin
class ScanViewModel(...) : ViewModel() {

    val debugConfig: StateFlow<DebugScanConfig> = if (BuildConfig.DEBUG) {
        DebugScanConfigStore.config
    } else {
        MutableStateFlow(DebugScanConfig()).asStateFlow()
    }

    private val _hudState = MutableStateFlow(ScanHudState())
    val hudState: StateFlow<ScanHudState> = _hudState.asStateFlow()

    // Les futurs chunks (2-6) updateront _hudState au fil du pipeline.
    // Au chunk-1, _hudState reste à ses défauts.
}
```

Note : `ScanHudState` est exposé même en release (le coût d'un
`StateFlow` inactif est négligeable), mais le Composable `ScanHud` qui
l'observe n'est rendu qu'en debug. Cela simplifie le câblage des chunks
suivants : ils updateront le state sans condition build, et seule la
projection UI est conditionnée.

## Acceptance criteria

**Debug build** :
- [ ] Bouton "DBG" flottant visible coin bas-droit de l'écran scan.
- [ ] Tap → bottom-sheet s'ouvre avec toutes les sections.
- [ ] Chaque slider bouge, chaque toggle change d'état, chaque radio est
      sélectionnable, et la valeur affichée est cohérente.
- [ ] HUD overlay visible en haut de l'écran, affiche au minimum le
      libellé "Idle" (placeholder).
- [ ] `[Reset to defaults]` remet tous les leviers aux valeurs initiales
      sans fermer le sheet.
- [ ] Le scan continuous existant fonctionne exactement comme avant tant
      que `triggerMode = OFF` (= aucun comportement changé).
- [ ] Rotation device : l'état du DebugBar persiste (pas reset à chaque
      recomposition).

**Release build** :
- [ ] Pas de bouton DBG visible.
- [ ] Pas de HUD overlay.
- [ ] APK Analyzer : aucune classe sous `features.scan.debug.**` dans le
      DEX final (vérifier via `./gradlew assembleRelease` + `apkanalyzer`).
- [ ] Comportement scan = inchangé strictement.

**Compilation** :
- [ ] `./gradlew :app-android:assembleDebug` passe.
- [ ] `./gradlew :app-android:assembleRelease` passe (avec ou sans
      ProGuard).

## Questions ouvertes à trancher pendant l'implem

1. **Persistance de `DebugScanConfig` entre sessions ?** Mon vote : non,
   reset à chaque cold start. Les valeurs sont exploratoires, pas des
   préférences user. Si on veut les sauver pour un bench long, on les
   notera ailleurs (commit ou texto). Sinon DataStore = surface en plus
   à maintenir.
2. **HUD visible aussi pendant Accepted (= fiche affichée) ?** Mon vote :
   oui, semi-transparent par-dessus la fiche, pour pouvoir lire la
   décision finale sans switcher d'écran. Tape sur le HUD = le masque
   temporairement.
3. **Bottom-sheet draggable ou modal ?** Mon vote : draggable
   (`ModalBottomSheet` avec drag handle). On veut pouvoir entrouvrir
   pour ajuster un slider, ré-ouvrir pour voir le HUD, sans fermer.
4. **ProGuard `-checkdiscard` sur `features.scan.debug.**` ?** Souhaitable
   mais à valider que rien d'autre ne référence la classe (sinon
   compilation rouge). À tester après la PR.

## Mémoires & règles liées

- `feedback_no_debt` — pas de toggle caché, pas de feature flag user-facing,
  debug-only se mérite via debug build.
- `feedback_chunk_audit_flow` — chunk audit visuel attendu sur APK debug
  installé : screencast du DebugBar + HUD avec tous les leviers manipulés.
- CLAUDE.md R1 (proto-first) : ce chunk est **exempté**. La debug-bar
  n'est pas une scène user-facing — c'est un outil technique purement
  développeur. Vérifié à l'écriture.
- CLAUDE.md R2 (tokens) : les couleurs du HUD utilisent
  `MaterialTheme.colorScheme.*` (surface, onSurface, tertiary). Pas de
  hex hardcodé.
