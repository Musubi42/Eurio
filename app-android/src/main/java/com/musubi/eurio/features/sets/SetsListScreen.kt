package com.musubi.eurio.features.sets

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.musubi.eurio.data.repository.SetWithProgress
import com.musubi.eurio.ui.theme.Danger
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold300
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
import com.musubi.eurio.ui.theme.Success

/**
 * Sets list sub-view matching vault-sets-list.html.
 */
@Composable
fun SetsListScreen(
    viewModel: SetsListViewModel,
    onSetClick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val sets by viewModel.filteredSets.collectAsStateWithLifecycle()
    val stats by viewModel.stats.collectAsStateWithLifecycle()

    Column(modifier = modifier.fillMaxSize()) {
        // Stats line
        StatsLine(stats)

        // Filter chips
        FilterChips(
            categoryFilter = uiState.categoryFilter,
            stateFilter = uiState.stateFilter,
            onCategoryChange = { viewModel.setCategoryFilter(it) },
            onStateChange = { viewModel.setStateFilter(it) },
        )

        Spacer(Modifier.height(EurioSpacing.s2))

        if (sets.isEmpty()) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "Aucun set ne correspond aux filtres",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Ink500,
                )
            }
        } else {
            val inProgress = sets.filter { it.owned > 0 && !it.isComplete }
            val notStarted = sets.filter { it.owned == 0 }
            val completed = sets.filter { it.isComplete }

            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(EurioSpacing.s4),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(
                    start = EurioSpacing.s5,
                    end = EurioSpacing.s5,
                    top = EurioSpacing.s2,
                    bottom = EurioSpacing.s10,
                ),
            ) {
                items(
                    items = inProgress + notStarted,
                    key = { "set_${it.id}" },
                ) { set ->
                    SetCard(set = set, onClick = { onSetClick(set.id) })
                }

                if (completed.isNotEmpty()) {
                    item(key = "divider_completed") {
                        CompletedDivider()
                    }
                    items(
                        items = completed,
                        key = { "set_done_${it.id}" },
                    ) { set ->
                        SetCard(set = set, onClick = { onSetClick(set.id) })
                    }
                }
            }
        }
    }
}

@Composable
private fun StatsLine(stats: SetsStats) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s3),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s4),
    ) {
        StatItem(value = stats.total.toString(), label = "sets")
        StatItem(value = stats.completed.toString(), label = "complétés")
        StatItem(
            value = "${stats.totalCoins}/${stats.totalTarget}",
            label = "pièces",
        )
    }
}

@Composable
private fun StatItem(value: String, label: String) {
    Row(verticalAlignment = Alignment.Bottom) {
        Text(
            text = value,
            style = MaterialTheme.typography.bodyLarge.copy(fontStyle = FontStyle.Italic),
            color = Ink,
        )
        Spacer(Modifier.width(4.dp))
        Text(
            text = label,
            style = MonoBadgeStyle,
            color = Ink400,
        )
    }
}

@Composable
private fun FilterChips(
    categoryFilter: String?,
    stateFilter: SetsStateFilter,
    onCategoryChange: (String?) -> Unit,
    onStateChange: (SetsStateFilter) -> Unit,
) {
    Column(
        modifier = Modifier.padding(horizontal = EurioSpacing.s5),
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        // Category row
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
        ) {
            Text(text = "TYPE", style = EyebrowStyle, color = Ink400)
            Spacer(Modifier.width(EurioSpacing.s1))
            ChipButton("Tous", categoryFilter == null) { onCategoryChange(null) }
            ChipButton("Pays", categoryFilter == "country") { onCategoryChange("country") }
            ChipButton("Thème", categoryFilter == "theme") { onCategoryChange("theme") }
            ChipButton("Tier", categoryFilter == "tier") { onCategoryChange("tier") }
            ChipButton("Perso", categoryFilter == "personal") { onCategoryChange("personal") }
            ChipButton("Chasse", categoryFilter == "hunt") { onCategoryChange("hunt") }
        }

        // State row
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
        ) {
            Text(text = "ÉTAT", style = EyebrowStyle, color = Ink400)
            Spacer(Modifier.width(EurioSpacing.s1))
            ChipButton("Tous", stateFilter == SetsStateFilter.ALL) { onStateChange(SetsStateFilter.ALL) }
            ChipButton("En cours", stateFilter == SetsStateFilter.IN_PROGRESS) { onStateChange(SetsStateFilter.IN_PROGRESS) }
            ChipButton("Complétés", stateFilter == SetsStateFilter.COMPLETED) { onStateChange(SetsStateFilter.COMPLETED) }
            ChipButton("Non commencés", stateFilter == SetsStateFilter.NOT_STARTED) { onStateChange(SetsStateFilter.NOT_STARTED) }
        }
    }
}

