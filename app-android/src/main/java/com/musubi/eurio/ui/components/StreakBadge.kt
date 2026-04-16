package com.musubi.eurio.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.MonoBadgeStyle

/**
 * Reusable daily-streak badge. Shows a flame glyph plus the current streak
 * count in tabular JetBrains Mono.
 *
 * Always visible — including when the count is zero. The top bar of the
 * Scan destination uses it in overlay-on-viewfinder mode (dark translucent
 * chrome); future surfaces like the Profile screen will pass paper-surface
 * colors via the parameters.
 */
@Composable
fun StreakBadge(
    count: Int,
    modifier: Modifier = Modifier,
    backgroundColor: Color = Color.Black.copy(alpha = 0.45f),
    borderColor: Color = Gold.copy(alpha = 0.35f),
    flameColor: Color = Gold,
    textColor: Color = Color.White.copy(alpha = 0.92f),
) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(backgroundColor)
            .border(
                width = 1.dp,
                color = borderColor,
                shape = RoundedCornerShape(EurioRadii.full),
            )
            .padding(
                horizontal = EurioSpacing.s3,
                vertical = EurioSpacing.s2,
            ),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "\uD83D\uDD25",
            style = MonoBadgeStyle,
            color = flameColor,
        )
        Text(
            text = count.toString(),
            style = MonoBadgeStyle,
            color = textColor,
        )
    }
}
