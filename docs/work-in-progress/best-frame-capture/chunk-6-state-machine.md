# Chunk 6 — State machine refonte ScanViewModel

> Formaliser les 6 états (`Idle → Detecting → Locking → Capturing →
> Identifying → Accepted`) avec les transitions explicites, les
> timeouts, les fallbacks, et le découplage `Accepted` (= fiche
> affichée) vs archive en background. Branche tous les chunks
> précédents en une machine unique pilotée par les events.

## Pré-requis

- Chunks 1-5 livrés (DebugBar, scorer, triggers + buffer, lock,
  ImageCapture + archive).

## Goal

À la fin du chunk-6 :

1. Le `ScanViewModel` expose `StateFlow<ScanState>` avec **6 états
   explicites** + transient `Aborted`.
2. Toutes les transitions sont **pures sur events** : pas de polling,
   pas de side-effect dans les transitions, pas de booléens auxiliaires
   qui répliquent un état.
3. La fiche pièce est affichée **uniquement** dans `Accepted` ; les 4
   sub-states intermédiaires (`Locking`, `Capturing`, `Identifying`)
   sont visuellement identiques à `Detecting` côté **release**, mais
   colorés différemment côté **debug overlay** (chunk-4).
4. Tous les **timeouts** sont gérés explicitement : Locking 1.5s,
   Capturing 1.5s, Identifying 3s. Au timeout → retour `Detecting`,
   archive jetée.
5. Le **cooldown post-Accepted** empêche les triggers de fire en
   boucle (D22 + question chunk-3 §3) : les strategies sont reset
   uniquement au retour `Idle`, pas au passage `Accepted → Idle`
   immédiat.

## Scope

**Dans le chunk** :

- `ScanState` sealed class refonte (passage des 3 états actuels aux 6).
- `ScanViewModel` refonte du flux principal : remplace les booléens
  auxiliaires par des transitions sur events typés.
- `ScanEvent` sealed class : tous les inputs externes (consensus,
  trigger, lock, capture, user dismiss, timeouts, lifecycle).
- Reducer pur `ScanReducer.reduce(state, event): ScanState`,
  testable en isolation.
- Wiring : transforme les flows existants (`TriggerStrategy`,
  `LockState`, `ConsensusBuffer`, `ImageCapture` callbacks) en
  `ScanEvent` ; collecte dans le ViewModel.
- Timeouts : un seul `TimeoutScheduler` qui cancel/restart sur
  chaque transition.
- Cooldown logic : `ArcfaceConsensusTrigger.reset()` appelé
  **uniquement** au retour `Idle`, pas au passage transient.
- Update du `ScanScreen` pour observer `ScanState` au lieu des
  flags actuels.

**Hors chunk** :

- Bench tooling + replay (chunk-7).
- Animations UI fiche (déjà existante côté release).

## Architecture — diagramme état

```mermaid
stateDiagram-v2
    [*] --> Idle

    Idle --> Detecting: FirstDetection

    Detecting --> Idle: NoDetection4Frames
    Detecting --> Locking: TriggerFire
    Detecting --> Accepted: ConsensusReached
        note right of Detecting: trigger=OFF path:\nconsensus → direct Accepted

    Locking --> Capturing: LockAcquired
    Locking --> Aborted: LockFailed
    Locking --> Aborted: BboxLost
    Locking --> Accepted: ConsensusReached
        note right of Locking: consensus peut arriver\npendant le lock

    Capturing --> Identifying: CaptureCompleted
    Capturing --> Identifying: CaptureError (fallback YUV)
    Capturing --> Aborted: BboxLost
    Capturing --> Accepted: ConsensusReached

    Identifying --> Accepted: ConsensusReached
    Identifying --> Detecting: NoConsensusTimeout (3s)
    Identifying --> Aborted: UserBacked

    Accepted --> Idle: UserDismiss
    Accepted --> Idle: UserConfirmAdd
    Accepted --> Idle: AutoReturn2sAlreadyOwned
    Accepted --> Accepted: ArchiveCompleted (capture flag flip)

    Aborted --> Detecting: AbortFlashElapsed (200ms)
```

Note D24 : `UserConfirmAdd` déclenche un `SideEffect.ConfirmPossession`
(upsert `coin_in_vault`) puis retourne `Idle`. Cohérent avec
`ScanViewModel.onAddToVault()` actuel : tap = ajout au coffre + retour
à la viewfinder. `UserDismiss` retourne à `Idle` **sans** créer
`coin_in_vault` — la capture éventuellement archivée dans
`coin_captures` reste orpheline (voulu, cf. chunk-5 §Possession).