@Composable
private fun ChipButton(label: String, selected: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(EurioRadii.full)
    Box(
        modifier = Modifier
            .clip(shape)
            .background(if (selected) Ink else PaperSurface1)
            .border(1.dp, if (selected) Ink else Ink.copy(alpha = 0.06f), shape)
            .clickable { onClick() }
            .padding(horizontal = 13.dp, vertical = 7.dp),
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

@Composable
private fun SetCard(
    set: SetWithProgress,
    onClick: () -> Unit,
) {
    val isComplete = set.isComplete
    val shape = RoundedCornerShape(EurioRadii.lg)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(PaperSurface)
            .then(
                if (isComplete) Modifier.border(1.dp, Gold.copy(alpha = 0.4f), shape)
                else Modifier.border(1.dp, Ink.copy(alpha = 0.06f), shape)
            )
            .clickable { onClick() }
            .padding(EurioSpacing.s4),
    ) {
        // Header: title + kind chip
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Top,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = set.nameFr,
                    style = MaterialTheme.typography.headlineMedium.copy(
                        fontStyle = FontStyle.Italic,
                        lineHeight = 22.sp,
                    ),
                    color = Ink,
                )
                if (set.descriptionFr != null) {
                    Spacer(Modifier.height(3.dp))
                    Text(
                        text = set.descriptionFr,
                        style = MaterialTheme.typography.bodySmall,
                        color = Ink400,
                        maxLines = 2,
                    )
                }
            }
            if (isComplete) {
                Text(
                    text = "👑",
                    style = MaterialTheme.typography.titleLarge,
                )
            }
        }

        Spacer(Modifier.height(EurioSpacing.s3))

        // Kind chip
        KindChip(set.category)

        Spacer(Modifier.height(EurioSpacing.s4))

        // Mini planche preview (4x2 grid of circles)
        MiniPlanche(total = set.total, owned = set.owned)

        Spacer(Modifier.height(EurioSpacing.s4))

        // Progress footer
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        ) {
            LinearProgressIndicator(
                progress = { set.percent },
                modifier = Modifier
                    .weight(1f)
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp)),
                color = if (isComplete) Gold else Gold300,
                trackColor = Gray100,
                strokeCap = StrokeCap.Round,
            )
            Text(
                text = "${set.owned} / ${set.total}",
                style = MonoBadgeStyle,
                color = Ink400,
            )
            Text(
                text = "${(set.percent * 100).toInt()}%",
                style = MaterialTheme.typography.headlineMedium.copy(
                    fontStyle = FontStyle.Italic,
                    fontSize = 18.sp,
                ),
                color = if (isComplete) GoldDeep else Ink,
            )
        }
    }
}

@Composable
private fun KindChip(category: String) {
    val (bgColor, textColor) = when (category) {
        "country" -> Indigo700.copy(alpha = 0.1f) to Indigo700
        "theme" -> Gold.copy(alpha = 0.18f) to GoldDeep
        "tier" -> Success.copy(alpha = 0.15f) to Success
        "personal" -> Ink.copy(alpha = 0.08f) to Ink500
        "hunt" -> Danger.copy(alpha = 0.14f) to Danger
        else -> Ink.copy(alpha = 0.08f) to Ink500
    }
    val label = when (category) {
        "country" -> "PAYS"
        "theme" -> "THÈME"
        "tier" -> "TIER"
        "personal" -> "PERSO"
        "hunt" -> "CHASSE"
        else -> category.uppercase()
    }

    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(bgColor)
            .padding(horizontal = 8.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box(
            modifier = Modifier
                .size(4.dp)
                .clip(CircleShape)
                .background(textColor),
        )
        Text(
            text = label,
            style = MonoBadgeStyle.copy(fontSize = 9.sp),
            color = textColor,
        )
    }
}

@Composable
private fun MiniPlanche(total: Int, owned: Int) {
    val slots = minOf(total, 8) // Show max 8 preview slots
    if (slots == 0) return

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.md))
            .background(PaperSurface1)
            .padding(EurioSpacing.s3),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        repeat(slots) { index ->
            val isOwned = index < owned
            Box(
                modifier = Modifier
                    .weight(1f)
                    .aspectRatio(1f)
                    .clip(CircleShape)
                    .background(
                        if (isOwned) Gold.copy(alpha = 0.3f)
                        else Gray200.copy(alpha = 0.5f)
                    )
                    .then(
                        if (!isOwned) Modifier.border(1.dp, Ink.copy(alpha = 0.1f), CircleShape)
                        else Modifier
                    ),
            )
        }
        // Pad remaining if less than 8 real slots
        repeat((8 - slots).coerceAtLeast(0)) {
            Spacer(Modifier.weight(1f))
        }
    }
}

@Composable
private fun CompletedDivider() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = EurioSpacing.s4),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        Text(
            text = "Complétés",
            style = MaterialTheme.typography.bodyMedium.copy(fontStyle = FontStyle.Italic),
            color = Ink500,
        )
        Box(
            modifier = Modifier
                .weight(1f)
                .height(1.dp)
                .background(Gold.copy(alpha = 0.35f)),
        )
    }
}
