package com.musubi.eurio.features.sets

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
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.draw.rotate
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
import com.musubi.eurio.data.repository.SetCoinSlot
import com.musubi.eurio.data.repository.SetWithProgress
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold300
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.GoldSoft
import com.musubi.eurio.ui.theme.Gray100
import com.musubi.eurio.ui.theme.Gray200
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink300
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Paper
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.PaperSurface1

@Composable
fun SetDetailScreen(
    viewModel: SetDetailViewModel,
    onBack: () -> Unit,
    onCoinClick: (String) -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(PaperSurface),
    ) {
        when {
            state.loading -> {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = Gold)
                }
            }
            state.error != null -> {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(state.error!!, color = Ink500)
                }
            }
            state.set != null -> SetDetailContent(
                set = state.set!!,
                slots = state.slots,
                onBack = onBack,
                onCoinClick = onCoinClick,
                onManualAdd = { viewModel.manualAdd(it) },
            )
        }
    }
}

@Composable
private fun SetDetailContent(
    set: SetWithProgress,
    slots: List<SetCoinSlot>,
    onBack: () -> Unit,
    onCoinClick: (String) -> Unit,
    onManualAdd: (String) -> Unit,
) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(3),
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding(),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        // Topbar
        item(span = { GridItemSpan(3) }) {
            TopBar(onBack = onBack)
        }

        // Hero section
        item(span = { GridItemSpan(3) }) {
            HeroSection(set = set, slots = slots)
        }

        // Progress section
        item(span = { GridItemSpan(3) }) {
            ProgressSection(set = set)
        }

        // Section header
        item(span = { GridItemSpan(3) }) {
            PlancheSectionHeader()
        }

        // Planche grid
        items(
            items = slots,
            key = { "slot_${it.eurioId}" },
        ) { slot ->
            CoinSlot(
                slot = slot,
                onClick = { onCoinClick(slot.eurioId) },
                onLongPress = if (!slot.owned) {
                    { onManualAdd(slot.eurioId) }
                } else null,
            )
        }

        // Reward teaser
        if (set.rewardJson != null) {
            item(span = { GridItemSpan(3) }) {
                RewardTeaser()
            }
        }

        // Completion note
        if (set.isComplete && set.completedAt != null) {
            item(span = { GridItemSpan(3) }) {
                CompletionNote(completedAt = set.completedAt)
            }
        }

        // Bottom spacer
        item(span = { GridItemSpan(3) }) {
            Spacer(Modifier.height(EurioSpacing.s10))
        }
    }
}

@Composable
private fun TopBar(onBack: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s3),
        verticalAlignment = Alignment.CenterVertically,
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
                Text(text = "←", style = MaterialTheme.typography.titleMedium, color = Ink500)
                Text(
                    text = "RETOUR",
                    style = MonoBadgeStyle,
                    color = Ink500,
                )
            }
        }
    }
}

@Composable
private fun HeroSection(set: SetWithProgress, slots: List<SetCoinSlot>) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s4),
    ) {
        // Fan collage of 4 representative coins
        FanCollage(
            slots = slots.take(4),
            modifier = Modifier
                .fillMaxWidth()
                .height(130.dp),
        )

        Spacer(Modifier.height(EurioSpacing.s5))

        // Kind eyebrow
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Box(
                modifier = Modifier
                    .width(16.dp)
                    .height(1.dp)
                    .background(Gold),
            )
            Text(
                text = set.kind.uppercase(),
                style = EyebrowStyle,
                color = GoldDeep,
            )
        }

        Spacer(Modifier.height(10.dp))

        // Title
        Text(
            text = set.nameFr,
            style = MaterialTheme.typography.displayMedium.copy(
                lineHeight = 40.sp,
                letterSpacing = (-0.02).sp,
            ),
            color = Ink,
        )

        // Description
        if (set.descriptionFr != null) {
            Spacer(Modifier.height(EurioSpacing.s3))
            Text(
                text = set.descriptionFr,
                style = MaterialTheme.typography.bodyMedium,
                color = Ink500,
            )
        }

        Spacer(Modifier.height(EurioSpacing.s4))

        // Category chip
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(EurioRadii.full))
                    .background(Gray100)
                    .border(1.dp, Ink.copy(alpha = 0.06f), RoundedCornerShape(EurioRadii.full))
                    .padding(horizontal = 10.dp, vertical = 6.dp),
            ) {
                Text(
                    text = set.category,
                    style = MaterialTheme.typography.bodySmall,
                    color = Ink,
                )
            }
        }
    }
}

