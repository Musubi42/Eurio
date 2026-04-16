package com.musubi.eurio.features.coffre.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.PaperSurface1

/**
 * Inline filter panel that expands/collapses below the toolbar.
 * Matches the vault-filters.html concept with M3 chips.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun VaultFilterSheet(
    visible: Boolean,
    availableCountries: List<String>,
    selectedCountries: Set<String>,
    onCountryToggle: (String) -> Unit,
    selectedIssueTypes: Set<String>,
    onIssueTypeToggle: (String) -> Unit,
    selectedFaceValues: Set<Int>,
    onFaceValueToggle: (Int) -> Unit,
    onClear: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AnimatedVisibility(
        visible = visible,
        enter = expandVertically(),
        exit = shrinkVertically(),
        modifier = modifier,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(EurioRadii.lg))
                .background(PaperSurface1)
                .padding(EurioSpacing.s4),
            verticalArrangement = Arrangement.spacedBy(EurioSpacing.s4),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Filtres",
                    style = MaterialTheme.typography.titleMedium,
                    color = Ink,
                )
                TextButton(onClick = onClear) {
                    Text("Réinitialiser", color = Indigo700)
                }
            }

            // Countries
            if (availableCountries.isNotEmpty()) {
                FilterSection(title = "PAYS") {
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                    ) {
                        availableCountries.forEach { country ->
                            FilterChip(
                                label = country.uppercase(),
                                selected = country in selectedCountries,
                                onClick = { onCountryToggle(country) },
                            )
                        }
                    }
                }
            }

            // Issue type
            FilterSection(title = "TYPE") {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                    verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                ) {
                    FilterChip(
                        label = "Circulation",
                        selected = "circulation" in selectedIssueTypes,
                        onClick = { onIssueTypeToggle("circulation") },
                    )
                    FilterChip(
                        label = "Commémorative",
                        selected = "commemo" in selectedIssueTypes,
                        onClick = { onIssueTypeToggle("commemo") },
                    )
                }
            }

            // Face values
            FilterSection(title = "VALEUR FACIALE") {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                    verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                ) {
                    val values = listOf(1, 2, 5, 10, 20, 50, 100, 200)
                    values.forEach { cents ->
                        val label = if (cents >= 100) "${cents / 100}€" else "${cents}c"
                        FilterChip(
                            label = label,
                            selected = cents in selectedFaceValues,
                            onClick = { onFaceValueToggle(cents) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun FilterSection(
    title: String,
    content: @Composable () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2)) {
        Text(
            text = title,
            style = EyebrowStyle,
            color = Ink400,
        )
        content()
    }
}

@Composable
private fun FilterChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(EurioRadii.full)
    Box(
        modifier = Modifier
            .clip(shape)
            .background(if (selected) Indigo700 else PaperSurface)
            .border(
                width = 1.dp,
                color = if (selected) Indigo700 else Ink.copy(alpha = 0.08f),
                shape = shape,
            )
            .clickable { onClick() }
            .padding(horizontal = 10.dp, vertical = 6.dp),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = if (selected) PaperSurface else Ink500,
        )
    }
}
