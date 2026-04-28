package com.musubi.eurio

import android.app.Application
import android.util.Log
import com.musubi.eurio.data.local.EurioDatabase
import com.musubi.eurio.data.local.bootstrap.CatalogBootstrapper
import com.musubi.eurio.data.repository.CoinRepository
import com.musubi.eurio.data.repository.MetaStreakRepository
import com.musubi.eurio.data.repository.RoomCoinRepository
import com.musubi.eurio.data.repository.RoomSetRepository
import com.musubi.eurio.data.repository.CatalogRepository
import com.musubi.eurio.data.repository.ProfileRepository
import com.musubi.eurio.data.repository.RoomCatalogRepository
import com.musubi.eurio.data.repository.RoomProfileRepository
import com.musubi.eurio.data.repository.RoomVaultRepository
import com.musubi.eurio.data.repository.SetRepository
import com.musubi.eurio.data.repository.StreakRepository
import com.musubi.eurio.data.repository.VaultRepository
import com.musubi.eurio.ml.CoinAnalyzer
import com.musubi.eurio.ml.CoinDetector
import com.musubi.eurio.ml.CoinRecognizer
import com.musubi.eurio.ml.EmbeddingMatcher
import com.musubi.eurio.domain.AppEvent
import com.musubi.eurio.features.scan.CaptureProtocol
import com.musubi.eurio.features.scan.ScanState
import com.musubi.eurio.ml.ScanResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import org.opencv.android.OpenCVLoader

// État du bootstrap initial. Exposé pour que les écrans qui lisent Room
// au démarrage puissent attendre que les tables catalogue soient peuplées.
enum class BootstrapState { Running, Ready, Failed }

/**
 * Relay between [CoinAnalyzer] (which binds its onResult callback at
 * construction time) and the [com.musubi.eurio.features.scan.ScanViewModel]
 * that is created later by the navigation layer. The scan destination sets
 * the [delegate] when its VM comes alive and clears it when the composition
 * leaves. If no delegate is bound, the analyzer result is silently dropped —
 * which is the correct behavior for the Coffre/Profil destinations.
 */
class ScanCallbackRelay {
    @Volatile
    var delegate: ((ScanResult) -> Unit)? = null

    fun emit(result: ScanResult) {
        delegate?.invoke(result)
    }
}

class ScanStateRelay {
    private val _pending = MutableStateFlow<ScanState?>(null)
    val pending: StateFlow<ScanState?> = _pending.asStateFlow()

    fun post(state: ScanState) {
        _pending.value = state
    }

    fun consume(): ScanState? {
        val current = _pending.value
        _pending.value = null
        return current
    }
}

class EurioApp : Application() {
    lateinit var database: EurioDatabase
        private set

    private val _bootstrapState = MutableStateFlow(BootstrapState.Running)
    val bootstrapState: StateFlow<BootstrapState> = _bootstrapState.asStateFlow()

    // null = still reading from Room ; false/true = hydrated. MainActivity
    // blocks rendering of the NavHost until this is non-null so the
    // startDestination is chosen based on the persisted flag (no flash
    // of Scan on first run before we know the user hasn't onboarded yet).
    private val _onboardingCompleted = MutableStateFlow<Boolean?>(null)
    val onboardingCompleted: StateFlow<Boolean?> = _onboardingCompleted.asStateFlow()

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    // ─────────────────────────────────────────────────────────────────
    // Repositories — app-scoped singletons, lazy so we don't pay the
    // construction cost on every access.
    // ─────────────────────────────────────────────────────────────────

    val coinRepository: CoinRepository by lazy {
        RoomCoinRepository(database.coinDao())
    }

    val vaultRepository: VaultRepository by lazy {
        RoomVaultRepository(database.vaultDao())
    }

    val streakRepository: StreakRepository by lazy {
        MetaStreakRepository(database.metaDao())
    }

    val setRepository: SetRepository by lazy {
        RoomSetRepository(database.setDao(), database.vaultDao(), database.coinDao())
    }

    val catalogRepository: CatalogRepository by lazy {
        RoomCatalogRepository(database.coinDao(), database.vaultDao())
    }

