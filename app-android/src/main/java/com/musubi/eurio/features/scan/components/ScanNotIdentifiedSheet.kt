package com.musubi.eurio.features.scan.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import com.musubi.eurio.data.repository.CoinViewData
import com.musubi.eurio.ui.theme.Danger
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold100
import com.musubi.eurio.ui.theme.Indigo900
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Warning

/**
 * Scene parity: docs/design/prototype/scenes/scan-not-identified.html
 *
 * A frozen top frame shows a red-ring "non identifiée" state; the bottom
 * sheet hosts three escape hatches:
 *   1. Top-5 suggestion list (kNN neighbours from the failed pass)
 *   2. Face value picker (8 chips, 1 c → 2 €) enabling a manual add
 *   3. Retry + "send for analysis" buttons
 */
@Composable
fun ScanNotIdentifiedSheet(
    top5: List<CoinViewData>,
    onPickSuggestion: (String) -> Unit,
    onPickFaceValue: (Int) -> Unit,
    onRetry: () -> Unit,
    onReport: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var selectedCents by remember { mutableStateOf<Int?>(null) }

    Column(modifier = modifier.fillMaxSize()) {
        // Top — frozen frame header with red ring
        FrozenFrame()

        // Bottom — sheet
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .fillMaxHeight()
                .background(Indigo900)
                .padding(
                    horizontal = EurioSpacing.s5,
                    vertical = EurioSpacing.s5,
                ),
            verticalArrangement = Arrangement.spacedBy(EurioSpacing.s6),
        ) {
            // Suggestions
            Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2)) {
                SectionLabel("Peut-être l'une de celles-ci")
                top5.forEachIndexed { idx, coin ->
                    SuggestionRow(rank = idx + 1, coin = coin, onClick = { onPickSuggestion(coin.eurioId) })
                }
            }

            // Face-value picker
            Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3)) {
                SectionLabel("Ou ajoute manuellement — valeur faciale")
                FaceValueChips(
                    selected = selectedCents,
                    onSelect = {
                        selectedCents = it
                        onPickFaceValue(it)
                    },
                )
            }

            // Actions
            Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2)) {
                Button(
                    onClick = onRetry,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(EurioRadii.full),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Gold,
                        contentColor = Ink,
                    ),
                ) {
                    Text("Essayer à nouveau")
                }
                OutlinedButton(
                    onClick = onReport,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(EurioRadii.full),
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = Color.White.copy(alpha = 0.85f),
                    ),
                ) {
                    Text(text = "Envoyer un signalement")
                }
            }
        }
    }
}

@Composable
private fun FrozenFrame() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color.Black.copy(alpha = 0.7f))
            .padding(vertical = EurioSpacing.s10),
        contentAlignment = Alignment.Center,
    ) {
        // Red ring outline (240dp)
        Box(
            modifier = Modifier
                .size(240.dp)
                .clip(CircleShape)
                .border(width = 1.5.dp, color = Danger.copy(alpha = 0.75f), shape = CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(160.dp)
                    .clip(CircleShape)
                    .background(Gold.copy(alpha = 0.12f)),
            )
        }
        Column(
            modifier = Modifier.align(Alignment.TopCenter).padding(top = EurioSpacing.s6),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = "NON IDENTIFIÉE",
                style = EyebrowStyle,
                color = Color.White.copy(alpha = 0.85f),
            )
            Text(
                text = "On n'a pas trouvé",
                style = MaterialTheme.typography.headlineMedium.copy(fontStyle = FontStyle.Italic),
                color = Color.White,
            )
        }
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text = text.uppercase(),
        style = EyebrowStyle,
        color = Color.White.copy(alpha = 0.45f),
    )
}

@Composable
private fun SuggestionRow(rank: Int, coin: CoinViewData, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.md))
            .background(Color.White.copy(alpha = 0.04f))
            .border(
                width = 1.dp,
                color = Color.White.copy(alpha = 0.08f),
                shape = RoundedCornerShape(EurioRadii.md),
            )
            .clickable(onClick = onClick)
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s3),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = rank.toString(),
            style = MonoBadgeStyle,
            color = Color.White.copy(alpha = 0.45f),
            modifier = Modifier.size(22.dp),
        )
        Text(
            text = coin.nameFr,
            style = MaterialTheme.typography.bodySmall.copy(fontStyle = FontStyle.Italic),
            color = Color.White.copy(alpha = 0.85f),
            modifier = Modifier.weight(1f),
        )
        Text(
            text = coin.country,
            style = MonoBadgeStyle,
            color = Warning,
        )
    }
}

@Composable
private fun FaceValueChips(selected: Int?, onSelect: (Int) -> Unit) {
    val values = listOf(1, 2, 5, 10, 20, 50, 100, 200)
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        values.forEach { cents ->
            val isSelected = selected == cents
            val bg = if (isSelected) Gold100 else Color.White.copy(alpha = 0.06f)
            val border = if (isSelected) Gold else Color.White.copy(alpha = 0.1f)
            val fg = if (isSelected) Gold else Color.White.copy(alpha = 0.88f)
            Box(
                modifier = Modifier
                    .weight(1f)
                    .clip(RoundedCornerShape(EurioRadii.full))
                    .background(bg)
                    .border(1.dp, border, RoundedCornerShape(EurioRadii.full))
                    .clickable { onSelect(cents) }
                    .padding(vertical = EurioSpacing.s2),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = if (cents >= 100) "${cents / 100}€" else "${cents}c",
                    style = MonoBadgeStyle,
                    color = fg,
                )
            }
        }
    }
}