@Composable
private fun FanCollage(slots: List<SetCoinSlot>, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier,
        contentAlignment = Alignment.Center,
    ) {
        val offsets = listOf(
            -60.dp to 5.dp to -11f,
            -21.dp to -3.dp to -3f,
            21.dp to -3.dp to 4f,
            60.dp to 5.dp to 12f,
        )
        slots.forEachIndexed { index, slot ->
            val (offset, rotation) = offsets.getOrElse(index) { offsets.last() }
            val (x, y) = offset

            Box(
                modifier = Modifier
                    .size(96.dp)
                    .offset(x = x, y = y)
                    .rotate(rotation)
                    .clip(CircleShape)
                    .background(
                        if (slot.owned) Gold.copy(alpha = 0.25f)
                        else Gray200.copy(alpha = 0.5f)
                    )
                    .border(1.dp, Gold.copy(alpha = 0.3f), CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                if (slot.imageObverseUrl != null && slot.owned) {
                    AsyncImage(
                        model = slot.imageObverseUrl,
                        contentDescription = slot.nameFr,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize().clip(CircleShape),
                    )
                } else {
                    Text(
                        text = formatFaceValue(slot.faceValueCents),
                        style = MaterialTheme.typography.headlineMedium.copy(
                            fontStyle = FontStyle.Italic,
                            fontWeight = FontWeight.Medium,
                            fontSize = 18.sp,
                        ),
                        color = if (slot.owned) GoldDeep else Ink400,
                    )
                }
            }
        }
    }
}

@Composable
private fun ProgressSection(set: SetWithProgress) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s6),
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column {
            Text(
                text = "PROGRESSION",
                style = EyebrowStyle,
                color = Ink400,
            )
            Text(
                text = "${(set.percent * 100).toInt()}",
                style = MaterialTheme.typography.displayLarge.copy(
                    fontStyle = FontStyle.Italic,
                    fontWeight = FontWeight.Light,
                    fontSize = 72.sp,
                    lineHeight = 68.sp,
                ),
                color = if (set.isComplete) GoldDeep else Ink,
            )
            Text(
                text = "${set.owned} / ${set.total} PIÈCES COLLECTÉES",
                style = MonoBadgeStyle,
                color = Ink500,
            )
        }

        LinearProgressIndicator(
            progress = { set.percent },
            modifier = Modifier
                .width(130.dp)
                .height(3.dp)
                .clip(RoundedCornerShape(2.dp)),
            color = Gold,
            trackColor = Gray100,
            strokeCap = StrokeCap.Round,
        )
    }
}

@Composable
private fun PlancheSectionHeader() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s3),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Bottom,
    ) {
        Text(
            text = "Planche",
            style = MaterialTheme.typography.headlineMedium.copy(fontStyle = FontStyle.Italic),
            color = Ink,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            LegendDot(gold = true, label = "possédées")
            LegendDot(gold = false, label = "à scanner")
        }
    }
}

