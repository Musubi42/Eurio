package com.musubi.eurio.features.profil

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
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.musubi.eurio.data.repository.BadgeState
import com.musubi.eurio.data.repository.ProfileState
import com.musubi.eurio.domain.Grade
import com.musubi.eurio.ui.theme.EurioRadii
import com.musubi.eurio.ui.theme.EurioSpacing
import com.musubi.eurio.ui.theme.EyebrowStyle
import com.musubi.eurio.ui.theme.Gold
import com.musubi.eurio.ui.theme.Gold700
import com.musubi.eurio.ui.theme.GoldDeep
import com.musubi.eurio.ui.theme.GoldSoft
import com.musubi.eurio.ui.theme.Gray100
import com.musubi.eurio.ui.theme.Gray200
import com.musubi.eurio.ui.theme.Gray400
import com.musubi.eurio.ui.theme.Indigo700
import com.musubi.eurio.ui.theme.Indigo800
import com.musubi.eurio.ui.theme.Ink
import com.musubi.eurio.ui.theme.Ink300
import com.musubi.eurio.ui.theme.Ink400
import com.musubi.eurio.ui.theme.Ink500
import com.musubi.eurio.ui.theme.MonoBadgeStyle
import com.musubi.eurio.ui.theme.Paper
import com.musubi.eurio.ui.theme.PaperSurface
import com.musubi.eurio.ui.theme.PaperSurface1
import com.musubi.eurio.ui.theme.PaperSurface1

@Composable
fun ProfilScreen(viewModel: ProfileViewModel) {
    val state by viewModel.profileState.collectAsStateWithLifecycle()
    val debugMode by viewModel.debugMode.collectAsStateWithLifecycle()
    val language by viewModel.language.collectAsStateWithLifecycle()

    if (state == null) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = Gold)
        }
        return
    }

    val profile = state!!

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(PaperSurface)
            .verticalScroll(rememberScrollState()),
    ) {
        HeroSection(profile)
        BodySection(
            profile = profile,
            debugMode = debugMode,
            onToggleDebug = { viewModel.toggleDebugMode() },
            language = language,
            onLanguageChange = { viewModel.setLanguage(it) },
        )
    }
}

@Composable
private fun HeroSection(profile: ProfileState) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(Brush.verticalGradient(listOf(Indigo700, Indigo800))),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .padding(horizontal = EurioSpacing.s6)
                .padding(top = 24.dp, bottom = EurioSpacing.s10),
        ) {
            // Top bar
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(10.dp)
                            .clip(CircleShape)
                            .background(Brush.radialGradient(listOf(GoldSoft, Gold, GoldDeep))),
                    )
                    Text(
                        text = "Eurio",
                        style = MaterialTheme.typography.headlineMedium,
                        color = Color.White,
                    )
                }
            }

            Spacer(Modifier.height(EurioSpacing.s8))

            // Level eyebrow
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Box(Modifier.width(18.dp).height(1.dp).background(Gold))
                Text(
                    text = "NIVEAU · RANG ${profile.grade.ordinal_} DE ${Grade.entries.size}",
                    style = EyebrowStyle,
                    color = Gold,
                )
            }

            Spacer(Modifier.height(10.dp))

            Text(
                text = profile.grade.labelFr,
                style = MaterialTheme.typography.displayLarge.copy(
                    fontStyle = FontStyle.Italic,
                    fontWeight = FontWeight.Light,
                    lineHeight = 56.sp,
                ),
                color = Gold,
            )

            Text(
                text = "« ${profile.grade.captionFr} »",
                style = MaterialTheme.typography.bodySmall,
                color = Ink300,
                modifier = Modifier.padding(top = 10.dp),
            )

            Spacer(Modifier.height(EurioSpacing.s6))

            // Ladder progress
            GradeLadder(profile)
        }
    }
}

