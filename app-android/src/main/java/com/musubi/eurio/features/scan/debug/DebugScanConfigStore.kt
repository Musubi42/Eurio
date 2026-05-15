package com.musubi.eurio.features.scan.debug

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Single mutable source of [DebugScanConfig] across the debug build. Resets to
 * [DebugScanConfig] defaults on every cold start — these knobs are exploratory,
 * not user preferences, so no DataStore.
 *
 * Mutation surface is intentionally narrow: only [DebugBar] (read-write) and
 * [com.musubi.eurio.features.scan.ScanViewModel] (read-only) touch this.
 */
object DebugScanConfigStore {
    private val _config = MutableStateFlow(DebugScanConfig())
    val config: StateFlow<DebugScanConfig> = _config.asStateFlow()

    fun update(transform: (DebugScanConfig) -> DebugScanConfig) {
        _config.value = transform(_config.value)
    }

    fun reset() {
        _config.value = DebugScanConfig()
    }
}
