package com.musubi.eurio.features.onboarding.pages

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CameraAlt
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.musubi.eurio.features.onboarding.components.EurioWordmark
import com.musubi.eurio.features.onboarding.components.OnboardingSkipButton
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.FrauncesFamily
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.GoldSoft
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.InkSoft
import com.musubi.eurio.ui.theme.Indigo400
import com.musubi.eurio.ui.theme.Indigo500
import com.musubi.eurio.ui.theme.Indigo600
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Indigo800
import com.musubi.eurio.ui.theme.Indigo900
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.PaperSurface

// Proto parity: docs/design/prototype/scenes/onboarding-permission.html
// Duolingo-style pre-prompt — explains camera usage BEFORE triggering the
// native Android dialog. On "Autoriser" we launch the native dialog; on
// "Plus tard" we finish onboarding anyway (permission is re-requested at
// first scan by ScanScreen's own inline check).
@Composable
fun OnboardingPermissionPage(
    onComplete: () -> Unit,
    onSkip: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current

    val launcher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { _ ->
        // Accept or deny — either way, onboarding is done.
        onComplete()
    }

    val alreadyGranted = ContextCompat.checkSelfPermission(
        context,
        Manifest.permission.CAMERA,
    ) == PackageManager.PERMISSION_GRANTED

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(Ink),
    ) {
        DimmedViewfinderBackdrop(modifier = Modifier.fillMaxSize())

        // Top bar
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(
                    start = EurioSpacing.s6,
                    end = EurioSpacing.s6,
                    top = 52.dp,
                ),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            EurioWordmark()
            OnboardingSkipButton(label = "Annuler", onClick = onSkip)
        }

        // Bottom sheet
        PermissionSheet(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth(),
            onAllow = {
                if (alreadyGranted) {
                    onComplete()
                } else {
                    launcher.launch(Manifest.permission.CAMERA)
                }
            },
            onLater = onComplete,
        )
    }
}

