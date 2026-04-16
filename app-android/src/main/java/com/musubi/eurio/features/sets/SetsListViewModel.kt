package com.musubi.eurio.features.sets

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.data.repository.SetRepository
import com.musubi.eurio.data.repository.SetWithProgress
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update

enum class SetsStateFilter { ALL, IN_PROGRESS, COMPLETED, NOT_STARTED }

data class SetsListUiState(
    val categoryFilter: String? = null,
    val stateFilter: SetsStateFilter = SetsStateFilter.ALL,
)

class SetsListViewModel(
    setRepository: SetRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SetsListUiState())
    val uiState: StateFlow<SetsListUiState> = _uiState.asStateFlow()

    private val allSets = setRepository.observeAllWithProgress()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val filteredSets: StateFlow<List<SetWithProgress>> = combine(
        allSets,
        _uiState,
    ) { sets, state ->
        var filtered = sets
        if (state.categoryFilter != null) {
            filtered = filtered.filter { it.category == state.categoryFilter }
        }
        filtered = when (state.stateFilter) {
            SetsStateFilter.ALL -> filtered
            SetsStateFilter.IN_PROGRESS -> filtered.filter { it.owned > 0 && !it.isComplete }
            SetsStateFilter.COMPLETED -> filtered.filter { it.isComplete }
            SetsStateFilter.NOT_STARTED -> filtered.filter { it.owned == 0 }
        }
        // Sort: in-progress by % desc, then not started, then completed
        filtered.sortedWith(
            compareBy<SetWithProgress> {
                when {
                    it.owned > 0 && !it.isComplete -> 0
                    it.owned == 0 -> 1
                    else -> 2
                }
            }.thenByDescending { it.percent }
                .thenBy { it.displayOrder }
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val stats: StateFlow<SetsStats> = allSets.combine(_uiState) { sets, _ ->
        SetsStats(
            total = sets.size,
            completed = sets.count { it.isComplete },
            totalCoins = sets.sumOf { it.owned },
            totalTarget = sets.sumOf { it.total },
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), SetsStats())

    fun setCategoryFilter(category: String?) {
        _uiState.update { it.copy(categoryFilter = category) }
    }

    fun setStateFilter(filter: SetsStateFilter) {
        _uiState.update { it.copy(stateFilter = filter) }
    }
}

data class SetsStats(
    val total: Int = 0,
    val completed: Int = 0,
    val totalCoins: Int = 0,
    val totalTarget: Int = 0,
)
