package com.musubi.eurio.features.coindetail

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.data.repository.CoinRepository
import com.musubi.eurio.data.repository.CoinViewData
import com.musubi.eurio.data.repository.SetRepository
import com.musubi.eurio.data.repository.SetWithProgress
import com.musubi.eurio.data.repository.VaultRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class CoinDetailUiState(
    val loading: Boolean = true,
    val coin: CoinViewData? = null,
    val alreadyOwned: Boolean = false,
    val scannedAt: Long? = null,
    val sets: List<SetWithProgress> = emptyList(),
    val error: String? = null,
    val showRemoveDialog: Boolean = false,
    val entryId: Long? = null,
)

class CoinDetailViewModel(
    private val eurioId: String,
    private val coinRepository: CoinRepository,
    private val vaultRepository: VaultRepository,
    private val setRepository: SetRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(CoinDetailUiState())
    val state: StateFlow<CoinDetailUiState> = _state.asStateFlow()

    init {
        load()
    }

    private fun load() {
        viewModelScope.launch {
            val coin = coinRepository.findByEurioId(eurioId)
            if (coin == null) {
                _state.value = CoinDetailUiState(
                    loading = false,
                    error = "Pièce introuvable",
                )
                return@launch
            }
            val owned = vaultRepository.containsCoin(eurioId)
            val sets = setRepository.findSetsContaining(eurioId)
            _state.value = CoinDetailUiState(
                loading = false,
                coin = coin,
                alreadyOwned = owned,
                sets = sets,
            )
        }
    }

    fun onAddToVault() {
        val coin = _state.value.coin ?: return
        if (_state.value.alreadyOwned) return
        viewModelScope.launch {
            vaultRepository.addCoin(coin.eurioId, confidence = 1f)
            _state.value = _state.value.copy(alreadyOwned = true)
        }
    }

    fun showRemoveDialog() {
        _state.value = _state.value.copy(showRemoveDialog = true)
    }

    fun dismissRemoveDialog() {
        _state.value = _state.value.copy(showRemoveDialog = false)
    }

    fun confirmRemove() {
        val entryId = _state.value.entryId
        viewModelScope.launch {
            if (entryId != null) {
                vaultRepository.removeEntry(entryId)
            }
            _state.value = _state.value.copy(
                alreadyOwned = false,
                showRemoveDialog = false,
                entryId = null,
            )
        }
    }
}