### Invariants

1. **`Accepted` est l'unique état où la fiche pièce est visible**
   côté release. Les 4 états intermédiaires `Locking`, `Capturing`,
   `Identifying`, `Aborted` sont "scan continue" côté release.
2. **`ConsensusReached`** peut arriver à n'importe quel état entre
   `Detecting` et `Identifying` → bascule immédiate vers `Accepted`.
   Permet de respecter D3 (fiche découplée de l'archive).
3. **Archive complete** ne change jamais l'état principal — c'est
   un `ArchiveCompleted` event qui flip `Accepted.captureArchived`
   et déclenche éventuellement le snackbar (chunk-5).
4. **Cooldown trigger** : `triggerStrategy.reset()` appelé **une seule
   fois** au passage `Idle → Detecting` (= début d'une nouvelle
   séquence de scan), jamais entre temps. Évite les re-fires en
   chaîne sur la même pièce.

## Fichiers à créer

| Fichier | Rôle |
|---|---|
| `domain/scan/ScanEvent.kt` | Sealed class des events typés |
| `domain/scan/ScanReducer.kt` | `reduce(state, event)` pur, testable |
| `domain/scan/ScanState.kt` | **Refonte** de l'existant (passage 3→6 états + Aborted transient) |
| `domain/scan/TimeoutScheduler.kt` | Coordonne les timeouts par état avec un seul Job |
| `domain/scan/ScanReducerTest.kt` | Tests exhaustifs des 30+ transitions |

## Fichiers à modifier

| Fichier | Modification |
|---|---|
| `features/scan/ScanViewModel.kt` | Refonte du flux : collecter les events des sub-systèmes, appliquer reducer, exposer `StateFlow<ScanState>` |
| `features/scan/ScanScreen.kt` | Observer `ScanState` au lieu des flags ; fiche montrée uniquement sur `Accepted` |
| `features/scan/debug/ScanDebugOverlay.kt` | Mapper les 6 états à leurs couleurs (chunk-4 a placeholder, on raffine ici) |
| `features/scan/debug/ScanHud.kt` | Afficher l'état courant + sub-state si applicable |
| `ml/CoinAnalyzer.kt` | Émettre `ScanEvent` au lieu de muter `_hudState` directement |
| `ml/camera/CameraLockController.kt` | Émettre `LockAcquired` / `LockFailed` events |
| `ml/capture/PendingArchiveBuffer.kt` | Émettre `ArchiveCompleted` event |

## ScanState — schéma refondu

```kotlin
sealed class ScanState {
    /** Aucune pièce dans le champ. Caméra continuous, pas de bbox. */
    object Idle : ScanState()

    /** Au moins une bbox détectée mais pas encore stable / pas encore identifiée. */
    object Detecting : ScanState()

    /** Trigger fired, lock caméra en cours. */
    data class Locking(
        val triggerReason: String,
        val sinceNs: Long,
    ) : ScanState()

    /** Lock acquired, ImageCapture en cours. */
    data class Capturing(
        val lockResult: LockResultSnapshot,
        val sinceNs: Long,
    ) : ScanState()

    /** Capture obtenue, en attente du consensus ArcFace pour archiver. */
    data class Identifying(
        val pendingCaptureId: String,
        val sourceMode: SourceMode,                  // IMAGE_CAPTURE_FULL ou YUV_PREVIEW_FALLBACK
        val sinceNs: Long,
    ) : ScanState()

    /** Consensus atteint, fiche visible. Archive en background éventuelle. */
    data class Accepted(
        val eurioId: String,
        val arcfaceTopK: List<ArcfaceMatchSnapshot>,
        val captureArchived: Boolean = false,        // flip on ArchiveCompleted
        val pendingCaptureId: String? = null,        // null si pas de capture en cours
    ) : ScanState()

    /** Transient (200ms) : flash visuel debug avant retour Detecting. */
    data class Aborted(
        val reason: String,
        val previousStateName: String,               // pour logs/debug
    ) : ScanState()
}
```

Note : `LockResultSnapshot` / `ArcfaceMatchSnapshot` / `SourceMode`
sont les mêmes data classes que celles du `CaptureMetadata` du chunk-5
— on les centralise dans `domain/scan/` pour qu'elles soient
sérialisables et réutilisables.

## ScanEvent — schéma

```kotlin
sealed class ScanEvent {
    // --- pipeline events ---
    object FirstDetection : ScanEvent()
    object NoDetectionStreak : ScanEvent()                  // 4 frames consécutives sans bbox
    data class TriggerFire(val reason: String) : ScanEvent()
    object TriggerAbort : ScanEvent()
    data class LockAcquired(val result: LockResultSnapshot) : ScanEvent()
    data class LockFailed(val reason: String) : ScanEvent()
    data class CaptureCompleted(
        val captureId: String,
        val sourceMode: SourceMode,
    ) : ScanEvent()
    data class CaptureError(val cause: String) : ScanEvent()
    data class ConsensusReached(
        val eurioId: String,
        val topK: List<ArcfaceMatchSnapshot>,
    ) : ScanEvent()
    data class ArchiveCompleted(val captureId: String) : ScanEvent()
    data class ArchiveDiscarded(val reason: String) : ScanEvent()

    // --- timeouts ---
    object LockingTimeout : ScanEvent()
    object CapturingTimeout : ScanEvent()
    object IdentifyingTimeout : ScanEvent()
    object AbortFlashElapsed : ScanEvent()

    // --- user events ---
    object UserDismiss : ScanEvent()
    object UserBack : ScanEvent()                            // back gesture pendant scan
    object UserConfirmAdd : ScanEvent()                      // tap « Ajouter au coffre » → confirmPossession (D24)
    object AlreadyOwnedAutoReturn : ScanEvent()              // 2s timer post-Accepted

    // --- lifecycle ---
    object ScreenResumed : ScanEvent()
    object ScreenPaused : ScanEvent()
}
```

## ScanReducer — pseudo-code

```kotlin
object ScanReducer {
    fun reduce(state: ScanState, event: ScanEvent): ReduceResult {
        return when (state) {
            ScanState.Idle -> reduceFromIdle(event)
            ScanState.Detecting -> reduceFromDetecting(event)
            is ScanState.Locking -> reduceFromLocking(state, event)
            is ScanState.Capturing -> reduceFromCapturing(state, event)
            is ScanState.Identifying -> reduceFromIdentifying(state, event)
            is ScanState.Accepted -> reduceFromAccepted(state, event)
            is ScanState.Aborted -> reduceFromAborted(state, event)
        }
    }

    private fun reduceFromIdle(event: ScanEvent): ReduceResult = when (event) {
        ScanEvent.FirstDetection -> transition(
            to = ScanState.Detecting,
            sideEffects = listOf(SideEffect.ResetTrigger, SideEffect.ScheduleNoDetectionWatcher),
        )
        ScanEvent.ScreenPaused -> stay()  // already idle
        else -> stay()  // ignore irrelevant events
    }

    private fun reduceFromDetecting(event: ScanEvent): ReduceResult = when (event) {
        ScanEvent.NoDetectionStreak -> transition(to = ScanState.Idle)
        is ScanEvent.TriggerFire -> transition(
            to = ScanState.Locking(event.reason, now()),
            sideEffects = listOf(SideEffect.StartLock, SideEffect.StartTimeout(LOCKING_TIMEOUT_MS)),
        )
        is ScanEvent.ConsensusReached -> transition(
            to = ScanState.Accepted(event.eurioId, event.topK),
            sideEffects = listOf(SideEffect.ScheduleAlreadyOwnedCheck),
        )
        ScanEvent.ScreenPaused -> transition(to = ScanState.Idle)
        else -> stay()
    }

    private fun reduceFromLocking(state: ScanState.Locking, event: ScanEvent): ReduceResult = when (event) {
        is ScanEvent.LockAcquired -> transition(
            to = ScanState.Capturing(event.result, now()),
            sideEffects = listOf(SideEffect.StartCapture, SideEffect.StartTimeout(CAPTURING_TIMEOUT_MS)),
        )
        is ScanEvent.LockFailed -> transition(
            to = ScanState.Aborted("lock_failed:${event.reason}", "Locking"),
            sideEffects = listOf(SideEffect.ReleaseLock, SideEffect.StartAbortFlashTimer),
        )
        ScanEvent.LockingTimeout -> transition(
            to = ScanState.Aborted("lock_timeout", "Locking"),
            sideEffects = listOf(SideEffect.ReleaseLock, SideEffect.StartAbortFlashTimer),
        )
        ScanEvent.TriggerAbort -> transition(
            to = ScanState.Aborted("bbox_lost", "Locking"),
            sideEffects = listOf(SideEffect.ReleaseLock, SideEffect.StartAbortFlashTimer),
        )
        is ScanEvent.ConsensusReached -> transition(
            // Consensus pendant Locking : on saute en Accepted, le lock se finalise async.
            to = ScanState.Accepted(event.eurioId, event.topK),
            sideEffects = listOf(SideEffect.ScheduleAlreadyOwnedCheck),
        )
        else -> stay()
    }

    // … similar pour Capturing, Identifying, Accepted, Aborted
}

sealed class SideEffect {
    object ResetTrigger : SideEffect()
    object StartLock : SideEffect()
    object StartCapture : SideEffect()
    object ReleaseLock : SideEffect()
    data class StartTimeout(val durationMs: Long) : SideEffect()
    object CancelTimeout : SideEffect()
    object StartAbortFlashTimer : SideEffect()
    object ScheduleNoDetectionWatcher : SideEffect()
    object ScheduleAlreadyOwnedCheck : SideEffect()
    /**
     * Tap user « Ajouter au coffre » dans l'AcceptedCard. Délègue à
     * `VaultCaptureRepository.confirmPossession(eurioId, captureId?)`
     * (cf. chunk-5 D24). Le captureId peut être null en cas d'archive
     * échouée (timeout PendingArchive ou erreur capture) — confirmPossession
     * gère ce cas en créant un `coin_in_vault` sans primary, l'UI fiche
     * coffre fallback sur l'image canonique Numista.
     */
    data class ConfirmPossession(val eurioId: String, val captureId: String?) : SideEffect()
}

data class ReduceResult(
    val nextState: ScanState,
    val sideEffects: List<SideEffect>,
)

private const val LOCKING_TIMEOUT_MS = 1_500L
private const val CAPTURING_TIMEOUT_MS = 1_500L
private const val IDENTIFYING_TIMEOUT_MS = 3_000L
private const val ABORT_FLASH_MS = 200L
```

**Le reducer est pur** : input (state, event) → output (newState,
list<sideEffect>). Aucun side effect appliqué dans le reducer. Le
ViewModel applique les side effects après réception du résultat.
Testable en isolation à 100%.

## ScanViewModel — flux principal

```kotlin
class ScanViewModel(/* deps */) : ViewModel() {

    private val _state = MutableStateFlow<ScanState>(ScanState.Idle)
    val state: StateFlow<ScanState> = _state.asStateFlow()

    private val events = MutableSharedFlow<ScanEvent>(extraBufferCapacity = 16)
    private val timeoutScheduler = TimeoutScheduler(viewModelScope, events::tryEmit)

    init {
        // --- collect pipeline events ---
        viewModelScope.launch {
            coinAnalyzer.scanEvents.collect { events.emit(it) }
        }
        viewModelScope.launch {
            cameraLockController.state.collect { lockState ->
                when (lockState) {
                    is LockState.Locked -> events.emit(ScanEvent.LockAcquired(lockState.toSnapshot()))
                    is LockState.Failed -> events.emit(ScanEvent.LockFailed(lockState.reason))
                    else -> Unit  // Idle/Acquiring/Released don't trigger state changes
                }
            }
        }
        viewModelScope.launch {
            consensusBuffer.state.collect { cs ->
                cs.lockedClass?.let { eurioId ->
                    events.emit(ScanEvent.ConsensusReached(eurioId, cs.topK.toSnapshots()))
                }
            }
        }
        viewModelScope.launch {
            pendingArchiveBuffer.events.collect { events.emit(it) }
        }
        // --- collect user / lifecycle events ---
        // (Composable côté ScanScreen pousse les events via une callback)

        // --- reduce + apply side effects ---
        viewModelScope.launch {
            events.collect { event ->
                val current = _state.value
                val result = ScanReducer.reduce(current, event)
                _state.value = result.nextState
                result.sideEffects.forEach { applySideEffect(it, current, result.nextState) }
            }
        }
    }

    private fun applySideEffect(
        effect: SideEffect,
        previousState: ScanState,
        nextState: ScanState,
    ) {
        when (effect) {
            SideEffect.ResetTrigger -> triggerStrategyFlow.value.reset()
            SideEffect.StartLock -> viewModelScope.launch {
                val region = lastDetectionRegion ?: return@launch
                cameraLockController.lock(LockOptions.fromDebugConfig(debugConfig.value, region))
            }
            SideEffect.ReleaseLock -> viewModelScope.launch {
                cameraLockController.release()
            }
            SideEffect.StartCapture -> imageCapture.takePicture(/* ... */)
            is SideEffect.StartTimeout -> timeoutScheduler.start(nextState, effect.durationMs)
            SideEffect.CancelTimeout -> timeoutScheduler.cancel()
            SideEffect.StartAbortFlashTimer -> timeoutScheduler.scheduleAbortFlashElapsed()
            SideEffect.ScheduleNoDetectionWatcher -> coinAnalyzer.startNoDetectionWatcher()
            SideEffect.ScheduleAlreadyOwnedCheck -> scheduleAlreadyOwnedCheck()
        }
    }
}
```

Le ViewModel ne contient **aucune logique de transition** — c'est
juste le glue entre les flows externes et le reducer pur.

## TimeoutScheduler

```kotlin
class TimeoutScheduler(
    private val scope: CoroutineScope,
    private val emit: (ScanEvent) -> Unit,
) {
    private var job: Job? = null

    fun start(currentState: ScanState, durationMs: Long) {
        cancel()
        val timeoutEvent = currentState.timeoutEvent() ?: return
        job = scope.launch {
            delay(durationMs)
            emit(timeoutEvent)
        }
    }

    fun cancel() {
        job?.cancel()
        job = null
    }

    fun scheduleAbortFlashElapsed() {
        cancel()
        job = scope.launch {
            delay(ABORT_FLASH_MS)
            emit(ScanEvent.AbortFlashElapsed)
        }
    }
}

private fun ScanState.timeoutEvent(): ScanEvent? = when (this) {
    is ScanState.Locking -> ScanEvent.LockingTimeout
    is ScanState.Capturing -> ScanEvent.CapturingTimeout
    is ScanState.Identifying -> ScanEvent.IdentifyingTimeout
    else -> null
}
```

Un seul job de timeout vit à la fois. Cancellé à chaque nouvelle
transition vers un état timeable. Pas de leak.

## UI — différenciation release vs debug

### Release (`!BuildConfig.DEBUG`)

```kotlin
when (val s = state) {
    ScanState.Idle, ScanState.Detecting,
    is ScanState.Locking, is ScanState.Capturing,
    is ScanState.Identifying, is ScanState.Aborted -> {
        // Affichage continuous scan unifié, indistinguable.
        ContinuousScanUi()
    }
    is ScanState.Accepted -> {
        CoinDetailSheet(eurioId = s.eurioId, topK = s.arcfaceTopK)
    }
}
```

L'utilisateur final voit **soit** le scan continu, **soit** la fiche.
Aucune indication des sub-states. Conforme à `feedback_scan_ux`.

### Debug (`BuildConfig.DEBUG`)

```kotlin
when (state) {
    is ScanState.Idle -> ContinuousScanUi()
    is ScanState.Detecting -> ContinuousScanUi()  // overlay DEBUG dessine bbox tertiary
    is ScanState.Locking -> ContinuousScanUi()    // overlay dessine bbox primary + halo pulse
    is ScanState.Capturing -> ContinuousScanUi()  // overlay dessine bbox primary fill
    is ScanState.Identifying -> ContinuousScanUi() // overlay dessine label "Identifying"
    is ScanState.Accepted -> CoinDetailSheet(...)
    is ScanState.Aborted -> ContinuousScanUi()    // overlay flash error
}
```

L'overlay `ScanDebugOverlay` (chunk-4) consomme `state` et choisit
le rendu graphique selon l'état. Mapping détaillé déjà dans le
chunk-4.

## Acceptance criteria

**Pureté du reducer** :
- [ ] `ScanReducer.reduce(state, event)` n'a aucun side effect (pas
      d'I/O, pas de mutation externe, pas de logs).
- [ ] Tests reducer couvrent les 7×N transitions identifiées (N
      events pertinents par state). Coverage 100% des branches.

**Comportement runtime** :
- [ ] `triggerMode = OFF` : la machine ne quitte jamais Detecting
      pour Locking. Le passage à Accepted se fait uniquement sur
      `ConsensusReached`, identique au comportement actuel.
- [ ] `triggerMode = BOX_STABILITY` : séquence complète testable —
      Idle → Detecting → Locking → Capturing → Identifying → Accepted
      observable via état + overlay debug.
- [ ] Timeout Locking 1.5s : pièce tenue immobile mais low-light qui
      empêche AF lock → après 1.5s on retombe Detecting via Aborted
      (flash 200ms).
- [ ] Consensus pendant Locking : on saute directement vers Accepted,
      le lock se release ensuite via le side effect.
- [ ] User Back gesture pendant n'importe quel sub-state non-Idle →
      retour Idle (release lock, cancel capture, discard archive).

**Cooldown trigger** :
- [ ] Après Accepted → Idle, le trigger ne re-fire pas
      immédiatement (jusqu'à FirstDetection sur nouvelle séquence).
- [ ] Une session continuous : Idle → Detecting → Accepted → Idle
      (dismiss) → Detecting → Accepted → Idle → ... fonctionne en
      boucle sans triggers en chaîne sur la même pièce.

**Archive flow** :
- [ ] `ArchiveCompleted` arrive après Accepted → flip
      `Accepted.captureArchived = true`, état reste Accepted, fiche
      reste visible.
- [ ] `ArchiveDiscarded` (timeout PendingArchive 3s) arrive → état
      ne change pas, fiche reste visible, juste log côté HUD debug.

**Pas de régression release** :
- [ ] UX release inchangée par rapport à l'actuel : continuous scan,
      pas de bouton, pas de pop-up, fiche au consensus.
- [ ] Animations existantes (entrée fiche, dismiss) inchangées.

## Questions ouvertes à trancher pendant l'implem

1. **`LOCKING_TIMEOUT_MS = 1500`** : c'est le timeout sur la state
   machine, pas sur le `CameraLockController.lock()` (qui a son
   propre `afTimeoutMs = 800`). Le timeout state-machine est plus
   long pour couvrir le délai jusqu'à `setCaptureRequestOptions`
   appliqué. À benchmarker.
2. **`CAPTURING_TIMEOUT_MS = 1500`** : `ImageCapture.takePicture`
   est typiquement < 500ms mais peut prendre plus en low-light. À
   benchmarker.
3. **`IDENTIFYING_TIMEOUT_MS = 3000`** : aligné avec le timeout du
   `PendingArchiveBuffer` (chunk-5). Si on remonte l'un, on remonte
   l'autre.
4. **`User Back gesture` pendant Capturing** : faut-il essayer de
   sauver la capture déjà prise (ré-injecter dans PendingArchive
   pour qu'elle bénéficie d'un futur consensus dans la prochaine
   session) ? Mon vote : non, on jette. Le user a explicitement
   sorti du flux ; pas de cas où la capture "orpheline" servirait.
5. **Re-fire trigger sur la même pièce** : aujourd'hui, après
   `Accepted → Idle (dismiss)`, l'utilisateur peut re-scanner la
   même pièce immédiatement → consensus → Accepted à nouveau. Le
   trigger est reset à FirstDetection, donc oui ça refonctionne.
   Mais est-ce qu'on veut un cooldown additionnel "pas de re-scan
   de la même eurio_id dans les 5s" ? Mon vote : non, laisser
   l'utilisateur libre.
6. **Suivi de bbox identité** : pendant Locking/Capturing, on
   suppose que c'est toujours la même pièce. Si l'utilisateur
   pivote la pièce et qu'on la perd (bbox_lost) → Aborted. Si il
   substitue une autre pièce subtilement (sans perdre la bbox) →
   le pipeline traite comme la même. C'est un edge case improbable
   (manipulation rapide entre deux pièces sans sortir la première
   du frame). Acceptable v1.

## Mémoires & règles liées

- D2 (state machine 6 états) — implémenté ici.
- D3 (display fiche découplé de l'archivage) — implémenté via
  `ConsensusReached` qui bascule en Accepted indépendamment de
  l'archive ; `ArchiveCompleted` flip un flag mais ne change pas
  l'état.
- D22 (Abort sur perte de stabilité) — implémenté via `TriggerAbort`
  + `Aborted` state.
- Question chunk-3 §3 résolue : cooldown trigger via `ResetTrigger`
  side effect appelé uniquement sur `Idle → Detecting`.
- `feedback_no_debt` — le reducer pur élimine la dette latente des
  "booléens auxiliaires" qui se désynchronisent avec les flags.
- `feedback_scan_ux` — release UX inchangée : continuous scan +
  fiche, rien d'autre.
- `feedback_workflow_check_before_ux` — scénario d'usage validé
  chunk par chunk avant code (la phrase de scénario du `vision.md`
  est respectée par cette machine).
