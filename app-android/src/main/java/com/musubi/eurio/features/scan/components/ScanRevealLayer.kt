package com.musubi.eurio.features.scan.components

import androidx.compose.animation.core.animate
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.util.lerp
import androidx.compose.ui.zIndex
import com.musubi.eurio.data.repository.CoinViewData
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold300
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Indigo900
import com.musubi.eurio.ui.theme.Indigo950
import com.musubi.eurio.ui.theme.Success
import kotlin.math.roundToInt
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/**
 * Reveal stratifié — portage Compose de la scène proto `ScanReveal.vue`
 * (sheet 2 crans + hero 3D persistant).
 *
 * Chunk A (charpente) :
 *  - un SEUL [Coin3DViewer], dont l'offset Y + la hauteur sont interpolés par la
 *    fraction d'ouverture du sheet (peek → bande haute pleine ; déployé → header
 *    du sheet, réduit). On n'émule PAS le reparent DOM du web — la SceneView
 *    Filament reste une instance unique animée par modifier (cf. notes de port).
 *  - bottom sheet 2 crans (peek ↔ déployé) avec drag main-roulé sur la poignée
 *    (mêmes maths que le proto : tap = toggle, drag franc sous le peek = dismiss).
 *  - swipe-down sous le peek → [onRescan] (= dismiss carte → la caméra reprend).
 *  - contenu peek (eyebrow / valeur / drives + CTA) ; corps déployé = placeholder
 *    jusqu'au Chunk B (extraction du `CoinDetailBody` partagé).
 *
 * Non couvert ici (Chunk A.5 / chunks suivants) : auto-add + undo (découplage VM),
 * jalons (overlay célébration), valeur de marché réelle dans le peek.
 */
