package com.musubi.eurio.features.scan.debug

import androidx.compose.foundation.layout.size
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

/**
 * Small floating button that opens [DebugBar].
 *
 * Persists the open/closed state across rotation via [rememberSaveable] so
 * benchmarking sessions aren't disrupted by recomposition.
 *
 * Caller is responsible for gating on [com.musubi.eurio.BuildConfig.DEBUG];
 * the FAB has no business existing in release.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebugBarLauncher(
    modifier: Modifier = Modifier,
    onOpenDevTool: ((DevTool) -> Unit)? = null,
) {
    var showSheet by rememberSaveable { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = false)
    val scope = rememberCoroutineScope()

    FloatingActionButton(
        onClick = { showSheet = true },
        containerColor = MaterialTheme.colorScheme.tertiary,
        contentColor = MaterialTheme.colorScheme.onTertiary,
        modifier = modifier.size(48.dp),
    ) {
        Text("DBG", style = MaterialTheme.typography.labelMedium)
    }

    if (showSheet) {
        DebugBar(
            sheetState = sheetState,
            onDismiss = {
                scope.launch { sheetState.hide() }
                showSheet = false
            },
            onOpenDevTool = onOpenDevTool?.let { handler ->
                { tool ->
                    scope.launch { sheetState.hide() }
                    showSheet = false
                    handler(tool)
                }
            },
        )
    }
}
