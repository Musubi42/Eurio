package com.musubi.eurio.features.coffre.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.musubi.eurio.data.repository.VaultCoinItem
import com.musubi.eurio.data.repository.VaultSort
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.PaperSurface1

/**
 * List display of vault coins matching vault-home.html .vault-home-list pattern.
 */
@Composable
fun VaultList(
    items: List<VaultCoinItem>,
    sort: VaultSort,
    listState: LazyListState,
    onCoinClick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val grouped = buildGroupedItems(items, sort)

    LazyColumn(
        state = listState,
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        for (group in grouped) {
            if (group.label != null) {
                item(key = "list_header_${group.label}") {
                    ListGroupHeader(label = group.label)
                }
            }
            items(
                items = group.coins,
                key = { "row_${it.coin.eurioId}" },
            ) { item ->
                CoinRow(
                    item = item,
                    onClick = { onCoinClick(item.coin.eurioId) },
                )
            }
        }
    }
}

@Composable
private fun ListGroupHeader(label: String) {
    Text(
        text = label,
        style = MaterialTheme.typography.bodyMedium.copy(fontStyle = FontStyle.Italic),
        color = Ink500,
        modifier = Modifier.padding(
            top = EurioSpacing.s5,
            bottom = EurioSpacing.s3,
        ),
    )
}

@Composable
private fun CoinRow(
    item: VaultCoinItem,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.md))
            .clickable { onClick() }
            .padding(horizontal = EurioSpacing.s2, vertical = EurioSpacing.s2),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        // Coin thumbnail
        val coinShape = CircleShape
        if (item.coin.imageObverseUrl != null) {
            AsyncImage(
                model = item.coin.imageObverseUrl,
                contentDescription = item.coin.nameFr,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .size(44.dp)
                    .clip(coinShape)
                    .background(PaperSurface1)
                    .border(1.dp, Gold.copy(alpha = 0.3f), coinShape),
            )
        } else {
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(coinShape)
                    .background(Gold.copy(alpha = 0.15f))
                    .border(1.dp, Gold.copy(alpha = 0.3f), coinShape),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = formatFaceValueShort(item.coin.faceValueCents),
                    style = MaterialTheme.typography.bodySmall.copy(fontStyle = FontStyle.Italic),
                    color = GoldDeep,
                )
            }
        }

        // Meta text
        Column(
            modifier = Modifier.weight(1f),
        ) {
            Text(
                text = item.coin.nameFr + if (item.count > 1) " ×${item.count}" else "",
                style = MaterialTheme.typography.bodyLarge,
                color = Ink,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = buildString {
                    append(formatFaceValueShort(item.coin.faceValueCents))
                    append(" · ")
                    if (item.coin.year > 0) append(item.coin.year)
                    else append("—")
                },
                style = EyebrowStyle,
                color = Ink400,
            )
        }

        // Face value on the right
        Text(
            text = formatFaceValueShort(item.coin.faceValueCents),
            style = MaterialTheme.typography.bodyLarge,
            color = Ink,
        )
    }
}

private fun formatFaceValueShort(cents: Int): String = when {
    cents <= 0 -> "—"
    cents < 100 -> "${cents} c"
    cents % 100 == 0 -> "${cents / 100} €"
    else -> "%.2f €".format(cents / 100.0)
}