@Composable
private fun GradeLadder(profile: ProfileState) {
    val grades = Grade.entries
    val currentIdx = grades.indexOf(profile.grade)

    LinearProgressIndicator(
        progress = {
            val totalSteps = grades.size - 1
            if (totalSteps > 0) (currentIdx + profile.gradeProgressPercent) / totalSteps
            else 1f
        },
        modifier = Modifier
            .fillMaxWidth()
            .height(2.dp)
            .clip(RoundedCornerShape(2.dp)),
        color = Gold,
        trackColor = Color.White.copy(alpha = 0.08f),
        strokeCap = StrokeCap.Round,
    )

    Spacer(Modifier.height(14.dp))

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Bottom,
    ) {
        val next = profile.nextGrade
        Text(
            text = if (next != null) "${next.threshold - profile.distinctCoinCount} pièces pour ${next.labelFr}"
            else "Grade maximum atteint",
            style = MaterialTheme.typography.bodySmall,
            color = Ink300,
        )
        Text(
            text = "${(profile.gradeProgressPercent * 100).toInt()}%",
            style = MonoBadgeStyle,
            color = Gold,
        )
    }
}

@Composable
private fun BodySection(
    profile: ProfileState,
    debugMode: Boolean,
    onToggleDebug: () -> Unit,
    language: String,
    onLanguageChange: (String) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s6),
    ) {
        StatsGrid(profile, modifier = Modifier.offset(y = (-32).dp))

        Spacer(Modifier.height(EurioSpacing.s4))

        // Streak
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(EurioRadii.lg))
                .background(Paper)
                .border(1.dp, Gray100, RoundedCornerShape(EurioRadii.lg))
                .padding(EurioSpacing.s4),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s4),
        ) {
            Text(text = "🔥", fontSize = 32.sp)
            Column {
                Text(
                    text = "${profile.currentStreak} jours",
                    style = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.SemiBold),
                    color = Ink,
                )
                Text(
                    text = "Meilleur : ${profile.bestStreak} jours",
                    style = MaterialTheme.typography.bodySmall,
                    color = Ink500,
                )
            }
        }

        Spacer(Modifier.height(EurioSpacing.s7))

        // Badges
        BadgesSection(profile.badges)

        Spacer(Modifier.height(EurioSpacing.s7))

        // Settings
        SectionHeader("Paramètres")
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(EurioRadii.lg))
                .background(Paper)
                .border(1.dp, Gray100, RoundedCornerShape(EurioRadii.lg)),
        ) {
            LanguageSettingsRow(
                currentLang = language,
                onLanguageChange = onLanguageChange,
            )
            DebugSettingsRow(
                enabled = debugMode,
                onToggle = onToggleDebug,
            )
            SettingsRow("À propos", "v0.1.0")
        }

        Spacer(Modifier.height(EurioSpacing.s11))
    }
}

@Composable
private fun StatsGrid(profile: ProfileState, modifier: Modifier = Modifier) {
    Row(modifier = modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        StatCard("PIÈCES", profile.coinCount.toString(), modifier = Modifier.weight(1f))
        StatCard("PAYS", "${profile.countryCount}", "/21", Modifier.weight(1f))
        StatCard("VALEUR", "${profile.totalFaceValueCents / 100}", " €", Modifier.weight(1f))
    }
}

@Composable
private fun StatCard(label: String, value: String, suffix: String? = null, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(EurioRadii.lg))
            .background(PaperSurface)
            .border(1.dp, Gray100, RoundedCornerShape(EurioRadii.lg))
            .padding(horizontal = 12.dp, vertical = 14.dp),
    ) {
        Text(text = label, style = MonoBadgeStyle.copy(fontSize = 9.sp), color = Ink400)
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(text = value, style = MaterialTheme.typography.headlineLarge, color = Ink)
            if (suffix != null) Text(text = suffix, style = MaterialTheme.typography.bodyMedium, color = Gray400)
        }
    }
}

@Composable
private fun BadgesSection(badges: List<BadgeState>) {
    val unlocked = badges.filter { it.unlocked }
    val nextToUnlock = badges.filter { !it.unlocked && it.progressCurrent != null }.take(3)

    SectionHeader("Badges", "${unlocked.size} débloqués")

    if (unlocked.isNotEmpty()) {
        LazyRow(horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3)) {
            items(unlocked, key = { "b_${it.definition.id}" }) { badge ->
                BadgePill(badge)
            }
        }
        Spacer(Modifier.height(EurioSpacing.s4))
    }

    if (nextToUnlock.isNotEmpty()) {
        Text(text = "PROCHAINS", style = EyebrowStyle, color = Ink400, modifier = Modifier.padding(bottom = EurioSpacing.s2))
        nextToUnlock.forEach { badge ->
            NextBadgeCard(badge)
            Spacer(Modifier.height(EurioSpacing.s2))
        }
    }
}

