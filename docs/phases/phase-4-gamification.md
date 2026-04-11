# Phase 4 — Gamification & Achievements

> Objectif : rendre la collection addictive de manière organique. Les achievements récompensent la progression naturelle — jamais de dark patterns.

---

## 4.1 — Système de sets

### Sets MVP (5 sets)

| Set | Règle | Difficulté | Pièces requises |
|---|---|---|---|
| **Série complète [Pays]** | Toutes les pièces courantes d'un pays (1c à 2€) | Facile | 8 |
| **Eurozone founding** | Une pièce de chaque pays fondateur (2002) | Moyen | 12 |
| **Grande chasse** | Au moins 1 pièce de chaque pays euro | Difficile | 20 |
| **Commémoratives [Pays]** | Toutes les 2€ commémoratives d'un pays | Difficile | Variable |
| **Le Coffre d'or** | 10 pièces valant > 10x leur face | Très difficile | 10 |

### Stockage (Room)

```kotlin
@Entity(tableName = "achievement_sets")
data class AchievementSetEntity(
    @PrimaryKey val id: String,       // ex: "serie_france"
    val name: String,
    val description: String,
    val difficulty: String,
    val rules: String,                // JSON : critères de complétion
    val iconRes: String               // Nom de la resource drawable
)

@Entity(tableName = "user_achievements")
data class UserAchievementEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val setId: String,
    val progress: Float = 0f,         // 0.0 à 1.0
    val completedAt: Long? = null
)
```

### Calcul de progression

```kotlin
class AchievementEngine(
    private val coinDao: UserCoinDao,
    private val achievementDao: AchievementDao
) {
    // Recalculé à chaque ajout de pièce au coffre
    suspend fun recalculate(userCoins: List<UserCoinEntity>) {
        for (set in achievementDao.getAllSets()) {
            val progress = calculateProgress(set, userCoins)
            achievementDao.updateProgress(set.id, progress)

            // Notification si complété
            if (progress >= 1.0f && !set.isCompleted()) {
                achievementDao.markCompleted(set.id)
                emitCompletionEvent(set)
            }
        }
    }

    private fun calculateProgress(
        set: AchievementSetEntity,
        coins: List<UserCoinEntity>
    ): Float {
        val rules = Json.decodeFromString<SetRules>(set.rules)
        return when (rules.type) {
            "country_series" -> {
                val required = rules.requiredCoins  // [1c, 2c, ..., 2€]
                val owned = coins.filter { it.country == rules.country }
                    .map { it.faceValue }.distinct()
                owned.size.toFloat() / required.size
            }
            "multi_country" -> {
                val requiredCountries = rules.countries
                val ownedCountries = coins.map { it.country }.distinct()
                ownedCountries.intersect(requiredCountries).size.toFloat() /
                    requiredCountries.size
            }
            "value_multiplier" -> {
                val qualifying = coins.filter {
                    (it.currentValue ?: 0.0) > it.faceValue * rules.multiplier
                }
                minOf(qualifying.size.toFloat() / rules.count, 1.0f)
            }
            else -> 0f
        }
    }
}
```

---

## 4.2 — Niveaux de collectionneur

| Niveau | Critère |
|---|---|
| Découvreur | 1-10 pièces uniques |
| Passionné | 11-50 pièces + 1 set complété |
| Expert | 51-200 pièces + 3 sets complétés |
| Maître | 200+ pièces + 5 sets complétés + 1 pièce très rare |

```kotlin
fun calculateLevel(coinCount: Int, completedSets: Int, hasVeryRare: Boolean): CollectorLevel {
    return when {
        coinCount >= 200 && completedSets >= 5 && hasVeryRare -> CollectorLevel.MASTER
        coinCount >= 51 && completedSets >= 3 -> CollectorLevel.EXPERT
        coinCount >= 11 && completedSets >= 1 -> CollectorLevel.PASSIONATE
        else -> CollectorLevel.DISCOVERER
    }
}
```

---

## 4.3 — UI Gamification (Compose)

### Badge wall

```kotlin
@Composable
fun BadgeWall(achievements: List<AchievementUiState>) {
    LazyVerticalGrid(columns = GridCells.Fixed(4)) {
        items(achievements) { achievement ->
            BadgeItem(
                icon = achievement.icon,
                name = achievement.name,
                progress = achievement.progress,
                isCompleted = achievement.isCompleted,
                modifier = Modifier.clickable {
                    // Naviguer vers le détail du set
                }
            )
        }
    }
}

@Composable
fun BadgeItem(icon: Painter, name: String, progress: Float, isCompleted: Boolean) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box {
            Image(
                painter = icon,
                alpha = if (isCompleted) 1f else 0.3f
            )
            if (!isCompleted) {
                CircularProgressIndicator(progress = progress)
            }
        }
        Text(name, style = MaterialTheme.typography.labelSmall)
    }
}
```

### Détail de set

```kotlin
@Composable
fun SetDetailScreen(set: AchievementSetDetail) {
    Column {
        Text(set.name, style = MaterialTheme.typography.headlineMedium)
        LinearProgressIndicator(progress = set.progress)
        Text("${set.ownedCount}/${set.totalCount}")

        // Liste des pièces (acquises et manquantes)
        set.coins.forEach { coin ->
            Row {
                Icon(
                    if (coin.owned) Icons.Filled.CheckCircle
                    else Icons.Outlined.Circle
                )
                Text(coin.name)
            }
        }

        // Hint pour les pièces manquantes
        if (set.missingCoins.isNotEmpty()) {
            Text(
                "Pièces manquantes — regarde dans ton porte-monnaie !",
                style = MaterialTheme.typography.bodySmall
            )
        }
    }
}
```

---

## 4.4 — Notifications locales

```kotlin
// Pas de push serveur pour le MVP — notifications locales uniquement
fun showAchievementNotification(context: Context, setName: String) {
    val notification = NotificationCompat.Builder(context, CHANNEL_ID)
        .setContentTitle("Set complété !")
        .setContentText("$setName — Badge débloqué")
        .setSmallIcon(R.drawable.ic_badge)
        .build()

    NotificationManagerCompat.from(context).notify(/* id */, notification)
}
```

---

## 4.5 — Livrables Phase 4

- [ ] 5 sets définis avec règles JSON
- [ ] `AchievementEngine` : calcul auto de progression
- [ ] Système de niveaux (4 niveaux)
- [ ] Badge wall dans le profil
- [ ] Vue détail de set (acquis / manquants)
- [ ] Notifications locales de progression
- [ ] Animation de déblocage (Compose animation)
- [ ] Recalcul automatique à chaque ajout au coffre

---

## Durée estimée

**5-7 jours**
- 2-3 jours : logique achievements + Room
- 2-3 jours : UI (badge wall, détail set, animations)
- 1 jour : notifications locales + intégration avec le coffre
