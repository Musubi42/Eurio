package com.musubi.eurio.features.dev.carousel

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.data.repository.CoinRepository
import com.musubi.eurio.data.repository.CoinViewData
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * ViewModel pour /dev/carousel — 3D coin viewer cyclant à travers toutes les
 * pièces 2 €. Pas de caméra, pas d'analyzer. L'écran est purement visuel et
 * sert à inspecter le rendu Coin3DViewer + le tuning PBR.
 */
class CarouselViewModel(
    private val coinRepository: CoinRepository,
) : ViewModel() {

    companion object {
        private const val TAG = "CarouselVM"
    }

    private val _current = MutableStateFlow<CoinViewData?>(null)
    val current: StateFlow<CoinViewData?> = _current.asStateFlow()

    private var coins: List<CoinViewData> = emptyList()
    private var index: Int = 0

    fun enter() {
        viewModelScope.launch {
            if (coins.isEmpty()) {
                coins = coinRepository.findAllByFaceValue(2.0)
                Log.d(TAG, "carousel loaded ${coins.size} 2€ coins")
            }
            if (coins.isNotEmpty()) {
                index = 0
                _current.value = coins[0]
            }
        }
    }

    fun onNext() = step(+1)
    fun onPrev() = step(-1)

    private fun step(delta: Int) {
        if (coins.isEmpty()) return
        index = ((index + delta) % coins.size + coins.size) % coins.size
        Log.d(TAG, "carousel step delta=$delta → index=$index/${coins.size} ${coins[index].eurioId}")
        _current.value = coins[index]
    }
}