@Composable
private fun BadgePill(badge: BadgeState) {
    Column(
        modifier = Modifier
            .clip(RoundedCornerShape(EurioRadii.lg))
            .background(Paper)
            .border(1.dp, Gold.copy(alpha = 0.3f), RoundedCornerShape(EurioRadii.lg))
            .padding(horizontal = EurioSpacing.s3, vertical = EurioSpacing.s3),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(CircleShape)
                .background(Brush.radialGradient(listOf(GoldSoft, Gold, GoldDeep))),
            contentAlignment = Alignment.Center,
        ) { Text(text = badge.definition.icon, fontSize = 20.sp) }
        Spacer(Modifier.height(6.dp))
        Text(text = badge.definition.nameFr, style = MaterialTheme.typography.labelSmall, color = Ink)
    }
}

@Composable
private fun NextBadgeCard(badge: BadgeState) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(EurioRadii.lg))
            .background(Paper)
            .border(1.dp, Gray100, RoundedCornerShape(EurioRadii.lg))
            .padding(horizontal = EurioSpacing.s4, vertical = EurioSpacing.s3),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s3),
    ) {
        Box(
            modifier = Modifier.size(44.dp).clip(CircleShape).background(Brush.radialGradient(listOf(Gray200, Gray400))),
            contentAlignment = Alignment.Center,
        ) { Text(text = badge.definition.icon, fontSize = 18.sp) }

        Column(modifier = Modifier.weight(1f)) {
            Text(text = badge.definition.nameFr, style = MaterialTheme.typography.titleSmall, color = Ink)
            Text(text = badge.definition.descriptionFr, style = MaterialTheme.typography.bodySmall, color = Ink400)
            if (badge.progressCurrent != null && badge.progressTarget != null) {
                Spacer(Modifier.height(EurioSpacing.s2))
                LinearProgressIndicator(
                    progress = { (badge.progressCurrent.toFloat() / badge.progressTarget).coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth().height(2.dp).clip(RoundedCornerShape(2.dp)),
                    color = Indigo700, trackColor = Gray100, strokeCap = StrokeCap.Round,
                )
            }
        }
        if (badge.progressCurrent != null && badge.progressTarget != null) {
            Text(text = "${badge.progressCurrent}/${badge.progressTarget}", style = MonoBadgeStyle, color = Ink400)
        }
    }
}

@Composable
private fun SectionHeader(title: String, action: String? = null) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(bottom = 14.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Bottom,
    ) {
        Text(text = title, style = MaterialTheme.typography.headlineMedium, color = Ink)
        if (action != null) Text(text = action, style = MonoBadgeStyle, color = Gold700)
    }
}

@Composable
private fun LanguageSettingsRow(
    currentLang: String,
    onLanguageChange: (String) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s4, vertical = 14.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "Langue",
            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
            color = Ink,
        )
        Row(
            horizontalArrangement = Arrangement.spacedBy(EurioSpacing.s2),
        ) {
            val options = listOf("fr" to "FR", "en" to "EN")
            options.forEach { (code, label) ->
                val selected = code == currentLang
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(EurioRadii.full))
                        .background(if (selected) Indigo700 else PaperSurface1)
                        .clickable { onLanguageChange(code) }
                        .padding(horizontal = 12.dp, vertical = 6.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = label,
                        style = MaterialTheme.typography.labelSmall,
                        color = if (selected) PaperSurface else Ink400,
                    )
                }
            }
        }
    }
}

@Composable
private fun DebugSettingsRow(
    enabled: Boolean,
    onToggle: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = EurioSpacing.s4, vertical = 10.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "Mode debug",
            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
            color = Ink,
        )
        Switch(
            checked = enabled,
            onCheckedChange = { onToggle() },
            colors = SwitchDefaults.colors(
                checkedThumbColor = Gold,
                checkedTrackColor = Indigo700,
            ),
        )
    }
}

@Composable
private fun SettingsRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = EurioSpacing.s4, vertical = 14.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = label, style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium), color = Ink)
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(text = value, style = MaterialTheme.typography.bodySmall, color = Ink400)
            Text(text = "›", color = Ink300)
        }
    }
}
