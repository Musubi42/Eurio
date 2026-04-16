package com.musubi.eurio.features.catalog

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.asAndroidPath
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.musubi.eurio.data.repository.CountryProgress
import com.musubi.eurio.data.repository.RoomCatalogRepository
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold300
import com.musubi.eurio.ui.theme.GoldSoft
import com.musubi.eurio.ui.theme.Gray100
import com.musubi.eurio.ui.theme.Indigo600
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Indigo800
import com.musubi.eurio.ui.theme.Indigo900
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.PaperSurface1

/**
 * Catalogue sub-view: eurozone map + list toggle.
 * Matches vault-catalog-map.html.
 */
@Composable
fun CatalogScreen(
    viewModel: CatalogViewModel,
    onCountryClick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val progress by viewModel.countryProgress.collectAsStateWithLifecycle()

    val progressMap = remember(progress) {
        progress.associateBy { it.country.lowercase() }
    }

    Column(modifier = modifier.fillMaxSize()) {
        // Mode toggle
        ModeToggle(
            current = uiState.mode,
            onChange = { viewModel.setMode(it) },
        )

        when (uiState.mode) {
            CatalogMode.MAP -> MapModeContent(
                progressMap = progressMap,
                totalProgress = progress,
                selectedCountry = uiState.selectedCountry,
                onCountrySelect = { viewModel.selectCountry(it) },
                onCountryDrillDown = onCountryClick,
            )
            CatalogMode.LIST -> ListModeContent(
                progress = progress,
                onCountryClick = onCountryClick,
            )
        }
    }
}

@Composable
private fun ModeToggle(current: CatalogMode, onChange: (CatalogMode) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = EurioSpacing.s4),
        horizontalArrangement = Arrangement.Center,
    ) {
        val shape = RoundedCornerShape(EurioRadii.full)
        Row(
            modifier = Modifier
                .clip(shape)
                .background(PaperSurface1)
                .border(1.dp, Ink.copy(alpha = 0.06f), shape)
                .padding(3.dp),
        ) {
            ToggleBtn("Carte", current == CatalogMode.MAP) { onChange(CatalogMode.MAP) }
            ToggleBtn("Liste", current == CatalogMode.LIST) { onChange(CatalogMode.LIST) }
        }
    }
}

@Composable
private fun ToggleBtn(label: String, selected: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(EurioRadii.full)
    Box(
        modifier = Modifier
            .then(if (selected) Modifier.shadow(1.dp, shape) else Modifier)
            .clip(shape)
            .background(if (selected) PaperSurface else PaperSurface1)
            .clickable { onClick() }
            .padding(horizontal = 18.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall.copy(
                fontWeight = androidx.compose.ui.text.font.FontWeight.Medium,
            ),
            color = if (selected) Ink else Ink400,
        )
    }
}

@Composable
private fun MapModeContent(
    progressMap: Map<String, CountryProgress>,
    totalProgress: List<CountryProgress>,
    selectedCountry: String?,
    onCountrySelect: (String?) -> Unit,
    onCountryDrillDown: (String) -> Unit,
) {
    val totalOwned = totalProgress.sumOf { it.owned }
    val totalCoins = totalProgress.sumOf { it.total }

    LazyColumn(modifier = Modifier.fillMaxSize()) {
        // Map card
        item {
            MapCard(
                progressMap = progressMap,
                totalOwned = totalOwned,
                totalCoins = totalCoins,
                onCountryTap = onCountrySelect,
            )
        }

        // Legend
        item {
            MapLegend(
                modifier = Modifier.padding(
                    horizontal = EurioSpacing.s5,
                    vertical = EurioSpacing.s2,
                ),
            )
        }

        // Peek card (selected country)
        val selected = selectedCountry ?: totalProgress.firstOrNull()?.country
        if (selected != null) {
            val cp = progressMap[selected.lowercase()]
            if (cp != null) {
                item {
                    PeekCard(
                        country = cp,
                        onClick = { onCountryDrillDown(cp.country) },
                    )
                }
            }
        }

        item { Spacer(Modifier.height(EurioSpacing.s10)) }
    }
}

