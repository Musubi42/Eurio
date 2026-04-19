package com.musubi.eurio.features.onboarding

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.EurioApp
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class OnboardingViewModel(
    private val app: EurioApp,
) : ViewModel() {

    private val _currentPage = MutableStateFlow(0)
    val currentPage: StateFlow<Int> = _currentPage.asStateFlow()

    fun setCurrentPage(page: Int) {
        _currentPage.value = page
    }

    // Persists onboarding_completed and invokes [onDone] on the main thread
    // once Room has acknowledged the write. NavHost swaps startDestination
    // reactively via EurioApp.onboardingCompleted so [onDone] is only used
    // for imperative post-completion navigation (popUpTo onboarding).
    fun completeOnboarding(onDone: () -> Unit) {
        viewModelScope.launch {
            app.markOnboardingCompleted()
            onDone()
        }
    }
}