@Composable
private fun DimmedViewfinderBackdrop(modifier: Modifier = Modifier) {
    val transition = rememberInfiniteTransition(label = "permissionDash")
    val alpha by transition.animateFloat(
        initialValue = 0.4f,
        targetValue = 0.85f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 4000, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "permissionDashAlpha",
    )

    Box(
        modifier = modifier.background(
            Brush.radialGradient(
                colors = listOf(InkSoft, Ink, Color.Black),
                center = Offset.Unspecified,
                radius = 1400f,
            ),
        ),
    ) {
        // Animated dashed circle centered at ~35% height
        Canvas(modifier = Modifier.fillMaxSize()) {
            val cx = size.width / 2f
            val cy = size.height * 0.35f
            val r = 110.dp.toPx()
            drawCircle(
                color = Gold.copy(alpha = alpha * 0.55f),
                radius = r,
                center = Offset(cx, cy),
                style = Stroke(
                    width = 1.5.dp.toPx(),
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(16f, 10f)),
                ),
            )
        }

        Text(
            text = "Pointer une pièce",
            style = MaterialTheme.typography.bodyMedium.copy(
                fontFamily = FrauncesFamily,
                fontStyle = FontStyle.Italic,
                color = Color.White.copy(alpha = 0.55f),
                fontSize = 14.sp,
                letterSpacing = 0.6.sp,
            ),
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 250.dp),
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun PermissionSheet(
    onAllow: () -> Unit,
    onLater: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .clip(
                RoundedCornerShape(
                    topStart = EurioRadii.r2xl,
                    topEnd = EurioRadii.r2xl,
                ),
            )
            .background(
                Brush.verticalGradient(
                    colors = listOf(Indigo600, Indigo700, Indigo800),
                ),
            )
            .padding(
                top = EurioSpacing.s3,
                start = EurioSpacing.s6,
                end = EurioSpacing.s6,
                bottom = EurioSpacing.s9,
            ),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // Grab handle
        Box(
            modifier = Modifier
                .width(40.dp)
                .height(4.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(Color.White.copy(alpha = 0.2f)),
        )

        Spacer(Modifier.height(EurioSpacing.s5))

        // Camera icon square
        Box(
            modifier = Modifier
                .size(64.dp)
                .clip(RoundedCornerShape(EurioRadii.lg))
                .background(
                    Brush.verticalGradient(
                        colors = listOf(Indigo500, Indigo800),
                    ),
                )
                .border(1.dp, Gold.copy(alpha = 0.45f), RoundedCornerShape(EurioRadii.lg)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Outlined.CameraAlt,
                contentDescription = null,
                tint = Gold,
                modifier = Modifier.size(30.dp),
            )
        }

        Spacer(Modifier.height(EurioSpacing.s4))

        Text(
            text = "Autoriser l'appareil photo.",
            style = MaterialTheme.typography.displaySmall.copy(
                fontFamily = FrauncesFamily,
                fontStyle = FontStyle.Italic,
                color = PaperSurface,
                fontSize = 28.sp,
                lineHeight = 30.sp,
            ),
            textAlign = TextAlign.Center,
        )

        Spacer(Modifier.height(EurioSpacing.s2))

        Text(
            text = "Eurio a besoin de la caméra pour reconnaître tes pièces. Tout se passe sur ton téléphone.",
            style = MaterialTheme.typography.bodyMedium.copy(
                color = Color.White.copy(alpha = 0.65f),
                fontSize = 14.sp,
                lineHeight = 20.sp,
            ),
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = EurioSpacing.s4),
        )

        Spacer(Modifier.height(EurioSpacing.s6))

        // Promises list
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
        ) {
            PromiseRow("Scan 100 % on-device, aucune connexion requise.")
            PromiseRow("Aucune photo n'est envoyée ni stockée.")
            PromiseRow("Aucun compte, aucun email, jamais.")
        }

        Spacer(Modifier.height(EurioSpacing.s6))

        // Primary CTA — indigo gradient, gold trim
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(EurioRadii.lg))
                .background(
                    Brush.verticalGradient(
                        colors = listOf(Indigo400, Indigo700, Indigo900),
                    ),
                )
                .border(
                    1.dp,
                    Gold.copy(alpha = 0.4f),
                    RoundedCornerShape(EurioRadii.lg),
                )
                .clickable(onClick = onAllow)
                .defaultMinSize(minHeight = 52.dp)
                .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s4),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Autoriser la caméra",
                    style = MaterialTheme.typography.titleMedium.copy(
                        color = GoldSoft,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 16.sp,
                    ),
                )
                Spacer(Modifier.width(EurioSpacing.s2))
                Text(
                    text = "→",
                    style = MaterialTheme.typography.titleMedium.copy(
                        color = GoldSoft,
                        fontSize = 16.sp,
                    ),
                )
            }
        }

        Spacer(Modifier.height(EurioSpacing.s3))

        // Secondary ghost
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(EurioRadii.lg))
                .clickable(onClick = onLater)
                .defaultMinSize(minHeight = 44.dp)
                .padding(horizontal = EurioSpacing.s5, vertical = EurioSpacing.s3),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "Plus tard",
                style = MaterialTheme.typography.titleSmall.copy(
                    color = Color.White.copy(alpha = 0.7f),
                    fontWeight = FontWeight.Medium,
                    fontSize = 14.sp,
                ),
            )
        }

        Spacer(Modifier.height(EurioSpacing.s5))

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(Gold.copy(alpha = 0.25f)),
        )
        Spacer(Modifier.height(EurioSpacing.s3))
        Text(
            text = "🛡  CONFIDENTIALITÉ BY DESIGN · ANDROID PERMISSION NATIVE",
            style = MonoBadgeStyle.copy(
                color = Color.White.copy(alpha = 0.38f),
                fontSize = 9.sp,
                letterSpacing = 1.2.sp,
            ),
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun PromiseRow(text: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.md))
            .background(Color.White.copy(alpha = 0.04f))
            .border(1.dp, Color.White.copy(alpha = 0.08f), RoundedCornerShape(EurioRadii.md))
            .padding(EurioSpacing.s3),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        Box(
            modifier = Modifier
                .size(22.dp)
                .clip(CircleShape)
                .background(Gold.copy(alpha = 0.18f))
                .border(1.dp, Gold.copy(alpha = 0.4f), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "✓",
                style = MaterialTheme.typography.labelSmall.copy(
                    color = Gold,
                    fontSize = 12.sp,
                ),
            )
        }
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium.copy(
                color = Color.White.copy(alpha = 0.9f),
                fontSize = 14.sp,
            ),
            modifier = Modifier.weight(1f),
        )
    }
}