@Composable
private fun MapCard(
    progressMap: Map<String, CountryProgress>,
    totalOwned: Int,
    totalCoins: Int,
    onCountryTap: (String) -> Unit,
) {
    Box(
        modifier = Modifier
            .padding(horizontal = EurioSpacing.s5)
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.xl))
            .background(
                Brush.verticalGradient(
                    colors = listOf(Indigo800, Indigo900),
                )
            ),
    ) {
        Column(
            modifier = Modifier.padding(
                horizontal = EurioSpacing.s5,
                vertical = EurioSpacing.s6,
            ),
        ) {
            // Header
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Bottom,
            ) {
                Text(
                    text = "EUROZONE · 21 PAYS",
                    style = MonoBadgeStyle.copy(fontSize = 9.sp),
                    color = Color.White.copy(alpha = 0.55f),
                )
                Row(verticalAlignment = Alignment.Bottom) {
                    Text(
                        text = "$totalOwned",
                        style = MaterialTheme.typography.bodyLarge.copy(fontStyle = FontStyle.Italic),
                        color = Color.White,
                    )
                    Text(
                        text = "/$totalCoins pièces",
                        style = MonoBadgeStyle,
                        color = Gold300,
                    )
                }
            }

            Spacer(Modifier.height(EurioSpacing.s2))

            // Map Canvas
            EurozoneMapCanvas(
                progressMap = progressMap,
                onCountryTap = onCountryTap,
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(MAP_VIEWBOX_WIDTH / MAP_VIEWBOX_HEIGHT),
            )

            Spacer(Modifier.height(EurioSpacing.s4))

            // Legend bar
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
            ) {
                Text(
                    text = "0%",
                    style = MonoBadgeStyle.copy(fontSize = 8.sp),
                    color = Color.White.copy(alpha = 0.5f),
                )
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(6.dp)
                        .clip(RoundedCornerShape(EurioRadii.full))
                        .background(
                            Brush.horizontalGradient(
                                colors = listOf(
                                    Gold.copy(alpha = 0.1f),
                                    Gold.copy(alpha = 0.45f),
                                    Gold,
                                ),
                            )
                        ),
                )
                Text(
                    text = "100%",
                    style = MonoBadgeStyle.copy(fontSize = 8.sp),
                    color = Color.White.copy(alpha = 0.5f),
                )
            }
        }
    }
}

@Composable
private fun EurozoneMapCanvas(
    progressMap: Map<String, CountryProgress>,
    onCountryTap: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    // Pre-parse paths
    val parsedPaths = remember {
        EUROZONE_MAP_PATHS.mapNotNull { cp ->
            if (cp.isMicro || cp.pathData.isBlank()) return@mapNotNull null
            try {
                val path = PathParser().parsePathString(cp.pathData).toPath()
                cp to path
            } catch (e: Exception) {
                null
            }
        }
    }
    val microPaths = remember {
        EUROZONE_MAP_PATHS.filter { it.isMicro }
    }

    Canvas(modifier = modifier) {
        val scaleX = size.width / MAP_VIEWBOX_WIDTH
        val scaleY = size.height / MAP_VIEWBOX_HEIGHT

        // Draw country paths
        for ((cp, path) in parsedPaths) {
            val progress = progressMap[cp.iso.lowercase()]?.percent ?: 0f
            val alpha = 0.06f + 0.88f * progress

            val scaledPath = androidx.compose.ui.graphics.Path()
            val matrix = android.graphics.Matrix()
            matrix.setScale(scaleX, scaleY)
            scaledPath.asAndroidPath().addPath(path.asAndroidPath(), matrix)

            // Fill
            drawPath(
                path = scaledPath,
                color = Gold.copy(alpha = alpha),
                style = Fill,
            )
            // Stroke
            drawPath(
                path = scaledPath,
                color = GoldSoft.copy(alpha = 0.38f),
                style = Stroke(width = 0.7f * scaleX),
            )
        }

        // Draw micro-state pastilles
        for (micro in microPaths) {
            val progress = progressMap[micro.iso.lowercase()]?.percent ?: 0f

            // Leader line (dashed)
            drawLine(
                color = GoldSoft.copy(alpha = 0.28f),
                start = Offset(micro.leaderFromX * scaleX, micro.leaderFromY * scaleY),
                end = Offset(micro.microCx * scaleX, micro.microCy * scaleY),
                strokeWidth = 0.5f * scaleX,
                pathEffect = PathEffect.dashPathEffect(
                    floatArrayOf(1.5f * scaleX, 2f * scaleX),
                ),
            )

            // Dot
            val cx = micro.microCx * scaleX
            val cy = micro.microCy * scaleY
            val r = 12f * scaleX
            drawCircle(
                color = Indigo700,
                radius = r,
                center = Offset(cx, cy),
            )
            drawCircle(
                color = Gold.copy(alpha = 0.06f + 0.88f * progress),
                radius = r - 1.2f * scaleX,
                center = Offset(cx, cy),
            )
            drawCircle(
                color = Gold,
                radius = r,
                center = Offset(cx, cy),
                style = Stroke(width = 1.2f * scaleX),
            )
        }
    }
}

