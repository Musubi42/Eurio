package com.musubi.eurio.features.coffre.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.unit.dp
import com.musubi.eurio.data.repository.VaultSort
import com.musubi.eurio.features.coffre.ViewMode
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.PaperSurface1

/**
 * Vault toolbar: search bar, filters button, view toggle, sort chips.
 * Matches vault-home.html .vault-home-toolbar.
 */
@Composable
fun VaultToolbar(
    searchActive: Boolean,
    searchQuery: String,
    onSearchToggle: () -> Unit,
    onSearchQueryChange: (String) -> Unit,
    onFiltersClick: () -> Unit,
    viewMode: ViewMode,
    onViewModeChange: (ViewMode) -> Unit,
    currentSort: VaultSort,
    onSortChange: (VaultSort) -> Unit,
    hasActiveFilters: Boolean,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        // Search bar
        if (searchActive) {
            SearchField(
                query = searchQuery,
                onQueryChange = onSearchQueryChange,
                onClose = onSearchToggle,
            )
        } else {
            SearchButton(onClick = onSearchToggle)
        }

        // Filters + view toggle row
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            FiltersButton(
                onClick = onFiltersClick,
                hasActive = hasActiveFilters,
            )
            ViewToggle(
                current = viewMode,
                onChange = onViewModeChange,
            )
        }

        // Sort chips
        SortChipRow(
            current = currentSort,
            onChange = onSortChange,
        )
    }
}

@Composable
private fun SearchButton(onClick: () -> Unit) {
    val shape = RoundedCornerShape(EurioRadii.full)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(PaperSurface1)
            .border(1.dp, Ink.copy(alpha = 0.06f), shape)
            .clickable { onClick() }
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        Icon(
            imageVector = Icons.Default.Search,
            contentDescription = null,
            tint = Ink400,
            modifier = Modifier.size(16.dp),
        )
        Text(
            text = "Chercher dans ton coffre",
            style = MaterialTheme.typography.bodyMedium,
            color = Ink400,
        )
    }
}

@Composable
private fun SearchField(
    query: String,
    onQueryChange: (String) -> Unit,
    onClose: () -> Unit,
) {
    val shape = RoundedCornerShape(EurioRadii.full)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(PaperSurface1)
            .border(1.dp, Indigo700.copy(alpha = 0.3f), shape)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Default.Search,
            contentDescription = null,
            tint = Ink400,
            modifier = Modifier.size(16.dp),
        )
        Spacer(Modifier.width(EurioSpacing.s2))
        BasicTextField(
            value = query,
            onValueChange = onQueryChange,
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyMedium.copy(color = Ink),
            cursorBrush = SolidColor(Indigo700),
            modifier = Modifier.weight(1f),
            decorationBox = { inner ->
                Box {
                    if (query.isEmpty()) {
                        Text(
                            text = "Chercher…",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Ink400,
                        )
                    }
                    inner()
                }
            },
        )
        if (query.isNotEmpty()) {
            Icon(
                imageVector = Icons.Default.Close,
                contentDescription = "Effacer",
                tint = Ink500,
                modifier = Modifier
                    .size(18.dp)
                    .clickable { onQueryChange("") },
            )
        }
    }
}

@Composable
private fun FiltersButton(
    onClick: () -> Unit,
    hasActive: Boolean,
) {
    val shape = RoundedCornerShape(EurioRadii.full)
    Row(
        modifier = Modifier
            .clip(shape)
            .background(Indigo700)
            .clickable { onClick() }
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            text = if (hasActive) "Filtres ●" else "Filtres",
            style = MaterialTheme.typography.bodySmall.copy(
                fontWeight = androidx.compose.ui.text.font.FontWeight.Medium,
            ),
            color = PaperSurface,
        )
    }
}

@Composable
private fun ViewToggle(
    current: ViewMode,
    onChange: (ViewMode) -> Unit,
) {
    val containerShape = RoundedCornerShape(EurioRadii.full)
    Row(
        modifier = Modifier
            .clip(containerShape)
            .background(PaperSurface1)
            .border(1.dp, Ink.copy(alpha = 0.06f), containerShape)
            .padding(3.dp),
    ) {
        ToggleButton(
            label = "▦",
            selected = current == ViewMode.GRID,
            onClick = { onChange(ViewMode.GRID) },
        )
        ToggleButton(
            label = "☰",
            selected = current == ViewMode.LIST,
            onClick = { onChange(ViewMode.LIST) },
        )
    }
}

@Composable
private fun ToggleButton(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(EurioRadii.full)
    Box(
        modifier = Modifier
            .then(if (selected) Modifier.shadow(1.dp, shape) else Modifier)
            .clip(shape)
            .background(if (selected) PaperSurface else PaperSurface1)
            .clickable { onClick() }
            .size(width = 34.dp, height = 28.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            color = if (selected) Indigo700 else Ink400,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun SortChipRow(
    current: VaultSort,
    onChange: (VaultSort) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        Text(
            text = "TRIER",
            style = EyebrowStyle,
            color = Ink400,
            modifier = Modifier.padding(end = EurioSpacing.s1),
        )
        SortChip("Pays", VaultSort.COUNTRY, current, onChange)
        SortChip("Valeur faciale", VaultSort.FACE_VALUE, current, onChange)
        SortChip("Date d'ajout", VaultSort.SCAN_DATE, current, onChange)
    }
}

@Composable
private fun SortChip(
    label: String,
    sort: VaultSort,
    current: VaultSort,
    onChange: (VaultSort) -> Unit,
) {
    val selected = sort == current
    val shape = RoundedCornerShape(EurioRadii.full)
    Box(
        modifier = Modifier
            .clip(shape)
            .background(if (selected) Ink else PaperSurface1)
            .border(
                width = 1.dp,
                color = if (selected) Ink else Ink.copy(alpha = 0.06f),
                shape = shape,
            )
            .clickable { onChange(sort) }
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall.copy(
                fontWeight = androidx.compose.ui.text.font.FontWeight.Medium,
            ),
            color = if (selected) Gold else Ink500,
        )
    }
}
