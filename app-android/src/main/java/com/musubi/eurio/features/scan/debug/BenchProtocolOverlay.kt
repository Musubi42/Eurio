package com.musubi.eurio.features.scan.debug

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import com.musubi.eurio.ml.bench.BenchProtocolState
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing

/**
 * Top band of the guided bench protocol overlay — shows the current
 * cell label and a Quit button. Caller aligns to `Alignment.TopCenter`.
 *
 * Visual is deliberately blunt — debug surface, not user-facing UX.
 */
@Composable
fun BenchProtocolHeader(
    state: BenchProtocolState,
    onQuit: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(EurioSpacing.s2)
            .clip(RoundedCornerShape(EurioRadii.sm))
            .background(Color.Black.copy(alpha = 0.7f))
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s2),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        if (state.isComplete) {
            Text(
                text = "Protocole terminé · ${state.doneCount} done, ${state.skippedCount} skipped",
                style = MaterialTheme.typography.labelMedium,
                color = Color.White,
                modifier = Modifier.weight(1f),
            )
            OutlinedButton(
                onClick = onQuit,
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
            ) { Text("Fermer") }
        } else {
            val cell = state.currentCell
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Bench ${state.currentIndex + 1}/${state.totalCells}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.tertiary,
                )
                Text(
                    text = cell?.coin?.displayName ?: "?",
                    style = MaterialTheme.typography.labelLarge,
                    color = Color.White,
                )
                Text(
                    text = cell?.condition?.label ?: "?",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.White.copy(alpha = 0.75f),
                )
            }
            OutlinedButton(
                onClick = onQuit,
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
            ) { Text("Quitter") }
        }
    }
}

/**
 * Bottom band — Start / Done / Skip controls. Caller aligns to
 * `Alignment.BottomCenter`. Renders nothing when the protocol is
 * complete (header banner handles the wrap-up).
 */
@Composable
fun BenchProtocolActions(
    state: BenchProtocolState,
    onStart: () -> Unit,
    onDone: () -> Unit,
    onSkip: () -> Unit,
    modifier: Modifier = Modifier,
) {
    if (state.isComplete) return
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(EurioSpacing.s2)
            .clip(RoundedCornerShape(EurioRadii.sm))
            .background(Color.Black.copy(alpha = 0.7f))
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s2),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        when (state.currentStatus) {
            BenchProtocolState.CellStatus.PENDING -> {
                Button(
                    onClick = onStart,
                    modifier = Modifier.weight(1f),
                ) { Text("Démarrer") }
                OutlinedButton(
                    onClick = onSkip,
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
                ) { Text("Skip") }
            }
            BenchProtocolState.CellStatus.IN_PROGRESS -> {
                Button(
                    onClick = onDone,
                    modifier = Modifier.weight(1f),
                ) { Text("Terminer") }
                OutlinedButton(
                    onClick = onSkip,
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
                ) { Text("Skip") }
            }
            else -> Unit
        }
    }
}