    val profileRepository: ProfileRepository by lazy {
        RoomProfileRepository(
            database.vaultDao(),
            database.coinDao(),
            database.metaDao(),
            setRepository,
            onAppEvent = ::emitEvent,
        )
    }

    // ─────────────────────────────────────────────────────────────────
    // ML pipeline — constructed once, shared across scan sessions. TFLite
    // model loading is expensive so we don't want it tied to a VM lifetime.
    // ─────────────────────────────────────────────────────────────────

    // App-wide event channel for cross-feature feedback (set completion, badge unlock)
    private val _appEvents = Channel<AppEvent>(Channel.BUFFERED)
    val appEvents = _appEvents.receiveAsFlow()

    fun emitEvent(event: AppEvent) {
        _appEvents.trySend(event)
    }

    val scanCallbackRelay = ScanCallbackRelay()
    val scanStateRelay = ScanStateRelay()

    private val coinRecognizer: CoinRecognizer by lazy {
        CoinRecognizer(applicationContext)
    }

    private val embeddingMatcher: EmbeddingMatcher? by lazy {
        val mode = coinRecognizer.meta.mode
        if (mode == "arcface" || mode == "embed") {
            EmbeddingMatcher(applicationContext)
        } else {
            null
        }
    }

    private val coinDetector: CoinDetector? by lazy {
        runCatching { CoinDetector(applicationContext) }
            .onFailure { Log.w(TAG, "CoinDetector unavailable, falling back to full-frame", it) }
            .getOrNull()
    }

    val coinAnalyzer: CoinAnalyzer by lazy {
        CoinAnalyzer(
            recognizer = coinRecognizer,
            matcher = embeddingMatcher,
            detector = coinDetector,
            onResult = scanCallbackRelay::emit,
        ).apply {
            // Lines up with go-task android:pull-debug (DEBUG_DIR_DEVICE).
            debugRootDir = java.io.File(
                getExternalFilesDir(android.os.Environment.DIRECTORY_DOCUMENTS),
                "eurio_debug",
            ).apply { mkdirs() }
        }
    }

    override fun onCreate() {
        super.onCreate()

        // OpenCV init (utilisé par la pipeline scan pour HoughCircles).
        if (!OpenCVLoader.initLocal()) {
            Log.e(TAG, "OpenCV init failed")
        } else {
            Log.i(TAG, "OpenCV init OK")
        }

        // Load the capture-mode coin list from assets/capture_coins.csv.
        // Synchronous: file is small (<1 KB) and CaptureProtocol is read
        // by the scan VM the moment the user opens the scanner.
        CaptureProtocol.init(this)

        database = EurioDatabase.get(this)

        // Bootstrap catalogue au premier run / sur mise à jour d'APK.
        // Non-bloquant : l'UI peut afficher un état de chargement en
        // observant bootstrapState.
        appScope.launch {
            runCatching {
                CatalogBootstrapper(this@EurioApp, database).runIfNeeded()
            }.onSuccess {
                _bootstrapState.value = BootstrapState.Ready
            }.onFailure { t ->
                Log.e(TAG, "Bootstrap catalogue échoué", t)
                _bootstrapState.value = BootstrapState.Failed
            }
        }

        // Hydrate the in-memory streak cache from Room so the top bar badge
        // renders the correct value on first composition.
        appScope.launch {
            runCatching { streakRepository.initializeFromDb() }
                .onFailure { Log.w(TAG, "Streak init failed", it) }
        }

        // Hydrate the onboarding flag — decides startDestination of NavHost.
        appScope.launch {
            val completed = runCatching {
                database.metaDao().getBoolean(KEY_ONBOARDING_COMPLETED) ?: false
            }.getOrDefault(false)
            _onboardingCompleted.value = completed
        }
    }

    suspend fun markOnboardingCompleted() {
        database.metaDao().putBoolean(KEY_ONBOARDING_COMPLETED, true)
        _onboardingCompleted.value = true
    }

    companion object {
        private const val TAG = "EurioApp"
        const val KEY_ONBOARDING_COMPLETED = "onboarding_completed"
    }
}
