package com.musubi.eurio.features.catalog

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import com.musubi.eurio.data.repository.CoinWithOwnership
import com.musubi.eurio.data.repository.RoomCatalogRepository
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.Gray100
import com.musubi.eurio.ui.theme.Gray200
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.PaperSurface1

/**
 * Country drill-down screen matching vault-catalog-country.html.
 * Shows a 3-column planche of all coins for the country.
 */
@Composable
fun CatalogCountryScreen(
    countryCode: String,
    viewModel: CatalogCountryViewModel,
    onBack: () -> Unit,
    onCoinClick: (String) -> Unit,
) {
    val coins by viewModel.coins.collectAsStateWithLifecycle()
    val typeFilter by viewModel.typeFilter.collectAsStateWithLifecycle()

    val name = RoomCatalogRepository.countryName(countryCode)
    val flag = RoomCatalogRepository.countryFlag(countryCode)
    val owned = coins.count { it.owned }
    val total = coins.size
    val percent = if (total > 0) (owned.toFloat() / total * 100).toInt() else 0

    LazyVerticalGrid(
        columns = GridCells.Fixed(3),
        modifier = Modifier
            .fillMaxSize()
            .background(PaperSurface)
            .statusBarsPadding(),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        // Back button
        item(span = { GridItemSpan(3) }) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s3),
            ) {
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(EurioRadii.full))
                        .clickable { onBack() }
                        .padding(vertical = 8.dp, horizontal = 2.dp),
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text("←", style = MaterialTheme.typography.titleMedium, color = Ink500)
                        Text("RETOUR", style = MonoBadgeStyle, color = Ink500)
                    }
                }
            }
        }

        // Hero header
        item(span = { GridItemSpan(3) }) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = EurioSpacing.s5),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // Flag circle
                Box(
                    modifier = Modifier
                        .size(56.dp)
                        .clip(CircleShape)
                        .background(PaperSurface1),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(text = flag, fontSize = 32.sp)
                }

                Spacer(Modifier.height(EurioSpacing.s3))

                Text(
                    text = name,
                    style = MaterialTheme.typography.displaySmall.copy(fontStyle = FontStyle.Italic),
                    color = Ink,
                    textAlign = TextAlign.Center,
                )

                Spacer(Modifier.height(EurioSpacing.s2))

                Text(
                    text = "$owned / $total possédées",
                    style = MonoBadgeStyle,
                    color = Ink400,
                )

                Spacer(Modifier.height(EurioSpacing.s3))

                LinearProgressIndicator(
                    progress = { if (total > 0) owned.toFloat() / total else 0f },
                    modifier = Modifier
                        .fillMaxWidth(0.6f)
                        .height(4.dp)
                        .clip(RoundedCornerShape(2.dp)),
                    color = Gold,
                    trackColor = Gray100,
                    strokeCap = StrokeCap.Round,
                )

                Spacer(Modifier.height(EurioSpacing.s5))
            }
        }

        // Type filter
        item(span = { GridItemSpan(3) }) {
            TypeFilterRow(
                current = typeFilter,
                onChange = { viewModel.setTypeFilter(it) },
            )
        }

        // Section header
        item(span = { GridItemSpan(3) }) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s3),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = "Pièces",
                    style = MaterialTheme.typography.headlineMedium.copy(fontStyle = FontStyle.Italic),
                    color = Ink,
                )
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(EurioRadii.full))
                        .background(Ink.copy(alpha = 0.08f))
                        .padding(horizontal = 8.dp, vertical = 2.dp),
                ) {
                    Text(
                        text = "$total",
                        style = MonoBadgeStyle,
                        color = Ink500,
                    )
                }
            }
        }

        // Planche grid
        items(
            items = coins,
            key = { "cat_${it.eurioId}" },
        ) { coin ->
            CountryCoinSlot(
                coin = coin,
                onClick = { onCoinClick(coin.eurioId) },
                onManualAdd = { viewModel.manualAdd(coin.eurioId) },
            )
        }

        // Bottom spacer
        item(span = { GridItemSpan(3) }) {
            Spacer(Modifier.height(EurioSpacing.s10))
        }
    }
}

