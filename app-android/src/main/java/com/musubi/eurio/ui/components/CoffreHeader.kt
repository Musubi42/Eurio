package com.musubi.eurio.ui.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.unit.dp
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Gray50
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.PaperSurface

enum class CoffreTab(val labelFr: String) {
    MES_PIECES("Mes pièces"),
    SETS("Sets"),
    CATALOGUE("Catalogue"),
}

/**
 * Segmented control shared between the 3 Coffre sub-views, matching the
 * proto `.tabbed-nav` pattern from components.css.
 */
@Composable
fun CoffreHeader(
    selectedTab: CoffreTab,
    onTabSelected: (CoffreTab) -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(EurioRadii.full)

    Row(
        modifier = modifier
            .fillMaxWidth()
            .clip(shape)
            .background(Gray50)
            .padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
    ) {
        CoffreTab.entries.forEach { tab ->
            val selected = tab == selectedTab
            val bgColor by animateColorAsState(
                targetValue = if (selected) PaperSurface else Gray50,
                animationSpec = tween(150),
                label = "tabBg",
            )
            val textColor by animateColorAsState(
                targetValue = if (selected) Ink else Ink400,
                animationSpec = tween(150),
                label = "tabText",
            )

            Box(
                modifier = Modifier
                    .weight(1f)
                    .then(
                        if (selected) Modifier.shadow(1.dp, RoundedCornerShape(EurioRadii.full))
                        else Modifier
                    )
                    .clip(RoundedCornerShape(EurioRadii.full))
                    .background(bgColor)
                    .clickable { onTabSelected(tab) }
                    .padding(vertical = 8.dp, horizontal = 14.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = tab.labelFr,
                    style = MaterialTheme.typography.bodySmall.copy(
                        fontWeight = androidx.compose.ui.text.font.FontWeight.Medium,
                    ),
                    color = textColor,
                )
            }
        }
    }
}
