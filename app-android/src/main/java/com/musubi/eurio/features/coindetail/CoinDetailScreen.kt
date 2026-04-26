package com.musubi.eurio.features.coindetail

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import com.musubi.eurio.data.repository.CoinViewData
import com.musubi.eurio.data.repository.SetWithProgress
import com.musubi.eurio.features.scan.components.Coin3DViewer
import com.musubi.eurio.ui.theme.Danger
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.PaperSurface1
import com.musubi.eurio.ui.theme.Success

@Composable
fun CoinDetailScreen(
    viewModel: CoinDetailViewModel,
    fromScan: Boolean,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(PaperSurface),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = EurioSpacing.s5),
        ) {
            TopBar(onBack = onBack)

            when {
                state.loading -> LoadingBlock()
                state.error != null -> ErrorBlock(state.error!!)
                state.coin != null -> CoinContent(
                    coin = state.coin!!,
                    alreadyOwned = state.alreadyOwned,
                    sets = state.sets,
                    fromScan = fromScan,
                    onAddToVault = { viewModel.onAddToVault() },
                    onRemoveFromVault = { viewModel.showRemoveDialog() },
                )
            }

            Spacer(Modifier.height(EurioSpacing.s10))
        }

        // Remove confirmation dialog
        if (state.showRemoveDialog) {
            RemoveConfirmDialog(
                coinName = state.coin?.nameFr ?: "",
                onConfirm = { viewModel.confirmRemove() },
                onDismiss = { viewModel.dismissRemoveDialog() },
            )
        }
    }
}

@Composable
private fun TopBar(onBack: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = EurioSpacing.s3, bottom = EurioSpacing.s2),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(36.dp)
                .clip(CircleShape)
                .background(PaperSurface1)
                .border(1.dp, Ink.copy(alpha = 0.06f), CircleShape)
                .clickable { onBack() },
            contentAlignment = Alignment.Center,
        ) {
            Text(text = "←", style = MaterialTheme.typography.titleMedium, color = Ink)
        }
    }
}

@Composable
private fun LoadingBlock() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = EurioSpacing.s10),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator(color = Gold)
    }
}

@Composable
private fun ErrorBlock(message: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = EurioSpacing.s10),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = Ink500,
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun CoinContent(
    coin: CoinViewData,
    alreadyOwned: Boolean,
    sets: List<SetWithProgress>,
    fromScan: Boolean,
    onAddToVault: () -> Unit,
    onRemoveFromVault: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(EurioSpacing.s4))

        // Phase 6 : full 3D viewer when we have an obverse photo, else fall
        // back to the legacy gold-disc carousel. Manipulable (orbit/zoom) and
        // does NOT play the discovery flip — that's reserved for the scan
        // accept moment to keep the gesture meaningful.
        if (coin.imageObverseUrl != null) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(360.dp)
                    .clip(RoundedCornerShape(EurioRadii.lg))
                    .background(Ink),
            ) {
                Coin3DViewer(
                    eurioId = coin.eurioId,
                    obverseImageUrl = coin.imageObverseUrl,
                    reverseImageUrl = coin.imageReverseUrl,
                    obverseMeta = coin.obversePhotoMeta,
                    reverseMeta = coin.reversePhotoMeta,
                    modifier = Modifier.fillMaxSize(),
                )
            }
        } else {
            CoinImageCarousel(coin = coin)
        }

        Spacer(Modifier.height(EurioSpacing.s5))

        // Name
        Text(
            text = coin.nameFr,
            style = MaterialTheme.typography.displaySmall.copy(fontStyle = FontStyle.Italic),
            color = Ink,
        )

        Spacer(Modifier.height(EurioSpacing.s2))

        // Meta eyebrow
        Text(
            text = formatMetaLine(coin),
            style = EyebrowStyle,
            color = Ink400,
        )

        // Identity section
        Spacer(Modifier.height(EurioSpacing.s5))
        IdentitySection(coin)

        // Description
        if (!coin.designDescription.isNullOrBlank()) {
            Spacer(Modifier.height(EurioSpacing.s5))
            SectionHeader("DESCRIPTION")
            Spacer(Modifier.height(EurioSpacing.s2))
            Text(
                text = coin.designDescription,
                style = MaterialTheme.typography.bodyMedium,
                color = Ink500,
            )
        }

        // Sets membership
        if (sets.isNotEmpty()) {
            Spacer(Modifier.height(EurioSpacing.s5))
            SectionHeader("SETS")
            Spacer(Modifier.height(EurioSpacing.s2))
            sets.forEach { set ->
                SetMembershipRow(set)
                Spacer(Modifier.height(EurioSpacing.s2))
            }
        }

        // Vault actions
        Spacer(Modifier.height(EurioSpacing.s6))
        if (alreadyOwned) {
            OwnedPill()
            Spacer(Modifier.height(EurioSpacing.s3))
            OutlinedButton(
                onClick = onRemoveFromVault,
                border = ButtonDefaults.outlinedButtonBorder(enabled = true).copy(
                    brush = androidx.compose.ui.graphics.SolidColor(Danger.copy(alpha = 0.5f)),
                ),
                shape = RoundedCornerShape(EurioRadii.full),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = "Retirer du coffre",
                    color = Danger,
                    style = MaterialTheme.typography.labelLarge,
                )
            }
        } else {
            Button(
                onClick = onAddToVault,
                colors = ButtonDefaults.buttonColors(
                    containerColor = Gold,
                    contentColor = Ink,
                ),
                shape = RoundedCornerShape(EurioRadii.full),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
            ) {
                Text(
                    text = "Ajouter au coffre",
                    style = MaterialTheme.typography.titleMedium,
                )
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun CoinImageCarousel(coin: CoinViewData) {
    val hasObverse = coin.imageObverseUrl != null
    // CoinViewData doesn't expose imageReverseUrl yet, so single-page for now
    val pageCount = if (hasObverse) 1 else 1

    Box(
        modifier = Modifier.size(180.dp),
        contentAlignment = Alignment.Center,
    ) {
        val coinShape = CircleShape
        if (hasObverse) {
            AsyncImage(
                model = coin.imageObverseUrl,
                contentDescription = coin.nameFr,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .fillMaxSize()
                    .clip(coinShape)
                    .background(PaperSurface1)
                    .border(1.dp, Gold.copy(alpha = 0.35f), coinShape),
            )
        } else {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .clip(coinShape)
                    .background(PaperSurface1)
                    .border(1.dp, Gold.copy(alpha = 0.35f), coinShape),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = formatFaceValue(coin.faceValueCents),
                    style = MaterialTheme.typography.displaySmall.copy(fontStyle = FontStyle.Italic),
                    color = GoldDeep,
                )
            }
        }
    }
}

