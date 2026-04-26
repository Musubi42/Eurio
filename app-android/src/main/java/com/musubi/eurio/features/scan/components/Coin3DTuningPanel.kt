package com.musubi.eurio.features.scan.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
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
import com.musubi.eurio.ui.theme.Success

/**
 * Floating tune button shown in carousel debug mode. Toggles the
 * [Coin3DTuningPanel] above it. Visual language matches the rest of the
 * debug overlay — monospace + green accent — so it reads as a debug
 * affordance, not a production control.
 */
@Composable
fun Coin3DTuneFab(
    open: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val borderColor = if (open) Success.copy(alpha = 0.65f) else Color.White.copy(alpha = 0.18f)
    val bg = if (open) Success.copy(alpha = 0.18f) else Color.Black.copy(alpha = 0.78f)
    val textColor = if (open) Success else Color.White.copy(alpha = 0.92f)
    Row(
        modifier = modifier
            .clip(CircleShape)
            .background(bg)
            .border(width = 1.dp, color = borderColor, shape = CircleShape)
            .clickable(onClick = onClick)
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s2),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
    ) {
        Text(text = "⚙", style = MonoBadgeStyle, color = textColor)
        Text(text = "Tune", style = MonoBadgeStyle, color = textColor)
    }
}

/**
 * Live PBR + exposure tuning panel for [Coin3DViewer]. Mirrors the proto
 * sliders (Relief / Metalness / Roughness / Exposure) — values stream into
 * the viewer through [Coin3DTuning] and apply within one frame because the
 * underlying Filament MaterialInstances are updated in place.
 */
@Composable
fun Coin3DTuningPanel(
    tuning: Coin3DTuning,
    onChange: (Coin3DTuning) -> Unit,
    onReset: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.sm))
            .background(Color.Black.copy(alpha = 0.82f))
            .border(
                width = 1.dp,
                color = Success.copy(alpha = 0.30f),
                shape = RoundedCornerShape(EurioRadii.sm),
            )
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s2),
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s1),
    ) {
        TuningSlider(
            label = "Relief",
            value = tuning.relief,
            range = Coin3DTuning.RELIEF_MIN..Coin3DTuning.RELIEF_MAX,
            onChange = { onChange(tuning.copy(relief = it)) },
        )
        TuningSlider(
            label = "Metalness",
            value = tuning.metallic,
            range = 0f..1f,
            onChange = { onChange(tuning.copy(metallic = it)) },
        )
        TuningSlider(
            label = "Roughness",
            value = tuning.roughness,
            range = 0f..1f,
            onChange = { onChange(tuning.copy(roughness = it)) },
        )
        TuningSlider(
            label = "Exposure",
            value = tuning.exposure,
            range = Coin3DTuning.EXPOSURE_MIN..Coin3DTuning.EXPOSURE_MAX,
            onChange = { onChange(tuning.copy(exposure = it)) },
        )
        Spacer(modifier = Modifier.height(EurioSpacing.s1))
        Row(
            modifier = Modifier
                .clip(RoundedCornerShape(3.dp))
                .border(
                    width = 1.dp,
                    color = Color.White.copy(alpha = 0.18f),
                    shape = RoundedCornerShape(3.dp),
                )
                .clickable(onClick = onReset)
                .padding(horizontal = EurioSpacing.s2, vertical = EurioSpacing.s1)
                .align(Alignment.End),
        ) {
            Text(
                text = "Reset",
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.85f),
            )
        }
    }
}

@Composable
private fun TuningSlider(
    label: String,
    value: Float,
    range: ClosedFloatingPointRange<Float>,
    onChange: (Float) -> Unit,
) {
    Column(modifier = Modifier.width(260.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = label.uppercase(),
                style = MonoBadgeStyle,
                color = Color.White.copy(alpha = 0.55f),
            )
            Text(
                text = "%.2f".format(value),
                style = MonoBadgeStyle,
                color = Gold,
            )
        }
        Slider(
            value = value,
            onValueChange = onChange,
            valueRange = range,
            modifier = Modifier.height(28.dp),
            colors = SliderDefaults.colors(
                thumbColor = Gold,
                activeTrackColor = Gold.copy(alpha = 0.7f),
                inactiveTrackColor = Color.White.copy(alpha = 0.18f),
            ),
        )
    }
}