@Composable
private fun LegendDot(gold: Boolean, label: String) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(CircleShape)
                .then(
                    if (gold) Modifier.background(Gold)
                    else Modifier
                        .background(Gray200)
                        .border(1.dp, Ink300, CircleShape)
                ),
        )
        Text(
            text = label,
            style = MonoBadgeStyle.copy(fontSize = 9.sp),
            color = Ink400,
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun CoinSlot(
    slot: SetCoinSlot,
    onClick: () -> Unit,
    onLongPress: (() -> Unit)?,
) {
    var showManualAddDialog by remember { mutableStateOf(false) }

    val shape = RoundedCornerShape(EurioRadii.md)
    Box(
        modifier = Modifier
            .padding(horizontal = EurioSpacing.s1)
            .aspectRatio(1f)
            .clip(shape)
            .background(
                if (slot.owned) PaperSurface1
                else PaperSurface1.copy(alpha = 0.5f)
            )
            .combinedClickable(
                onClick = onClick,
                onLongClick = {
                    if (onLongPress != null) showManualAddDialog = true
                },
            ),
        contentAlignment = Alignment.Center,
    ) {
        if (slot.owned) {
            // Owned: show coin image or gold placeholder
            val coinShape = CircleShape
            if (slot.imageObverseUrl != null) {
                AsyncImage(
                    model = slot.imageObverseUrl,
                    contentDescription = slot.nameFr,
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
                        text = formatFaceValue(slot.faceValueCents),
                        style = MaterialTheme.typography.bodyLarge.copy(
                            fontStyle = FontStyle.Italic,
                            fontWeight = FontWeight.Medium,
                        ),
                        color = GoldDeep,
                    )
                }
            }
        } else {
            // Missing: silhouette
            val coinShape = CircleShape
            if (slot.imageObverseUrl != null) {
                AsyncImage(
                    model = slot.imageObverseUrl,
                    contentDescription = slot.nameFr,
                    contentScale = ContentScale.Crop,
                    colorFilter = ColorFilter.tint(Gray200),
                    modifier = Modifier
                        .size(76.dp)
                        .clip(coinShape)
                        .border(
                            1.dp,
                            Ink.copy(alpha = 0.1f),
                            coinShape,
                        ),
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

        // Country + year underneath
        Text(
            text = "${slot.country.uppercase()} ${if (slot.year > 0) slot.year else ""}",
            style = EyebrowStyle.copy(fontSize = 7.sp),
            color = Ink400.copy(alpha = 0.6f),
            textAlign = TextAlign.Center,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 4.dp),
        )
    }

    if (showManualAddDialog) {
        AlertDialog(
            onDismissRequest = { showManualAddDialog = false },
            title = { Text("Marquer comme possédée ?") },
            text = {
                Text(
                    text = "\"${slot.nameFr}\" sera ajouté à ton coffre sans scan.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Ink500,
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    showManualAddDialog = false
                    onLongPress?.invoke()
                }) {
                    Text("Ajouter", color = Indigo700)
                }
            },
            dismissButton = {
                TextButton(onClick = { showManualAddDialog = false }) {
                    Text("Annuler", color = Ink500)
                }
            },
            containerColor = PaperSurface,
        )
    }
}

@Composable
private fun RewardTeaser() {
    Row(
        modifier = Modifier
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s6)
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.lg))
            .background(PaperSurface)
            .border(1.dp, Gold.copy(alpha = 0.35f), RoundedCornerShape(EurioRadii.lg))
            .padding(EurioSpacing.s4),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s4),
    ) {
        // Medal circle
        Box(
            modifier = Modifier
                .size(56.dp)
                .clip(CircleShape)
                .background(Gold),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "★",
                style = MaterialTheme.typography.headlineMedium,
                color = GoldDeep,
            )
        }

        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "RÉCOMPENSE",
                style = EyebrowStyle,
                color = GoldDeep,
            )
            Text(
                text = "Badge à débloquer",
                style = MaterialTheme.typography.bodyLarge.copy(fontStyle = FontStyle.Italic),
                color = Ink,
            )
            Text(
                text = "Débloqué à la dernière pièce scannée.",
                style = MaterialTheme.typography.bodySmall,
                color = Ink400,
            )
        }
    }
}

@Composable
private fun CompletionNote(completedAt: Long) {
    val dateStr = remember(completedAt) {
        val sdf = java.text.SimpleDateFormat("d MMMM yyyy", java.util.Locale.FRENCH)
        sdf.format(java.util.Date(completedAt))
    }
    Text(
        text = "Complété le $dateStr",
        style = MaterialTheme.typography.bodyMedium.copy(fontStyle = FontStyle.Italic),
        color = GoldDeep,
        textAlign = TextAlign.Center,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = EurioSpacing.s3),
    )
}

private fun formatFaceValue(cents: Int): String = when {
    cents <= 0 -> "—"
    cents < 100 -> "${cents}c"
    cents % 100 == 0 -> "${cents / 100}€"
    else -> "%.2f€".format(cents / 100.0)
}
