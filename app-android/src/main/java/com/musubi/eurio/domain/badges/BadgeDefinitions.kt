package com.musubi.eurio.domain.badges

/**
 * Badge definitions — type-safe, evaluated against a pre-computed VaultSnapshot.
 * Runtime state (unlocked_at) is persisted separately in Room MetaDao.
 */
data class VaultSnapshot(
    val totalCoins: Int,
    val distinctCoins: Int,
    val countryCount: Int,
    val completedSets: Int,
    val bestStreak: Int,
    val currentStreak: Int,
)

data class BadgeDefinition(
    val id: String,
    val nameFr: String,
    val descriptionFr: String,
    val icon: String,
    val predicate: (VaultSnapshot) -> Boolean,
    val progressExtractor: ((VaultSnapshot) -> Pair<Int, Int>)? = null,
)

val BADGE_DEFINITIONS = listOf(
    BadgeDefinition(
        id = "first_scan",
        nameFr = "Premier scan",
        descriptionFr = "Ajouter ta première pièce au coffre",
        icon = "🎯",
        predicate = { it.totalCoins >= 1 },
    ),
    BadgeDefinition(
        id = "coins_10",
        nameFr = "Dix pièces",
        descriptionFr = "Posséder 10 pièces",
        icon = "🔟",
        predicate = { it.distinctCoins >= 10 },
        progressExtractor = { it.distinctCoins to 10 },
    ),
    BadgeDefinition(
        id = "coins_50",
        nameFr = "Cinquante pièces",
        descriptionFr = "Posséder 50 pièces",
        icon = "💰",
        predicate = { it.distinctCoins >= 50 },
        progressExtractor = { it.distinctCoins to 50 },
    ),
    BadgeDefinition(
        id = "coins_100",
        nameFr = "Cent pièces",
        descriptionFr = "Posséder 100 pièces",
        icon = "🏆",
        predicate = { it.distinctCoins >= 100 },
        progressExtractor = { it.distinctCoins to 100 },
    ),
    BadgeDefinition(
        id = "countries_5",
        nameFr = "5 pays",
        descriptionFr = "Posséder des pièces de 5 pays différents",
        icon = "🌍",
        predicate = { it.countryCount >= 5 },
        progressExtractor = { it.countryCount to 5 },
    ),
    BadgeDefinition(
        id = "countries_10",
        nameFr = "10 pays",
        descriptionFr = "Posséder des pièces de 10 pays différents",
        icon = "🗺️",
        predicate = { it.countryCount >= 10 },
        progressExtractor = { it.countryCount to 10 },
    ),
    BadgeDefinition(
        id = "eurozone_complete",
        nameFr = "Tour d'Europe",
        descriptionFr = "Au moins une pièce de chacun des 21 pays eurozone",
        icon = "🇪🇺",
        predicate = { it.countryCount >= 21 },
        progressExtractor = { it.countryCount to 21 },
    ),
    BadgeDefinition(
        id = "streak_7",
        nameFr = "Streak 7",
        descriptionFr = "7 jours consécutifs de scan",
        icon = "🔥",
        predicate = { it.bestStreak >= 7 },
        progressExtractor = { it.currentStreak to 7 },
    ),
    BadgeDefinition(
        id = "streak_30",
        nameFr = "Streak 30",
        descriptionFr = "30 jours consécutifs de scan",
        icon = "🔥",
        predicate = { it.bestStreak >= 30 },
        progressExtractor = { it.currentStreak to 30 },
    ),
    BadgeDefinition(
        id = "first_set",
        nameFr = "Premier set",
        descriptionFr = "Compléter ton premier set",
        icon = "⭐",
        predicate = { it.completedSets >= 1 },
    ),
    BadgeDefinition(
        id = "sets_5",
        nameFr = "5 sets complétés",
        descriptionFr = "Compléter 5 sets différents",
        icon = "🌟",
        predicate = { it.completedSets >= 5 },
        progressExtractor = { it.completedSets to 5 },
    ),
)
