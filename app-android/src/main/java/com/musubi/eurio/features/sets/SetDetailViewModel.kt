package com.musubi.eurio.features.sets

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.data.repository.SetCoinSlot
import com.musubi.eurio.data.repository.SetRepository
import com.musubi.eurio.data.repository.SetWithProgress
import com.musubi.eurio.data.repository.VaultRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class SetDetailUiState(
    val loading: Boolean = true,
    val set: SetWithProgress? = null,
    val slots: List<SetCoinSlot> = emptyList(),
    val error: String? = null,
)

class SetDetailViewModel(
    private val setId: String,
    private val setRepository: SetRepository,
    private val vaultRepository: VaultRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(SetDetailUiState())
    val state: StateFlow<SetDetailUiState> = _state.asStateFlow()

    init {
        load()
    }

    private fun load() {
        viewModelScope.launch {
            val set = setRepository.getSetDetail(setId)
            if (set == null) {
                _state.value = SetDetailUiState(
                    loading = false,
                    error = "Set introuvable",
                )
                return@launch
            }
            val slots = setRepository.getSetSlots(setId)
            _state.value = SetDetailUiState(
                loading = false,
                set = set,
                slots = slots,
            )
        }
    }

    fun manualAdd(eurioId: String) {
        viewModelScope.launch {
            vaultRepository.addCoin(eurioId, confidence = 0f)
            load() // refresh after adding
        }
    }
}
