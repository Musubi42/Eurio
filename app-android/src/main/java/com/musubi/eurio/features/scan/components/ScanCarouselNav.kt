package com.musubi.eurio.features.scan.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.musubi.eurio.data.repository.CoinViewData
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.MonoBadgeStyle

/**
 * Bottom nav for the debug carousel mode. Cycles through every 2 € coin via
 * prev/next; the label shows country · year · name of the currently displayed
 * coin. Visual language matches [ScanDebugOverlay]'s monospace + green accent
 * so the user reads it as a debug affordance, not a production UI element.
 */
@Composable
fun ScanCarouselNav(
    coin: CoinViewData?,
    onPrev: () -> Unit,
    onNext: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.sm))
            .background(Color.Black.copy(alpha = 0.78f))
            .border(
                width = 1.dp,
                color = com.musubi.eurio.ui.theme.Success.copy(alpha = 0.25f),
                shape = RoundedCornerShape(EurioRadii.sm),
            )
            .padding(horizontal = EurioSpacing.s2, vertical = EurioSpacing.s1),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        ArrowButton("‹", onClick = onPrev)
        Column(
            modifier = Modifier.width(220.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = "CAROUSEL",
                style = MonoBadgeStyle,
                color = com.musubi.eurio.ui.theme.Success.copy(alpha = 0.7f),
            )
            Spacer(modifier = Modifier.size(2.dp))
            Text(
                text = coin?.let { "${it.country.uppercase()} · ${it.year} · ${it.nameFr}" } ?: "—",
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.92f),
                textAlign = TextAlign.Center,
                maxLines = 1,
            )
        }
        ArrowButton("›", onClick = onNext)
    }
}

@Composable
private fun ArrowButton(glyph: String, onClick: () -> Unit) {
    Column(
        modifier = Modifier
            .size(36.dp)
            .clip(RoundedCornerShape(3.dp))
            .background(Color.White.copy(alpha = 0.04f))
            .border(
                width = 1.dp,
                color = Color.White.copy(alpha = 0.08f),
                shape = RoundedCornerShape(3.dp),
            )
            .clickable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = glyph,
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.92f),
        )
    }
}
