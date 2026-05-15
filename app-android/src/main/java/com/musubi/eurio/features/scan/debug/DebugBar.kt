package com.musubi.eurio.features.scan.debug

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.RadioButton
import androidx.compose.material3.SheetState
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.musubi.eurio.ui.theme.EurioSpacing

/**
 * Debug-only bottom-sheet exposing every tunable knob of the best-frame
 * pipeline. See [DebugScanConfig] for the schema.
 *
 * Sliders move and toggles flip even before the consuming pipeline exists
 * (chunks 2-6) — at this chunk the sheet is "functional but inert".
 *
 * Caller is responsible for never rendering this in a release build.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebugBar(
    sheetState: SheetState,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val config by DebugScanConfigStore.config.collectAsStateWithLifecycle()

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        modifier = modifier,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = EurioSpacing.s4, vertical = EurioSpacing.s2),
            verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        ) {
            Text(
                text = "DEBUG · best-frame capture",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )

            SectionHeader("Trigger")
            TriggerSection(config)

            SectionDivider()
            SectionHeader("Capture")
            CaptureSection(config)

            SectionDivider()
            SectionHeader("Lock")
            LockSection(config)

            SectionDivider()
            SectionHeader("Quality gates")
            QualityGatesSection(config)

            SectionDivider()
            SectionHeader("Record")
            RecordSection(config)

            SectionDivider()
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = EurioSpacing.s4),
                horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3, Alignment.End),
            ) {
                TextButton(onClick = { DebugScanConfigStore.reset() }) {
                    Text("Reset to defaults")
                }
                TextButton(onClick = onDismiss) { Text("Close") }
            }
        }
    }
}

// ── Sections ─────────────────────────────────────────────────────────────────

@Composable
private fun TriggerSection(config: DebugScanConfig) {
    Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s1)) {
        TriggerRadio(
            label = "OFF (continu actuel)",
            selected = config.triggerMode == TriggerMode.OFF,
            onSelect = { DebugScanConfigStore.update { it.copy(triggerMode = TriggerMode.OFF) } },
        )
        TriggerRadio(
            label = "Box stability",
            selected = config.triggerMode == TriggerMode.BOX_STABILITY,
            onSelect = { DebugScanConfigStore.update { it.copy(triggerMode = TriggerMode.BOX_STABILITY) } },
        )
        LabeledSlider(
            label = "  IoU min",
            value = config.stabilityIouMin,
            valueRange = 0.30f..0.95f,
            steps = 12,
            formatter = { "%.2f".format(it) },
            onValueChange = { v -> DebugScanConfigStore.update { it.copy(stabilityIouMin = v) } },
        )
        LabeledSlider(
            label = "  N frames",
            value = config.stabilityNFrames.toFloat(),
            valueRange = 2f..8f,
            steps = 5,
            formatter = { "${it.toInt()}" },
            onValueChange = { v -> DebugScanConfigStore.update { it.copy(stabilityNFrames = v.toInt()) } },
        )
        TriggerRadio(
            label = "YOLO confidence",
            selected = config.triggerMode == TriggerMode.YOLO_CONFIDENCE,
            onSelect = { DebugScanConfigStore.update { it.copy(triggerMode = TriggerMode.YOLO_CONFIDENCE) } },
        )
        LabeledSlider(
            label = "  conf min",
            value = config.yoloConfMin,
            valueRange = 0.20f..0.95f,
            steps = 14,
            formatter = { "%.2f".format(it) },
            onValueChange = { v -> DebugScanConfigStore.update { it.copy(yoloConfMin = v) } },
        )
        TriggerRadio(
            label = "ArcFace consensus",
            selected = config.triggerMode == TriggerMode.ARCFACE_CONSENSUS,
            onSelect = { DebugScanConfigStore.update { it.copy(triggerMode = TriggerMode.ARCFACE_CONSENSUS) } },
        )
    }
}

@Composable
private fun CaptureSection(config: DebugScanConfig) {
    Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s1)) {
        CaptureRadio(
            label = "Preview only",
            selected = config.captureMode == CaptureMode.PREVIEW_ONLY,
            onSelect = { DebugScanConfigStore.update { it.copy(captureMode = CaptureMode.PREVIEW_ONLY) } },
        )
        CaptureRadio(
            label = "ImageCapture full",
            selected = config.captureMode == CaptureMode.IMAGECAPTURE_FULL,
            onSelect = { DebugScanConfigStore.update { it.copy(captureMode = CaptureMode.IMAGECAPTURE_FULL) } },
        )
        CaptureRadio(
            label = "Both parallel",
            selected = config.captureMode == CaptureMode.BOTH_PARALLEL,
            onSelect = { DebugScanConfigStore.update { it.copy(captureMode = CaptureMode.BOTH_PARALLEL) } },
        )
        LabeledSlider(
            label = "Burst size",
            value = config.burstSize.toFloat(),
            valueRange = 1f..10f,
            steps = 8,
            formatter = { "${it.toInt()}" },
            onValueChange = { v -> DebugScanConfigStore.update { it.copy(burstSize = v.toInt()) } },
        )
        LabeledSwitch(
            label = "Rolling buffer",
            checked = config.rollingBufferEnabled,
            onCheckedChange = { v -> DebugScanConfigStore.update { it.copy(rollingBufferEnabled = v) } },
        )
    }
}

@Composable
private fun LockSection(config: DebugScanConfig) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s4),
    ) {
        LockToggle(
            label = "AE",
            checked = config.aeLockEnabled,
            onCheckedChange = { v -> DebugScanConfigStore.update { it.copy(aeLockEnabled = v) } },
        )
        LockToggle(
            label = "AF",
            checked = config.afLockEnabled,
            onCheckedChange = { v -> DebugScanConfigStore.update { it.copy(afLockEnabled = v) } },
        )
        LockToggle(
            label = "AWB",
            checked = config.awbLockEnabled,
            onCheckedChange = { v -> DebugScanConfigStore.update { it.copy(awbLockEnabled = v) } },
        )
    }
}

@Composable
private fun QualityGatesSection(config: DebugScanConfig) {
    Column(verticalArrangement = Arrangement.spacedBy(EurioSpacing.s1)) {
        LabeledSlider(
            label = "Sharpness min",
            value = config.sharpnessMin,
            valueRange = 0f..500f,
            steps = 0,
            formatter = { "${it.toInt()}" },
            onValueChange = { v -> DebugScanConfigStore.update { it.copy(sharpnessMin = v) } },
        )
        LabeledSlider(
            label = "Exposure band ±",
            value = config.exposureBandHalfWidth,
            valueRange = 0.05f..0.45f,
            steps = 7,
            formatter = { "%.2f".format(it) },
            onValueChange = { v -> DebugScanConfigStore.update { it.copy(exposureBandHalfWidth = v) } },
        )
        LabeledSlider(
            label = "Completeness min",
            value = config.completenessMin,
            valueRange = 0.80f..1.00f,
            steps = 19,
            formatter = { "%.2f".format(it) },
            onValueChange = { v -> DebugScanConfigStore.update { it.copy(completenessMin = v) } },
        )
        LabeledSwitch(
            label = "Motion gate",
            checked = config.motionEnabled,
            onCheckedChange = { v -> DebugScanConfigStore.update { it.copy(motionEnabled = v) } },
        )
    }
}

@Composable
private fun RecordSection(config: DebugScanConfig) {
    LabeledSwitch(
        label = "Record session (JSONL + frames)",
        checked = config.recordEnabled,
        onCheckedChange = { v -> DebugScanConfigStore.update { it.copy(recordEnabled = v) } },
    )
}

// ── Primitives ───────────────────────────────────────────────────────────────

@Composable
private fun SectionHeader(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun SectionDivider() {
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}

@Composable
private fun TriggerRadio(label: String, selected: Boolean, onSelect: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        RadioButton(selected = selected, onClick = onSelect)
        Text(text = label, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun CaptureRadio(label: String, selected: Boolean, onSelect: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        RadioButton(selected = selected, onClick = onSelect)
        Text(text = label, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun LabeledSlider(
    label: String,
    value: Float,
    valueRange: ClosedFloatingPointRange<Float>,
    steps: Int,
    formatter: (Float) -> String,
    onValueChange: (Float) -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.width(140.dp),
        )
        Slider(
            value = value,
            onValueChange = onValueChange,
            valueRange = valueRange,
            steps = steps,
            modifier = Modifier.weight(1f),
        )
        Box(modifier = Modifier.width(56.dp), contentAlignment = Alignment.CenterEnd) {
            Text(
                text = formatter(value),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun LabeledSwitch(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(text = label, style = MaterialTheme.typography.bodyMedium)
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}

@Composable
private fun LockToggle(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(end = EurioSpacing.s2),
        )
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}
