package com.musubi.eurio.domain

/**
 * Collection grade based on total distinct coins owned.
 * Thresholds from phase-5-profile-gamification.md.
 */
enum class Grade(
    val threshold: Int,
    val labelFr: String,
    val captionFr: String,
    val ordinal_: Int,
) {
    DEBUTANT(0, "Débutant", "Ton aventure commence", 1),
    AMATEUR(5, "Amateur", "Les premiers pas sont faits", 2),
    COLLECTIONNEUR(25, "Collectionneur", "La passion se confirme", 3),
    NUMISMATE(50, "Numismate", "Un regard d'expert", 4),
    EXPERT(100, "Expert", "La collection prend forme", 5),
    MAITRE(200, "Maître", "Le coffre est légendaire", 6);

    companion object {
        fun forCoinCount(count: Int): Grade =
            entries.last { count >= it.threshold }

        fun nextGrade(current: Grade): Grade? {
            val idx = entries.indexOf(current)
            return if (idx < entries.lastIndex) entries[idx + 1] else null
        }
    }
}