@Composable
fun ScanRevealLayer(
    coin: CoinViewData,
    onCtaAdd: () -> Unit,
    onRescan: () -> Unit,
    modifier: Modifier = Modifier,
) {
    BoxWithConstraints(modifier = modifier.fillMaxSize()) {
        val density = LocalDensity.current
        val containerH = constraints.maxHeight.toFloat()

        // ── Géométrie du sheet (px) ──
        // peek ~42 % de la hauteur (le proto clamp 0.26..0.44, mais notre CTA garde
        // 88dp de marge nav → on prend le haut de la fourchette) ; déployé 92 %.
        val peekHpx = containerH * 0.42f
        val expandedHpx = containerH * 0.92f
        val peekTop = containerH - peekHpx
        val expandedTop = containerH - expandedHpx
        val dismissThresholdPx = with(density) { 64.dp.toPx() }
        // ScanScreen est déjà insété au-dessus de la bottom-nav du shell : il suffit
        // d'un coussin court pour décoller le CTA du bord (le proto met 88px car sa
        // nav vit dans la même surface).
        val navPad = 24.dp

        val scope = rememberCoroutineScope()
        // offsetY = position Y du haut du sheet depuis le haut du conteneur.
        // Float state piloté en synchrone par le drag (PAS d'Animatable.snapTo par
        // event : des coroutines snapTo concurrentes s'annulent → le drag ne bouge
        // plus). Le settle utilise `animate(...)`, annulé au début d'un nouveau drag.
        // Clé sur l'eurioId : chaque nouvelle pièce identifiée repart en peek.
        var offsetY by remember(coin.eurioId) { mutableFloatStateOf(peekTop) }
        var settleJob by remember(coin.eurioId) { mutableStateOf<Job?>(null) }
        // Re-clamp si la taille du conteneur change (rotation, insets).
        LaunchedEffect(peekTop, expandedTop) {
            offsetY = offsetY.coerceIn(expandedTop, peekTop)
        }

        // frac 0 = peek, 1 = déployé.
        val frac = ((peekTop - offsetY) / (peekTop - expandedTop)).coerceIn(0f, 1f)

        fun settleTo(target: Float) {
            settleJob?.cancel()
            settleJob = scope.launch {
                animate(offsetY, target, animationSpec = spring()) { v, _ -> offsetY = v }
            }
        }

        // ── Hero 3D (instance unique, interpolée par frac) ──
        val heroPeekHpx = containerH * 0.42f
        val heroExpandedHpx = with(density) { 180.dp.toPx() }
        // Déployé : la pièce se loge sous le titre, en haut du sheet.
        val heroTopExpandedPx = expandedTop + with(density) { 104.dp.toPx() }
        val heroTopPx = lerp(0f, heroTopExpandedPx, frac)
        val heroHpx = lerp(heroPeekHpx, heroExpandedHpx, frac)

        Coin3DViewer(
            eurioId = coin.eurioId,
            obverseImageUrl = coin.imageObverseUrl,
            reverseImageUrl = coin.imageReverseUrl,
            obverseMeta = coin.obversePhotoMeta,
            reverseMeta = coin.reversePhotoMeta,
            flipKey = coin.eurioId,
            isOpaque = false,
            modifier = Modifier
                .fillMaxWidth()
                .height(with(density) { heroHpx.toDp() })
                .offset { IntOffset(0, heroTopPx.roundToInt()) }
                .zIndex(2f),
        )

        // ── Titre « bande » (peek) : sous la pièce, s'efface en se déployant ──
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .offset { IntOffset(0, (containerH * 0.40f).roundToInt()) }
                .padding(horizontal = 24.dp)
                .alpha(1f - frac),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            RevealTitle(coin)
        }

        // ── Bottom sheet ──
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .offset { IntOffset(0, offsetY.roundToInt()) }
                .height(with(density) { (containerH - offsetY).coerceAtLeast(0f).toDp() })
                .zIndex(1f)
                .clip(RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp))
                .background(
                    Brush.verticalGradient(
                        0f to Indigo700.copy(alpha = 0.55f),
                        0.16f to Indigo900.copy(alpha = 0.94f),
                        1f to Indigo950.copy(alpha = 0.98f),
                    ),
                )
                .border(
                    width = 1.dp,
                    color = Color.White.copy(alpha = 0.10f),
                    shape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp),
                ),
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                // Poignée : un SEUL pointerInput gère tap ET drag (mêmes maths que le
                // proto : `moved < slop` → tap/toggle, sinon drag). Empiler
                // clickable + draggable se vole le pointeur et affame le drag.
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        // Zone tactile ≥44dp (le grip visuel reste fin) pour une
                        // poignée confortable au doigt.
                        .height(44.dp)
                        .pointerInput(peekTop, expandedTop) {
                            val slop = viewConfiguration.touchSlop
                            awaitEachGesture {
                                val down = awaitFirstDown()
                                settleJob?.cancel()
                                var moved = 0f
                                var isDrag = false
                                while (true) {
                                    val event = awaitPointerEvent()
                                    val change = event.changes.firstOrNull { it.id == down.id }
                                        ?: break
                                    if (!change.pressed) break
                                    val dy = change.positionChange().y
                                    moved += kotlin.math.abs(dy)
                                    if (!isDrag && moved > slop) isDrag = true
                                    if (isDrag) {
                                        offsetY = (offsetY + dy)
                                            .coerceIn(expandedTop, peekTop + dismissThresholdPx + 80f)
                                        change.consume()
                                    }
                                }
                                if (!isDrag) {
                                    // Toggle basé sur offsetY (lu en direct) : `frac`
                                    // serait figé (pointerInput non re-clé sur offsetY).
                                    settleTo(
                                        if (offsetY > (peekTop + expandedTop) / 2f) expandedTop
                                        else peekTop,
                                    )
                                } else {
                                    val o = offsetY
                                    when {
                                        o > peekTop + dismissThresholdPx -> onRescan()
                                        o < (peekTop + expandedTop) / 2f -> settleTo(expandedTop)
                                        else -> settleTo(peekTop)
                                    }
                                }
                            }
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    Box(
                        modifier = Modifier
                            .width(lerp(42f, 30f, frac).dp)
                            .height(4.dp)
                            .clip(CircleShape)
                            .background(Color.White.copy(alpha = lerp(0.32f, 0.22f, frac))),
                    )
                }

                // Zone scrollable (résumé + corps).
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 20.dp),
                ) {
                    // Titre « sheet » (déployé) : apparaît en haut au-dessus de la pièce.
                    if (frac > 0.02f) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .alpha(frac),
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            RevealTitle(coin)
                        }
                        // Réserve l'espace occupé par la pièce (overlay) en déployé.
                        Spacer(Modifier.height(with(density) { (heroExpandedHpx * frac).toDp() } + 8.dp))
                    }

                    RevealSummary(coin)

                    // Corps de fiche — placeholder Chunk A (extraction CoinDetailBody = Chunk B).
                    Spacer(Modifier.height(20.dp))
                    Text(
                        text = "Fiche détaillée",
                        style = MaterialTheme.typography.labelSmall,
                        color = Gold300,
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        text = "Récit, valorisation, sets, design et caractéristiques arrivent au Chunk B (corps de fiche partagé).",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color.White.copy(alpha = 0.55f),
                    )
                    Spacer(Modifier.height(24.dp))
                }

                // CTA épinglé en bas, au-dessus de la navbar.
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(start = 20.dp, end = 20.dp, top = 12.dp, bottom = navPad),
                ) {
                    Button(
                        onClick = onCtaAdd,
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(percent = 50),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = Gold,
                            contentColor = Ink,
                        ),
                    ) {
                        Text("Ajouter au coffre")
                    }
                }
            }
        }
    }
}

