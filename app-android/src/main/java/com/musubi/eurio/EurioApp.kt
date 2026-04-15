package com.musubi.eurio

import android.app.Application
import android.util.Log
import com.musubi.eurio.data.local.EurioDatabase
import com.musubi.eurio.data.local.bootstrap.CatalogBootstrapper
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.opencv.android.OpenCVLoader

// État du bootstrap initial. Exposé pour que les écrans qui lisent Room
// au démarrage puissent attendre que les tables catalogue soient peuplées.
enum class BootstrapState { Running, Ready, Failed }

class EurioApp : Application() {
    lateinit var database: EurioDatabase
        private set

    private val _bootstrapState = MutableStateFlow(BootstrapState.Running)
    val bootstrapState: StateFlow<BootstrapState> = _bootstrapState.asStateFlow()

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()

        // OpenCV init (utilisé par la pipeline scan pour HoughCircles).
        if (!OpenCVLoader.initLocal()) {
            Log.e(TAG, "OpenCV init failed")
        } else {
            Log.i(TAG, "OpenCV init OK")
        }

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
    }

    companion object {
        private const val TAG = "EurioApp"
    }
}