@Composable
private fun MapLegend(modifier: Modifier = Modifier) {
    // Already included in the map card — this is intentionally empty
}

@Composable
private fun PeekCard(
    country: CountryProgress,
    onClick: () -> Unit,
) {
    val name = RoomCatalogRepository.countryName(country.country)
    val flag = RoomCatalogRepository.countryFlag(country.country)

    Row(
        modifier = Modifier
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s5)
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.lg))
            .background(PaperSurface)
            .border(1.dp, Ink.copy(alpha = 0.08f), RoundedCornerShape(EurioRadii.lg))
            .clickable { onClick() }
            .padding(EurioSpacing.s4),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s4),
    ) {
        // Flag
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(CircleShape)
                .background(PaperSurface1)
                .border(1.dp, Ink.copy(alpha = 0.06f), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Text(text = flag, fontSize = 24.sp)
        }

        // Body
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = name,
                style = MaterialTheme.typography.headlineMedium.copy(
                    fontStyle = FontStyle.Italic,
                    lineHeight = 22.sp,
                ),
                color = Ink,
            )
            Spacer(Modifier.height(4.dp))
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    text = "${country.owned} / ${country.total}",
                    style = MonoBadgeStyle,
                    color = Ink400,
                )
                LinearProgressIndicator(
                    progress = { country.percent },
                    modifier = Modifier
                        .weight(1f)
                        .height(3.dp)
                        .clip(RoundedCornerShape(2.dp)),
                    color = Gold,
                    trackColor = Gray100,
                    strokeCap = StrokeCap.Round,
                )
                Text(
                    text = "${(country.percent * 100).toInt()}%",
                    style = MonoBadgeStyle,
                    color = Ink400,
                )
            }
        }

        // Chevron
        Text(text = "›", style = MaterialTheme.typography.titleLarge, color = Ink400)
    }
}

@Composable
private fun ListModeContent(
    progress: List<CountryProgress>,
    onCountryClick: (String) -> Unit,
) {
    val sorted = remember(progress) {
        progress.sortedBy { RoomCatalogRepository.countryName(it.country) }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(
            horizontal = EurioSpacing.s5,
            vertical = EurioSpacing.s2,
        ),
    ) {
        items(
            items = sorted,
            key = { "list_${it.country}" },
        ) { cp ->
            CountryListRow(
                country = cp,
                onClick = { onCountryClick(cp.country) },
            )
        }
        item { Spacer(Modifier.height(EurioSpacing.s10)) }
    }
}

@Composable
private fun CountryListRow(
    country: CountryProgress,
    onClick: () -> Unit,
) {
    val name = RoomCatalogRepository.countryName(country.country)
    val flag = RoomCatalogRepository.countryFlag(country.country)

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.md))
            .clickable { onClick() }
            .padding(EurioSpacing.s3),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        Box(
            modifier = Modifier
                .size(32.dp)
                .clip(CircleShape)
                .background(PaperSurface1)
                .border(1.dp, Ink.copy(alpha = 0.06f), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Text(text = flag, fontSize = 18.sp)
        }

        Text(
            text = name,
            style = MaterialTheme.typography.bodyLarge,
            color = Ink,
            modifier = Modifier.weight(1f),
        )

        Text(
            text = "${country.owned}/${country.total}",
            style = MonoBadgeStyle,
            color = Ink400,
        )

        LinearProgressIndicator(
            progress = { country.percent },
            modifier = Modifier
                .width(56.dp)
                .height(3.dp)
                .clip(RoundedCornerShape(2.dp)),
            color = Gold,
            trackColor = Gray100,
            strokeCap = StrokeCap.Round,
        )
    }
}