@Composable
private fun IdentitySection(coin: CoinViewData) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.lg))
            .background(PaperSurface1)
            .padding(EurioSpacing.s4),
        verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        IdentityRow("Pays", coin.country.uppercase())
        IdentityRow("Année", if (coin.year > 0) coin.year.toString() else "—")
        IdentityRow("Valeur faciale", formatFaceValue(coin.faceValueCents))
        IdentityRow("Type", when (coin.issueType) {
            "commemo" -> "Commémorative"
            else -> "Circulation"
        })
    }
}

@Composable
private fun IdentityRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = Ink500,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            color = Ink,
        )
    }
}

@Composable
private fun SetMembershipRow(set: SetWithProgress) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.md))
            .background(PaperSurface1)
            .padding(EurioSpacing.s3),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = set.nameFr,
            style = MaterialTheme.typography.bodyMedium,
            color = Ink,
            modifier = Modifier.weight(1f),
        )
        Text(
            text = "${set.owned}/${set.total}",
            style = EyebrowStyle,
            color = if (set.isComplete) Success else Ink400,
        )
    }
}

@Composable
private fun SectionHeader(title: String) {
    Text(
        text = title,
        style = EyebrowStyle,
        color = Ink400,
    )
}

@Composable
private fun OwnedPill() {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(EurioRadii.full))
            .background(Success.copy(alpha = 0.15f))
            .border(1.dp, Success.copy(alpha = 0.4f), RoundedCornerShape(EurioRadii.full))
            .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s3),
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = "✓", style = MaterialTheme.typography.titleMedium, color = Success)
        Text(
            text = "Déjà dans ton coffre",
            style = MaterialTheme.typography.labelLarge,
            color = Success,
        )
    }
}

@Composable
private fun RemoveConfirmDialog(
    coinName: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                text = "Retirer du coffre ?",
                style = MaterialTheme.typography.titleLarge,
            )
        },
        text = {
            Text(
                text = "\"$coinName\" sera retiré de ta collection. Tu pourras toujours le rescanner plus tard.",
                style = MaterialTheme.typography.bodyMedium,
                color = Ink500,
            )
        },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text("Retirer", color = Danger)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Annuler", color = Indigo700)
            }
        },
        containerColor = PaperSurface,
    )
}

private fun formatFaceValue(cents: Int): String {
    return when {
        cents <= 0 -> "—"
        cents < 100 -> "${cents}c"
        cents % 100 == 0 -> "${cents / 100}€"
        else -> "%.2f€".format(cents / 100.0)
    }
}

private fun formatMetaLine(coin: CoinViewData): String {
    val pieces = mutableListOf<String>()
    if (coin.country.isNotBlank()) pieces += coin.country.uppercase()
    if (coin.year > 0) pieces += coin.year.toString()
    pieces += formatFaceValue(coin.faceValueCents)
    return pieces.joinToString(" · ")
}
