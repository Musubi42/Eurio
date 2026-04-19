package com.musubi.eurio.domain

/**
 * App-wide events that cross feature boundaries.
 * Collected by MainActivity to show global Snackbar feedback.
 */
sealed class AppEvent {
    data class SetCompleted(val setName: String) : AppEvent()
    data class BadgeUnlocked(val badgeName: String, val icon: String) : AppEvent()
}
