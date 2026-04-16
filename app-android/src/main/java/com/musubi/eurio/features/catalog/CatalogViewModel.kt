package com.musubi.eurio.features.catalog

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.data.repository.CatalogRepository
import com.musubi.eurio.data.repository.CountryProgress
import com.musubi.eurio.data.repository.RoomCatalogRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn

enum class CatalogMode { MAP, LIST }

data class CatalogUiState(
    val mode: CatalogMode = CatalogMode.MAP,
    val selectedCountry: String? = null,
)

class CatalogViewModel(
    catalogRepository: CatalogRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(CatalogUiState())
    val uiState: StateFlow<CatalogUiState> = _uiState.asStateFlow()

    val countryProgress: StateFlow<List<CountryProgress>> =
        catalogRepository.observeCountryProgress()
            .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun setMode(mode: CatalogMode) {
        _uiState.value = _uiState.value.copy(mode = mode)
    }

    fun selectCountry(iso: String?) {
        _uiState.value = _uiState.value.copy(selectedCountry = iso)
    }
}
