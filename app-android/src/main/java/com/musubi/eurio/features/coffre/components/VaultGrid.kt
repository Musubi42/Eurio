package com.musubi.eurio.features.coffre.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.musubi.eurio.data.repository.VaultCoinItem
import com.musubi.eurio.data.repository.VaultSort
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.PaperSurface1
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Grid display of vault coins (3 columns), with monthly group headers when
 * sorted by scan date. Matches vault-home.html .vault-home-grid pattern.
 */
@Composable
fun VaultGrid(
    items: List<VaultCoinItem>,
    sort: VaultSort,
    gridState: LazyGridState,
    onCoinClick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val grouped = buildGroupedItems(items, sort)

    LazyVerticalGrid(
        columns = GridCells.Fixed(3),
        state = gridState,
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        for (group in grouped) {
            if (group.label != null) {
                item(
                    key = "header_${group.label}",
                    span = { GridItemSpan(3) },
                ) {
                    GroupHeader(label = group.label)
                }
            }
            items(
                items = group.coins,
                key = { "tile_${it.coin.eurioId}" },
            ) { item ->
                CoinTile(
                    item = item,
                    onClick = { onCoinClick(item.coin.eurioId) },
                )
            }
        }
    }
}

@Composable
private fun GroupHeader(label: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = EurioSpacing.s5, bottom = EurioSpacing.s3),
    ) {
        Column {
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium.copy(fontStyle = FontStyle.Italic),
                color = Ink500,
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = EurioSpacing.s2)
                    .background(Gold.copy(alpha = 0.35f))
                    .size(height = 1.dp, width = 0.dp),
            )
        }
    }
}

@Composable
private fun CoinTile(
    item: VaultCoinItem,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(EurioRadii.md)
    Box(
        modifier = Modifier
            .aspectRatio(1f / 1.05f)
            .clip(shape)
            .background(PaperSurface1)
            .border(1.dp, Ink.copy(alpha = 0.04f), shape)
            .clickable { onClick() }
            .padding(EurioSpacing.s2),
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            // Coin image
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                val coinShape = CircleShape
                if (item.coin.imageObverseUrl != null) {
                    AsyncImage(
                        model = item.coin.imageObverseUrl,
                        contentDescription = item.coin.nameFr,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .size(78.dp)
                            .clip(coinShape)
                            .background(PaperSurface1)
                            .border(1.dp, Gold.copy(alpha = 0.3f), coinShape),
                    )
                } else {
                    Box(
                        modifier = Modifier
                            .size(78.dp)
                            .clip(coinShape)
                            .background(Gold.copy(alpha = 0.15f))
                            .border(1.dp, Gold.copy(alpha = 0.3f), coinShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = formatFaceValue(item.coin.faceValueCents),
                            style = MaterialTheme.typography.headlineMedium.copy(
                                fontStyle = FontStyle.Italic,
                            ),
                            color = GoldDeep,
                        )
                    }
                }
            }

            // Meta: country + year
            Box(
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = item.coin.country.uppercase(),
                    style = EyebrowStyle,
                    color = Ink500,
                    modifier = Modifier.align(Alignment.CenterStart),
                )
                Text(
                    text = if (item.coin.year > 0) item.coin.year.toString() else "",
                    style = EyebrowStyle,
                    color = Ink500,
                    modifier = Modifier.align(Alignment.CenterEnd),
                )
            }
        }

        // Multiplicity badge
        if (item.count > 1) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .clip(RoundedCornerShape(EurioRadii.full))
                    .background(Indigo700)
                    .padding(horizontal = 6.dp, vertical = 2.dp),
            ) {
                Text(
                    text = "×${item.count}",
                    style = MonoBadgeStyle,
                    color = PaperSurface,
                )
            }
        }
    }
}

private fun formatFaceValue(cents: Int): String = when {
    cents <= 0 -> "—"
    cents < 100 -> "${cents}c"
    cents % 100 == 0 -> "${cents / 100}€"
    else -> "%.2f€".format(cents / 100.0)
}

// Grouping logic

data class CoinGroup(
    val label: String?,
    val coins: List<VaultCoinItem>,
)

fun buildGroupedItems(items: List<VaultCoinItem>, sort: VaultSort): List<CoinGroup> {
    if (items.isEmpty()) return emptyList()

    return when (sort) {
        VaultSort.COUNTRY -> {
            items.groupBy { it.coin.country }
                .toSortedMap()
                .map { (country, coins) -> CoinGroup(label = country, coins = coins) }
        }
        VaultSort.FACE_VALUE -> {
            items.groupBy { it.coin.faceValueCents }
                .toSortedMap(compareByDescending { it })
                .map { (cents, coins) -> CoinGroup(label = formatFaceValue(cents), coins = coins) }
        }
        VaultSort.SCAN_DATE -> {
            val fmt = SimpleDateFormat("MMMM yyyy", Locale.FRENCH)
            items.groupBy { fmt.format(Date(it.scannedAt)) }
                .map { (month, coins) ->
                    CoinGroup(
                        label = month.replaceFirstChar { it.titlecase(Locale.FRENCH) },
                        coins = coins,
                    )
                }
        }
        VaultSort.YEAR -> {
            items.groupBy { it.coin.year }
                .toSortedMap(compareByDescending { it })
                .map { (year, coins) ->
                    CoinGroup(
                        label = if (year != null && year > 0) year.toString() else "Année inconnue",
                        coins = coins,
                    )
                }
        }
    }
}