@Composable
private fun RevealTitle(coin: CoinViewData) {
    Text(
        text = "${coin.country.uppercase()} · ${coin.year}",
        style = MaterialTheme.typography.labelSmall,
        color = Color.White.copy(alpha = 0.55f),
        textAlign = TextAlign.Center,
    )
    Spacer(Modifier.height(3.dp))
    Text(
        text = coin.nameFr,
        style = MaterialTheme.typography.headlineSmall.copy(fontStyle = FontStyle.Italic),
        color = Color.White,
        textAlign = TextAlign.Center,
    )
}

@Composable
private fun RevealSummary(coin: CoinViewData) {
    val isCommemo = coin.issueType == "commemo"
    Text(
        text = "Nouvelle pièce",
        style = MaterialTheme.typography.labelSmall,
        color = Gold300,
    )
    Spacer(Modifier.height(6.dp))
    Row(verticalAlignment = Alignment.Bottom) {
        Text(
            text = "≈ ${formatFaceEuro(coin.faceValueCents)}",
            style = MaterialTheme.typography.headlineSmall.copy(fontStyle = FontStyle.Italic),
            color = Gold300,
        )
        Spacer(Modifier.width(10.dp))
        Text(
            text = if (isCommemo) "COMMÉMORATIVE" else "COURANTE",
            style = MaterialTheme.typography.labelSmall,
            color = Color.White.copy(alpha = 0.55f),
        )
    }
    Spacer(Modifier.height(14.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        RevealDrive("Nouvelle", accent = false, success = true)
        RevealDrive(coin.country, accent = false, success = false)
        RevealDrive(if (isCommemo) "Commémorative" else "Circulation", accent = true, success = false)
    }
}

@Composable
private fun RevealDrive(text: String, accent: Boolean, success: Boolean) {
    val bg = when {
        success -> Success.copy(alpha = 0.18f)
        accent -> Gold.copy(alpha = 0.14f)
        else -> Color.White.copy(alpha = 0.06f)
    }
    val border = when {
        success -> Success.copy(alpha = 0.5f)
        accent -> Gold300.copy(alpha = 0.4f)
        else -> Color.White.copy(alpha = 0.10f)
    }
    val fg = when {
        success -> Color(0xFF6FE0A8)
        accent -> Gold300
        else -> Color.White.copy(alpha = 0.85f)
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(percent = 50))
            .background(bg)
            .border(1.dp, border, RoundedCornerShape(percent = 50))
            .padding(horizontal = 11.dp, vertical = 6.dp),
    ) {
        Text(text = text, style = MaterialTheme.typography.labelSmall, color = fg)
    }
}

private fun formatFaceEuro(cents: Int): String = when {
    cents >= 100 && cents % 100 == 0 -> "${cents / 100} €"
    cents >= 100 -> "${"%.2f".format(cents / 100.0).replace('.', ',')} €"
    else -> "$cents c"
}
