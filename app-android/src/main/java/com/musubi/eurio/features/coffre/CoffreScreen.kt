package com.musubi.eurio.features.coffre

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontStyle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.musubi.eurio.features.coffre.components.VaultEmptyState
import com.musubi.eurio.features.coffre.components.VaultFilterSheet
import com.musubi.eurio.features.coffre.components.VaultGrid
import com.musubi.eurio.features.coffre.components.VaultList
import com.musubi.eurio.features.coffre.components.VaultStatsStrip
import com.musubi.eurio.features.coffre.components.VaultToolbar
import com.musubi.eurio.features.catalog.CatalogScreen
import com.musubi.eurio.features.catalog.CatalogViewModel
import com.musubi.eurio.features.sets.SetsListScreen
import com.musubi.eurio.features.sets.SetsListViewModel
import com.musubi.eurio.ui.components.CoffreHeader
import com.musubi.eurio.ui.components.CoffreTab
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.PaperSurface

@Composable
fun CoffreScreen(
    viewModel: CoffreViewModel,
    setsListViewModel: SetsListViewModel,
    catalogViewModel: CatalogViewModel,
    onNavigateToScan: () -> Unit,
    onNavigateToCoinDetail: (String) -> Unit,
    onNavigateToSetDetail: (String) -> Unit,
    onNavigateToCatalogCountry: (String) -> Unit,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val coins by viewModel.vaultCoins.collectAsStateWithLifecycle()
    val totalCount by viewModel.totalCount.collectAsStateWithLifecycle()
    val distinctCount by viewModel.distinctCoinCount.collectAsStateWithLifecycle()
    val availableCountries by viewModel.availableCountries.collectAsStateWithLifecycle()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(PaperSurface)
            .statusBarsPadding(),
    ) {
        // Eyebrow + segmented control
        Column(
            modifier = Modifier.padding(
                start = EurioSpacing.s5,
                end = EurioSpacing.s5,
                top = EurioSpacing.s3,
            ),
        ) {
            Text(
                text = "TON COFFRE",
                style = EyebrowStyle,
                color = Ink400,
            )

            Spacer(Modifier.height(EurioSpacing.s4))

            CoffreHeader(
                selectedTab = uiState.selectedTab,
                onTabSelected = { viewModel.selectTab(it) },
            )
        }

        Spacer(Modifier.height(EurioSpacing.s4))

        when (uiState.selectedTab) {
            CoffreTab.MES_PIECES -> MesPiecesContent(
                viewModel = viewModel,
                uiState = uiState,
                coins = coins,
                totalCount = totalCount,
                distinctCount = distinctCount,
                availableCountries = availableCountries,
                onNavigateToScan = onNavigateToScan,
                onNavigateToCoinDetail = onNavigateToCoinDetail,
            )
            CoffreTab.SETS -> SetsListScreen(
                viewModel = setsListViewModel,
                onSetClick = onNavigateToSetDetail,
            )
            CoffreTab.CATALOGUE -> CatalogScreen(
                viewModel = catalogViewModel,
                onCountryClick = onNavigateToCatalogCountry,
            )
        }
    }
}

@Composable
private fun MesPiecesContent(
    viewModel: CoffreViewModel,
    uiState: CoffreUiState,
    coins: List<com.musubi.eurio.data.repository.VaultCoinItem>,
    totalCount: Int,
    distinctCount: Int,
    availableCountries: List<String>,
    onNavigateToScan: () -> Unit,
    onNavigateToCoinDetail: (String) -> Unit,
) {
    if (totalCount == 0) {
        VaultEmptyState(onScanClick = onNavigateToScan)
        return
    }

    val gridState = rememberLazyGridState()
    val listState = rememberLazyListState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = EurioSpacing.s5),
    ) {
        // Value total (face value sum)
        val totalCents = coins.sumOf { it.coin.faceValueCents * it.count }
        val euros = totalCents / 100
        val cents = totalCents % 100
        Text(
            text = buildString {
                append(euros)
                append("€")
                if (cents > 0) append("%02d".format(cents))
            },
            style = MaterialTheme.typography.displayLarge.copy(
                fontStyle = FontStyle.Italic,
            ),
            color = Ink,
        )

        // Stats strip
        VaultStatsStrip(
            coinCount = totalCount,
            countryCount = availableCountries.size.coerceAtLeast(
                coins.map { it.coin.country }.distinct().size
            ),
        )

        Spacer(Modifier.height(EurioSpacing.s5))

        // Toolbar
        VaultToolbar(
            searchActive = uiState.searchActive,
            searchQuery = uiState.filter.searchQuery,
            onSearchToggle = { viewModel.toggleSearch() },
            onSearchQueryChange = { viewModel.setSearchQuery(it) },
            onFiltersClick = { viewModel.toggleFilters() },
            viewMode = uiState.viewMode,
            onViewModeChange = { viewModel.setViewMode(it) },
            currentSort = uiState.sort,
            onSortChange = { viewModel.setSort(it) },
            hasActiveFilters = viewModel.hasActiveFilters,
        )

        // Filters panel
        VaultFilterSheet(
            visible = uiState.filtersExpanded,
            availableCountries = availableCountries,
            selectedCountries = uiState.filter.countries,
            onCountryToggle = { viewModel.toggleCountryFilter(it) },
            selectedIssueTypes = uiState.filter.issueTypes,
            onIssueTypeToggle = { viewModel.toggleIssueTypeFilter(it) },
            selectedFaceValues = uiState.filter.faceValues,
            onFaceValueToggle = { viewModel.toggleFaceValueFilter(it) },
            onClear = { viewModel.clearFilters() },
        )

        Spacer(Modifier.height(EurioSpacing.s3))

        // Grid or list
        when (uiState.viewMode) {
            ViewMode.GRID -> VaultGrid(
                items = coins,
                sort = uiState.sort,
                gridState = gridState,
                onCoinClick = onNavigateToCoinDetail,
                modifier = Modifier.weight(1f),
            )
            ViewMode.LIST -> VaultList(
                items = coins,
                sort = uiState.sort,
                listState = listState,
                onCoinClick = onNavigateToCoinDetail,
                modifier = Modifier.weight(1f),
            )
        }
    }
}
