package com.musubi.eurio.features.scan

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ui.components.StreakBadge
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.MonoBadgeStyle

/**
 * Translucent top bar overlaying the viewfinder. Two slots:
 *  - Version badge (left): hidden debug toggle. Tap 7× within 2s to open
 *    the debug overlay.
 *  - Streak badge (right): always visible, shows the current daily streak.
 *
 * Stateless — the parent [ScanScreen] drives both [versionName] and
 * [streakCount] from the ViewModel.
 */
@Composable
fun ScanTopBar(
    versionName: String,
    streakCount: Int,
    onVersionBadgeTap: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .padding(
                horizontal = EurioSpacing.s5,
                vertical = EurioSpacing.s3,
            ),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(EurioRadii.full))
                .background(Color.Black.copy(alpha = 0.45f))
                .border(
                    width = 1.dp,
                    color = Color.White.copy(alpha = 0.1f),
                    shape = RoundedCornerShape(EurioRadii.full),
                )
                .clickable { onVersionBadgeTap() }
                .padding(
                    horizontal = EurioSpacing.s3,
                    vertical = EurioSpacing.s2,
                ),
        ) {
            Text(
                text = versionName,
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.78f),
            )
        }

        StreakBadge(count = streakCount)
    }
}
