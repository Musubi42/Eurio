package com.musubi.eurio.features.coffre

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.data.repository.VaultCoinItem
import com.musubi.eurio.data.repository.VaultFilter
import com.musubi.eurio.data.repository.VaultRepository
import com.musubi.eurio.data.repository.VaultSort
import com.musubi.eurio.ui.components.CoffreTab
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update

enum class ViewMode { GRID, LIST }

data class CoffreUiState(
    val selectedTab: CoffreTab = CoffreTab.MES_PIECES,
    val viewMode: ViewMode = ViewMode.GRID,
    val sort: VaultSort = VaultSort.COUNTRY,
    val filter: VaultFilter = VaultFilter(),
    val searchActive: Boolean = false,
    val filtersExpanded: Boolean = false,
)

class CoffreViewModel(
    private val vaultRepository: VaultRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(CoffreUiState())
    val uiState: StateFlow<CoffreUiState> = _uiState.asStateFlow()

    private val _searchQuery = MutableStateFlow("")

    val totalCount: StateFlow<Int> = vaultRepository.observeTotalCount()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)

    val distinctCoinCount: StateFlow<Int> = vaultRepository.observeDistinctCoinCount()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)

    val availableCountries: StateFlow<List<String>> = vaultRepository.observeAvailableCountries()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    @OptIn(FlowPreview::class, ExperimentalCoroutinesApi::class)
    val vaultCoins: StateFlow<List<VaultCoinItem>> = combine(
        _uiState,
        _searchQuery.debounce(300),
    ) { state, query ->
        state.filter.copy(searchQuery = query) to state.sort
    }.flatMapLatest { (filter, sort) ->
        vaultRepository.observeVaultCoins(filter, sort)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun selectTab(tab: CoffreTab) {
        _uiState.update { it.copy(selectedTab = tab) }
    }

    fun setViewMode(mode: ViewMode) {
        _uiState.update { it.copy(viewMode = mode) }
    }

    fun setSort(sort: VaultSort) {
        _uiState.update { it.copy(sort = sort) }
    }

    fun setSearchQuery(query: String) {
        _searchQuery.value = query
    }

    fun toggleSearch() {
        _uiState.update {
            val newActive = !it.searchActive
            if (!newActive) _searchQuery.value = ""
            it.copy(searchActive = newActive)
        }
    }

    fun toggleFilters() {
        _uiState.update { it.copy(filtersExpanded = !it.filtersExpanded) }
    }

    fun toggleCountryFilter(country: String) {
        _uiState.update { state ->
            val current = state.filter.countries
            val updated = if (country in current) current - country else current + country
            state.copy(filter = state.filter.copy(countries = updated))
        }
    }

    fun toggleIssueTypeFilter(type: String) {
        _uiState.update { state ->
            val current = state.filter.issueTypes
            val updated = if (type in current) current - type else current + type
            state.copy(filter = state.filter.copy(issueTypes = updated))
        }
    }

    fun toggleFaceValueFilter(cents: Int) {
        _uiState.update { state ->
            val current = state.filter.faceValues
            val updated = if (cents in current) current - cents else current + cents
            state.copy(filter = state.filter.copy(faceValues = updated))
        }
    }

    fun clearFilters() {
        _uiState.update { it.copy(filter = VaultFilter(), filtersExpanded = false) }
        _searchQuery.value = ""
    }

    val hasActiveFilters: Boolean
        get() {
            val f = _uiState.value.filter
            return f.countries.isNotEmpty() || f.issueTypes.isNotEmpty() ||
                f.faceValues.isNotEmpty() || f.yearRange != null
        }
}
