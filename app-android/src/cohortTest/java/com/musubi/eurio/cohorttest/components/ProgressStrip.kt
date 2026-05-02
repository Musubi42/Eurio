package com.musubi.eurio.cohorttest.components

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.musubi.eurio.cohorttest.TestPrescription
import com.musubi.eurio.cohorttest.TestResult
import com.musubi.eurio.ui.theme.Danger
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Ink200
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink700
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Success

/**
 * Strip of segments above the hero card showing per-test status at a
 * glance. Mirrors the proto `.progress-strip`.
 *
 * Each segment maps to one test in [tests]:
 *   pending      → Ink200, 4dp
 *   done correct → Success, 4dp
 *   done wrong   → Danger, 4dp
 *   current      → Indigo700, 6dp + slow-pulsing halo
 *
 * The mono meta-row above shows the "TEST NN / N · X faits · A ✓ · B ✗"
 * counter line.
 */
@Composable
fun ProgressStrip(
    tests: List<TestPrescription>,
    results: Map<Int, TestResult>,
    currentIdx: Int,
    modifier: Modifier = Modifier,
) {
    val total = tests.size
    val correct = results.values.count { it.isCorrect && it.error == null }
    val wrong = results.values.count { !it.isCorrect && it.error == null }
    // R@1 sous la règle d'équivalence design_group (cf. EquivalenceMap.kt).
    // Toujours >= correct ; quand la cohorte ne partage aucun design_group
    // (cas standard), eq == strict et le compteur est silencieux.
    val correctEq = results.values.count { it.isCorrectEq && it.error == null }
    val done = results.size

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Bottom,
        ) {
            val padIdx = currentIdx.toString().padStart(2, '0')
            val padTotal = total.toString().padStart(2, '0')
            Text(
                "TEST $padIdx / $padTotal",
                style = MonoBadgeStyle.copy(color = Ink700, fontSize = 11.sp),
            )
            Row(
                horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "${done.toString().padStart(2, '0')} faits",
                    style = MonoBadgeStyle.copy(color = Ink400, fontSize = 11.sp),
                )
                Text(
                    "·",
                    style = MonoBadgeStyle.copy(color = Ink400, fontSize = 11.sp),
                )
                Text(
                    "$correct ✓",
                    style = MonoBadgeStyle.copy(color = Success, fontSize = 11.sp),
                )
                Text(
                    "$wrong ✗",
                    style = MonoBadgeStyle.copy(color = Danger, fontSize = 11.sp),
                )
                // Affiché uniquement quand la règle d'équivalence
                // design_group "rattrape" au moins un test ; pas de bruit
                // visuel dans une cohorte 100% strict.
                if (correctEq > correct) {
                    Text(
                        "$correctEq ≈",
                        style = MonoBadgeStyle.copy(color = Indigo700, fontSize = 11.sp),
                    )
                }
            }
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(10.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            tests.forEach { t ->
                val result = results[t.idx]
                val state: SegState = when {
                    t.idx == currentIdx -> SegState.Current
                    result == null -> SegState.Pending
                    result.error != null || !result.isCorrect -> SegState.Wrong
                    else -> SegState.Correct
                }
                Segment(
                    state = state,
                    modifier = Modifier
                        .weight(1f, fill = true)
                        .height(if (state == SegState.Current) 8.dp else 4.dp),
                )
            }
        }
    }
}

private enum class SegState { Pending, Correct, Wrong, Current }

@Composable
private fun Segment(state: SegState, modifier: Modifier = Modifier) {
    val color: Color = when (state) {
        SegState.Pending -> Ink200
        SegState.Correct -> Success
        SegState.Wrong -> Danger
        SegState.Current -> Indigo700
    }
    val transition = rememberInfiniteTransition(label = "current-pulse")
    val pulseAlpha by transition.animateFloat(
        initialValue = 0.18f,
        targetValue = 0.30f,
        animationSpec = infiniteRepeatable(
            animation = tween(1100),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulse",
    )
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(999.dp))
            .background(
                if (state == SegState.Current) Indigo700.copy(alpha = pulseAlpha)
                else Color.Transparent,
            ),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(if (state == SegState.Current) 6.dp else 4.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(color),
        )
    }
}