@Composable
private fun TypeFilterRow(
    current: String?,
    onChange: (String?) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s2),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        FilterBtn("Tout", current == null) { onChange(null) }
        FilterBtn("Circulation", current == "circulation") { onChange("circulation") }
        FilterBtn("Commémos", current == "commemo") { onChange("commemo") }
    }
}

@Composable
private fun FilterBtn(label: String, selected: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(EurioRadii.full)
    Box(
        modifier = Modifier
            .clip(shape)
            .background(if (selected) Ink else PaperSurface1)
            .border(1.dp, if (selected) Ink else Ink.copy(alpha = 0.06f), shape)
            .clickable { onClick() }
            .padding(horizontal = 14.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall.copy(
                fontWeight = FontWeight.Medium,
            ),
            color = if (selected) Gold else Ink500,
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun CountryCoinSlot(
    coin: CoinWithOwnership,
    onClick: () -> Unit,
    onManualAdd: () -> Unit,
) {
    var showDialog by remember { mutableStateOf(false) }

    val shape = RoundedCornerShape(EurioRadii.md)
    Box(
        modifier = Modifier
            .padding(horizontal = EurioSpacing.s1)
            .aspectRatio(1f)
            .clip(shape)
            .background(PaperSurface1)
            .combinedClickable(
                onClick = onClick,
                onLongClick = {
                    if (!coin.owned) showDialog = true
                },
            ),
        contentAlignment = Alignment.Center,
    ) {
        val coinShape = CircleShape
        if (coin.owned) {
            if (coin.imageObverseUrl != null) {
                AsyncImage(
                    model = coin.imageObverseUrl,
                    contentDescription = coin.nameFr,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier
                        .size(76.dp)
                        .clip(coinShape)
                        .border(1.dp, Gold.copy(alpha = 0.3f), coinShape),
                )
            } else {
                Box(
                    modifier = Modifier
                        .size(76.dp)
                        .clip(coinShape)
                        .background(Gold.copy(alpha = 0.2f))
                        .border(1.dp, Gold.copy(alpha = 0.3f), coinShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = formatFaceValue(coin.faceValueCents),
                        style = MaterialTheme.typography.bodyLarge.copy(
                            fontStyle = FontStyle.Italic,
                            fontWeight = FontWeight.Medium,
                        ),
                        color = GoldDeep,
                    )
                }
            }
        } else {
            // Silhouette
            if (coin.imageObverseUrl != null) {
                AsyncImage(
                    model = coin.imageObverseUrl,
                    contentDescription = coin.nameFr,
                    contentScale = ContentScale.Crop,
                    colorFilter = ColorFilter.tint(Gray200),
                    modifier = Modifier
                        .size(76.dp)
                        .clip(coinShape)
                        .border(1.dp, Ink.copy(alpha = 0.1f), coinShape),
                )
            } else {
                Box(
                    modifier = Modifier
                        .size(76.dp)
                        .clip(coinShape)
                        .background(Gray200.copy(alpha = 0.5f))
                        .border(1.dp, Ink.copy(alpha = 0.1f), coinShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "?",
                        style = MaterialTheme.typography.headlineMedium,
                        color = Ink400,
                    )
                }
            }
        }

        // Year label
        Text(
            text = if (coin.year > 0) coin.year.toString() else "",
            style = EyebrowStyle.copy(fontSize = 7.sp),
            color = Ink400.copy(alpha = 0.6f),
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 4.dp),
        )
    }

    if (showDialog) {
        AlertDialog(
            onDismissRequest = { showDialog = false },
            title = { Text("Marquer comme possédée ?") },
            text = {
                Text(
                    text = "\"${coin.nameFr}\" sera ajouté à ton coffre sans scan.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Ink500,
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    showDialog = false
                    onManualAdd()
                }) {
                    Text("Ajouter", color = Indigo700)
                }
            },
            dismissButton = {
                TextButton(onClick = { showDialog = false }) {
                    Text("Annuler", color = Ink500)
                }
            },
            containerColor = PaperSurface,
        )
    }
}

private fun formatFaceValue(cents: Int): String = when {
    cents <= 0 -> "—"
    cents < 100 -> "${cents}c"
    cents % 100 == 0 -> "${cents / 100}€"
    else -> "%.2f€".format(cents / 100.0)
}
