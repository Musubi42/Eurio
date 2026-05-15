# Chunk 3 — Trigger strategies + rolling buffer

> Trois stratégies de trigger interchangeables (`box_stability`,
> `yolo_confidence`, `arcface_consensus`) + un rolling buffer N=5 qui
> garde les dernières frames scorées + un `BestFrameSelector` qui choisit
> la meilleure à chaque fire. Aucune action concrète déclenchée encore
> (pas de lock caméra, pas d'archive) — on observe.

## Pré-requis

- Chunk 1 livré (DebugBar avec sliders trigger + HUD coquille).
- Chunk 2 livré (FrameQualityScorer produit `FrameScore` à chaque frame).

## Goal

À la fin du chunk-3 :

1. Le **rolling buffer** retient les N dernières `BufferedFrame`
   (crop 224 + score + detection + arcface_top3 + timestamp), N
   configurable via debug-bar (défaut 5).
2. **Trois `TriggerStrategy`** sont instanciables et sélectionnables
   au runtime. Chacune observe le flux de frames et décide quand
   émettre un `TriggerEvent.Fire`.
3. À chaque `Fire`, le **`BestFrameSelector`** consomme la snapshot du
   buffer et retourne la frame retenue + le motif de sélection
   (`passed_all_gates` ou `best_aggregate_fallback`).
4. Le HUD affiche `bestFrameIndex`, le score de la frame retenue, et
   le motif. L'utilisateur de la debug-bar peut comparer visuellement
   les triggers et leurs paramètres en condition réelle.

À ce stade, **aucun side effect** : pas de lock caméra (chunk-4), pas
de ImageCapture (chunk-5), pas de bascule d'état formelle (chunk-6).
On observe.

## Scope

**Dans le chunk** :

- Interface `TriggerStrategy` + 4 impls (`NoOp`, `BoxStability`,
  `YoloConfidence`, `ArcfaceConsensus`).
- `RollingFrameBuffer` avec capacité dynamique.
- `BestFrameSelector` qui implémente la logique D8 (early-stop sur
  gates absolus, fallback relatif).
- `TriggerStrategyFactory` qui produit la bonne strategy depuis
  `DebugScanConfig`.
- Wiring dans `CoinAnalyzer` : push buffer, observe trigger, propage
  l'event au HUD.
- Tests : unitaires (triggers en isolation avec frames mockées) +
  instrumented (smoke test avec un vrai scan device pour valider que
  le HUD reflète bien les fires).

**Hors chunk** :

- Lock AE/AF/AWB déclenché par `Fire` (chunk-4).
- ImageCapture full-res déclenché par `Fire` (chunk-5).
- Bascule d'état formelle `Detecting → Locking` (chunk-6) — pour le
  moment on émet le label "Trigger fired" dans le HUD mais on reste
  dans la machine actuelle.
- Calibration empirique des seuils sur 50 captures (chunk-7).

## Architecture

```
CoinAnalyzer.analyzeFrame(...)
  │
  ├─ existing: detect → normalize → score → arcface → consensus
  │
  ├─ NEW: rollingBuffer.push(BufferedFrame(...))
  │
  ├─ NEW: triggerStrategyFlow.value.observe(FrameContext) ──> TriggerEvent?
  │
  └─ NEW: when (event) is Fire ──> selector.select(snapshot)
                                       ↓
                                  SelectionResult
                                       ↓
                                  hudState.update {
                                      bestFrameIndex, bestFrameScore,
                                      machineState = "Trigger fired (reason)"
                                  }
                                       ↓
                                  trigger.reset()
                                  // pas de side effect prod (chunks 4-6)
```

Le `TriggerStrategy` est **stateful** par instance (chaque strategy
maintient son propre compteur, son IoU précédent, etc.). C'est pour
ça qu'on a une factory et qu'on instancie une nouvelle strategy à
chaque changement de mode.

## Fichiers à créer

| Fichier | Rôle |
|---|---|
| `domain/scan/trigger/TriggerStrategy.kt` | Interface + sealed `TriggerEvent` |
| `domain/scan/trigger/FrameContext.kt` | Input des `observe()` |
| `domain/scan/trigger/SelectionResult.kt` | Output du selector |
| `ml/trigger/NoOpTriggerStrategy.kt` | Mode OFF — ne fire jamais |
| `ml/trigger/BoxStabilityTrigger.kt` | IoU temporel ≥ iouMin sur N frames |
| `ml/trigger/YoloConfidenceTrigger.kt` | conf ≥ confMin sur N frames |
| `ml/trigger/ArcfaceConsensusTrigger.kt` | Fire quand consensus 3/5 atteint |
| `ml/trigger/TriggerStrategyFactory.kt` | Construit la strategy depuis DebugScanConfig |
| `ml/trigger/RollingFrameBuffer.kt` | Ring buffer capacité ajustable |
| `ml/trigger/BestFrameSelector.kt` | Logique D8 (gates absolus + fallback) |
| `ml/trigger/BufferedFrame.kt` | data class de l'item bufferisé |
| Tests unitaires (un par trigger + selector + buffer) | |

## Fichiers à modifier

| Fichier | Modification |
|---|---|
| `ml/CoinAnalyzer.kt` | Wire buffer + trigger + selector ; publier dans HUD |
| `features/scan/ScanViewModel.kt` | Construire la factory + flow `triggerStrategy` qui réagit aux changements de `DebugScanConfig` |
| `features/scan/debug/ScanHud.kt` | Afficher `bestFrameIndex` et le motif de sélection en second row |

## Schémas Kotlin

### `TriggerStrategy`

```kotlin
interface TriggerStrategy {
    /** Identifiant pour les logs et le HUD. */
    val name: String

    /**
     * Appelée à chaque frame analyzer. Peut consommer le `FrameContext`
     * (buffer courant, consensus, primary detection) et retourner un
     * event (ou null si pas encore prêt).
     */
    fun observe(context: FrameContext): TriggerEvent?

    /** Remet l'état interne à zéro (appelée après Fire ou sur changement de mode). */
    fun reset()
}

sealed class TriggerEvent {
    /** La strategy demande à déclencher le best-frame. Snapshot inclus. */
    data class Fire(
        val reason: String,
        val bufferSnapshot: List<BufferedFrame>,
    ) : TriggerEvent()

    /** La strategy demande d'aborter (sortie de zone de stabilité). */
    object Abort : TriggerEvent()
}
```

### `FrameContext`

```kotlin
data class FrameContext(
    val sequenceId: Int,                      // monotone increasing
    val buffer: List<BufferedFrame>,          // snapshot lecture seule
    val primaryDetection: Detection?,          // null si pas de bbox
    val arcfaceTop1: ArcfaceMatch?,
    val consensusState: ConsensusState,        // existing (5/3 sticky)
)
```

### `BufferedFrame`

```kotlin
data class BufferedFrame(
    val sequenceId: Int,
    val timestampNs: Long,
    val crop: NormalizedCrop,                 // 224×224 BGR uint8, ~150 KB
    val score: FrameScore,
    val detection: Detection,
    val arcfaceTop3: List<ArcfaceMatch>,
)
```

Le `NormalizedCrop` est gardé tel quel (référence Bitmap). Mémoire :
~150 KB × 5 frames = 750 KB en RAM. Acceptable pour Pixel 9a et
mid-range Samsung (4-8 GB RAM). À surveiller si on monte à N=10+.

### `SelectionResult`

```kotlin
sealed class SelectionResult {
    data class Best(
        val frame: BufferedFrame,
        val indexInSnapshot: Int,
        val reason: SelectionReason,
    ) : SelectionResult()

    /** Aucune frame disponible (buffer vide). */
    object Empty : SelectionResult()
}

enum class SelectionReason {
    PASSED_ALL_GATES,           // une frame passe tous les gates absolus
    BEST_AGGREGATE_FALLBACK,    // aucune ne passe → on prend la meilleure relative
}
```

## Algorithmes par strategy

### `NoOpTriggerStrategy`

```kotlin
class NoOpTriggerStrategy : TriggerStrategy {
    override val name = "off"
    override fun observe(context: FrameContext) = null
    override fun reset() {}
}
```

Comportement : never fires. C'est le défaut, garantit que le scan
fonctionne comme aujourd'hui tant que l'utilisateur ne flippe pas le
mode dans la debug-bar.

### `BoxStabilityTrigger`

```kotlin
class BoxStabilityTrigger(
    private val iouMin: Float,        // 0.7 typique
    private val nFramesRequired: Int, // 3 typique
) : TriggerStrategy {
    override val name = "box_stability"

    private var firedForRun = false
    private var consecutive = 0
    private var lastBbox: Rect? = null

    override fun observe(context: FrameContext): TriggerEvent? {
        if (firedForRun) return null

        val current = context.primaryDetection?.bbox
        if (current == null) {
            consecutive = 0
            lastBbox = null
            return null
        }

        val prev = lastBbox
        if (prev != null) {
            val iou = iou(prev, current)
            if (iou >= iouMin) consecutive++ else consecutive = 1
        } else {
            consecutive = 1
        }
        lastBbox = current

        return if (consecutive >= nFramesRequired) {
            firedForRun = true
            TriggerEvent.Fire(
                reason = "stable ${consecutive}f IoU≥${iouMin}",
                bufferSnapshot = context.buffer,
            )
        } else null
    }

    override fun reset() {
        firedForRun = false
        consecutive = 0
        lastBbox = null
    }
}
```

### `YoloConfidenceTrigger`

```kotlin
class YoloConfidenceTrigger(
    private val confMin: Float,       // 0.50 typique
    private val nFramesRequired: Int, // 3 typique
) : TriggerStrategy {
    override val name = "yolo_confidence"

    private var firedForRun = false
    private var consecutive = 0

    override fun observe(context: FrameContext): TriggerEvent? {
        if (firedForRun) return null
        val conf = context.primaryDetection?.yoloConfidence
        if (conf == null || conf < confMin) {
            consecutive = 0
            return null
        }
        consecutive++
        return if (consecutive >= nFramesRequired) {
            firedForRun = true
            TriggerEvent.Fire(
                reason = "yolo ${consecutive}f conf≥${confMin}",
                bufferSnapshot = context.buffer,
            )
        } else null
    }

    override fun reset() { firedForRun = false; consecutive = 0 }
}
```

Note : le `Detection` côté Android porte aussi des bbox issues de
Hough — pour celles-là, `yoloConfidence` est null (Hough n'a pas de
score probabiliste équivalent). Conséquence : `YoloConfidenceTrigger`
ne fire jamais sur une pièce détectée uniquement par Hough. C'est un
trade-off voulu : si on veut un trigger qui marche aussi Hough-only,
on prend `BoxStability` qui est agnostique.

### `ArcfaceConsensusTrigger`

```kotlin
class ArcfaceConsensusTrigger : TriggerStrategy {
    override val name = "arcface_consensus"

    private var firedForConsensus: String? = null  // eurio_id du consensus déjà fired

    override fun observe(context: FrameContext): TriggerEvent? {
        val consensus = context.consensusState
        val locked = consensus.lockedClass ?: return null
        if (firedForConsensus == locked) return null

        firedForConsensus = locked
        return TriggerEvent.Fire(
            reason = "consensus ${locked}",
            bufferSnapshot = context.buffer,
        )
    }

    override fun reset() { firedForConsensus = null }
}
```

Particularité : fire **une seule fois par consensus locké**. Si le
consensus change (l'utilisateur passe à une autre pièce), il re-fire
pour la nouvelle. Cette stratégie sert surtout au mode "burst
rétroactif sur les 5 dernières frames une fois la pièce confirmée"
— le compromis ressemble au comportement actuel sans best-frame, mais
avec sélection qualité.

## RollingFrameBuffer

```kotlin
class RollingFrameBuffer(initialCapacity: Int = 5) {
    @Volatile
    var capacity: Int = initialCapacity
        set(value) {
            require(value in 1..20) { "capacity out of range" }
            field = value
            synchronized(lock) {
                while (buffer.size > value) buffer.removeFirst()
            }
        }

    private val lock = Any()
    private val buffer = ArrayDeque<BufferedFrame>()

    fun push(frame: BufferedFrame) {
        synchronized(lock) {
            buffer.addLast(frame)
            while (buffer.size > capacity) buffer.removeFirst()
        }
    }

    fun snapshot(): List<BufferedFrame> = synchronized(lock) { buffer.toList() }

    fun clear() = synchronized(lock) { buffer.clear() }

    val size: Int get() = synchronized(lock) { buffer.size }
}
```

Sécurité thread : `CoinAnalyzer` tourne sur le thread analyzer
CameraX ; le HUD/ViewModel pourrait lire la snapshot depuis le main
thread. `synchronized` minimal suffit, pas de structure lock-free
sophistiquée.

## BestFrameSelector

```kotlin
class BestFrameSelector {
    fun select(snapshot: List<BufferedFrame>): SelectionResult {
        if (snapshot.isEmpty()) return SelectionResult.Empty

        // 1. Early-stop on first frame passing all gates.
        snapshot.forEachIndexed { idx, frame ->
            if (frame.score.passes.all) {
                return SelectionResult.Best(
                    frame = frame,
                    indexInSnapshot = idx,
                    reason = SelectionReason.PASSED_ALL_GATES,
                )
            }
        }

        // 2. Fallback: best aggregate among all.
        val (idx, frame) = snapshot.withIndex().maxBy { it.value.score.aggregate }
        return SelectionResult.Best(
            frame = frame,
            indexInSnapshot = idx,
            reason = SelectionReason.BEST_AGGREGATE_FALLBACK,
        )
    }
}
```

L'ordre de la snapshot est **chronologique** (oldest first). Donc
`forEachIndexed` traverse du plus ancien au plus récent — la première
frame qui passe les gates est la **plus ancienne** qui pourrait
convenir. Trade-off contre "la plus récente" : la plus récente est
plus représentative de l'instant final, mais la plus ancienne est
souvent plus stable (juste après que l'utilisateur a stabilisé).
Tranchable empiriquement au chunk-7 ; pour l'instant je prends
"oldest passing" car c'est ce qui minimise la latence perçue (on
sélectionne tôt).

## Wiring dans `CoinAnalyzer`

```kotlin
class CoinAnalyzer(
    private val detector: CoinDetector,
    private val normalizer: SnapNormalizer,
    private val scorer: FrameQualityScorer,
    private val recognizer: CoinRecognizer,
    private val matcher: EmbeddingMatcher,
    private val consensus: ConsensusBuffer,
    private val rollingBuffer: RollingFrameBuffer,
    private val triggerStrategyFlow: StateFlow<TriggerStrategy>,
    private val bestFrameSelector: BestFrameSelector,
    private val scoringPolicyFlow: StateFlow<ScoringPolicy>,
    private val hudState: MutableStateFlow<ScanHudState>,
) {
    private var sequenceCounter = 0

    fun analyzeFrame(imageProxy: ImageProxy) {
        // ... detect → normalize → score → arcface → consensus (existing + chunk-2)

        val buffered = BufferedFrame(
            sequenceId = sequenceCounter++,
            timestampNs = elapsedRealtimeNanos(),
            crop = crop,
            score = score,
            detection = primary,
            arcfaceTop3 = matches.take(3),
        )
        rollingBuffer.push(buffered)

        val context = FrameContext(
            sequenceId = buffered.sequenceId,
            buffer = rollingBuffer.snapshot(),
            primaryDetection = primary,
            arcfaceTop1 = matches.firstOrNull(),
            consensusState = consensus.state,
        )

        when (val event = triggerStrategyFlow.value.observe(context)) {
            is TriggerEvent.Fire -> {
                val result = bestFrameSelector.select(event.bufferSnapshot)
                val best = (result as? SelectionResult.Best)
                hudState.update {
                    it.copy(
                        bestFrameIndex = best?.indexInSnapshot,
                        bestFrameScore = best?.frame?.score,
                        machineState = "Fired: ${event.reason} → ${result.reasonShort()}",
                    )
                }
                triggerStrategyFlow.value.reset()
                // Note: pas de side effect production ici (chunks 4-6 prendront le relais)
            }
            TriggerEvent.Abort -> {
                hudState.update { it.copy(machineState = "Aborted") }
                triggerStrategyFlow.value.reset()
            }
            null -> Unit
        }
    }
}
```

### Réactivité aux changements de DebugScanConfig

Dans `ScanViewModel` (debug build) :

```kotlin
val triggerStrategy: StateFlow<TriggerStrategy> = debugConfig
    .map { config ->
        TriggerStrategyFactory.create(config).also {
            it.reset()
        }
    }
    .stateIn(viewModelScope, SharingStarted.Eagerly, NoOpTriggerStrategy())
```

Quand l'utilisateur change `triggerMode` ou un paramètre, une nouvelle
instance est créée (état remis à zéro). Le `rollingBuffer` n'est pas
touché — le buffer continue ses 5 dernières frames, la nouvelle
strategy les voit dès sa première `observe()`. C'est désiré : on peut
tester "ce que ferait BoxStability sur les 5 frames qui viennent de
passer" en flippant le radio sans rescanner.

## HUD — update affichage

Le second row du HUD (déjà préfiguré chunk-1) prend forme :

```
┌─────────────────────────────────────────────────────────────────┐
│ Detecting · sharp 142✓ · exp 0.48✓ · comp 1.00✓ · agg 0.84      │
├─────────────────────────────────────────────────────────────────┤
│ Fired: stable 3f IoU≥0.70 → passed_all_gates · best#3 agg 0.91  │
└─────────────────────────────────────────────────────────────────┘
```

Reste affiché jusqu'au prochain trigger ou jusqu'au reset (passage
Idle). Permet de scroller mentalement les sessions sans avoir à
récupérer les logs.

## Acceptance criteria

**Fonctionnel** :
- [ ] `triggerMode = OFF` : le HUD n'affiche jamais "Fired", le
      pipeline scan est strictement identique à avant.
- [ ] `triggerMode = BOX_STABILITY, IoU=0.7, N=3` : en tenant la
      pièce stable ~1.5 s, le HUD affiche "Fired: stable …".
- [ ] `triggerMode = YOLO_CONFIDENCE, conf=0.50, N=3` : idem dès que
      la conf YOLO se maintient.
- [ ] `triggerMode = ARCFACE_CONSENSUS` : fire dès que le consensus
      sticky est atteint (= en même temps que la fiche s'afficherait
      aujourd'hui).
- [ ] Changer un slider IoU à chaud → la nouvelle strategy est en
      vigueur dans la frame suivante (pas besoin de fermer le sheet
      ni de retoggle).
- [ ] Bouger le slider `Burst size` → le rolling buffer s'ajuste
      (vérifier en lisant `rollingBuffer.size` via le HUD ou un log
      DEBUG).

**Sélection** :
- [ ] Quand au moins une frame du buffer passe tous les gates,
      `BestFrameSelector` retourne `PASSED_ALL_GATES` et pointe vers
      la plus ancienne qualifiée.
- [ ] Quand aucune ne passe, fallback `BEST_AGGREGATE_FALLBACK` sur
      le max aggregate.
- [ ] Buffer vide à la frame n=0 → `Fire` impossible (BoxStability
      requiert N=3, YoloConf idem, Consensus requiert 3/5).

**Perf** :
- [ ] Coût supplémentaire par frame analyzer < 5 ms (le scoring du
      chunk-2 reste le dominant).
- [ ] RAM : pic ≤ 1 MB pour le buffer (5 frames × 224×224×3 +
      métadonnées légères).

**Tests** :
- [ ] Tests unitaires `BoxStabilityTriggerTest` : séquence de bbox
      avec IoU variés, vérifier le comptage et le fire au bon moment.
- [ ] Tests unitaires `YoloConfidenceTriggerTest` : séquence de conf.
- [ ] Tests unitaires `ArcfaceConsensusTriggerTest` : séquence de
      `ConsensusState`.
- [ ] Test `BestFrameSelectorTest` : 4 cas (buffer vide ; tous gates
      passent ; aucun ; mix).
- [ ] Test `RollingFrameBufferTest` : push au-delà de capacity, clear,
      resize.

## Questions ouvertes à trancher pendant l'implem

1. **`firstOrNull { passes.all }` ou `lastOrNull` ?** J'ai pris
   `firstOrNull` (oldest qualifiée = latence minimale). Tunable au
   chunk-7 si bench montre que la plus récente est mieux.
2. **Strategy `BoxStability` sur Hough-only ?** Aujourd'hui ça
   marche : `bbox` est commune YOLO+Hough. Mais `IoU > 0.7` sur des
   bbox Hough peut être plus permissif (Hough donne un cercle, on
   transforme en bbox carrée). À surveiller dans le bench.
3. **`ArcfaceConsensusTrigger` qui re-fire si consensus change** :
   actuellement, oui (par design). Mais ça veut dire que si
   l'utilisateur balaye 3 pièces successives, on fire 3 fois. Ce
   chunk n'a pas de side effect donc OK ; le chunk-6 devra décider
   si la state machine accepte ce comportement.
4. **Lifecycle du `firedForRun` flag** : le trigger est créé via
   factory à chaque change de `DebugScanConfig`, donc nouveau flag à
   chaque change. Mais sans change, le flag reste true après fire →
   trigger silencieux jusqu'à reset externe. Chunk-6 devra appeler
   `reset()` au retour Detecting (post-Accepted).
5. **Buffer thread-safety** : `synchronized` minimal. Si on observe
   de la contention en bench, on passe à `CopyOnWriteArrayList` ou
   un mutex Kotlin coroutines.

## Mémoires & règles liées

- D4 (rolling buffer pré-trigger) — implémenté ici, capacity dynamique.
- D5 (3 stratégies en parallèle) — interface unifiée, instanciation
  factory.
- D6 (pas d'auto-suppression de path) — toutes les strategies restent
  compilées en release. Sélection runtime, jamais code-mort.
- D8 (early-stop sur gates + fallback) — implémenté dans
  `BestFrameSelector`.
- `feedback_no_debt` — pas de fallback silencieux : tout `Fire` produit
  soit un `Best` soit un `Empty` explicite consommé par le HUD.
- `feedback_chunk_audit_flow` — audit attendu : screencast device avec
  les 3 modes successivement, en alternant les paramètres via la
  debug-bar, montrant les fires HUD correspondants.
