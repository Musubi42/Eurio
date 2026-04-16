package com.musubi.eurio.features.coffre.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.VerticalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink400

/**
 * Stats strip: Pièces / Pays / Séries — matches vault-home.html .vault-home-stats.
 */
@Composable
fun VaultStatsStrip(
    coinCount: Int,
    countryCount: Int,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .padding(vertical = EurioSpacing.s4),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s6),
    ) {
        StatItem(value = coinCount.toString(), label = "PIÈCES")

        VerticalDivider(
            modifier = Modifier.fillMaxHeight(),
            thickness = 1.dp,
            color = Ink.copy(alpha = 0.08f),
        )

        StatItem(value = countryCount.toString(), label = "PAYS")

        VerticalDivider(
            modifier = Modifier.fillMaxHeight(),
            thickness = 1.dp,
            color = Ink.copy(alpha = 0.08f),
        )

        StatItem(value = "$countryCount/21", label = "SÉRIES")
    }
}

@Composable
private fun StatItem(
    value: String,
    label: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(
            text = value,
            style = MaterialTheme.typography.headlineMedium,
            color = Ink,
        )
        Text(
            text = label,
            style = EyebrowStyle,
            color = Ink400,
        )
    }
}
