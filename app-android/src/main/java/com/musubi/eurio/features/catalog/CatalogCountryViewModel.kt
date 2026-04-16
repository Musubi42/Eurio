package com.musubi.eurio.features.catalog

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.data.repository.CatalogRepository
import com.musubi.eurio.data.repository.CoinWithOwnership
import com.musubi.eurio.data.repository.VaultRepository
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class CatalogCountryViewModel(
    private val countryCode: String,
    private val catalogRepository: CatalogRepository,
    private val vaultRepository: VaultRepository,
) : ViewModel() {

    private val _typeFilter = MutableStateFlow<String?>(null)
    val typeFilter: StateFlow<String?> = _typeFilter.asStateFlow()

    @OptIn(ExperimentalCoroutinesApi::class)
    val coins: StateFlow<List<CoinWithOwnership>> = _typeFilter
        .flatMapLatest { filter ->
            catalogRepository.observeCoinsForCountry(countryCode, filter)
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun setTypeFilter(filter: String?) {
        _typeFilter.value = filter
    }

    fun manualAdd(eurioId: String) {
        viewModelScope.launch {
            vaultRepository.addCoin(eurioId, confidence = 0f)
        }
    }
}
