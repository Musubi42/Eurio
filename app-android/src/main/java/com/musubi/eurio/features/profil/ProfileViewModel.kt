package com.musubi.eurio.features.profil

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.data.repository.ProfileRepository
import com.musubi.eurio.data.repository.ProfileState
import com.musubi.eurio.domain.Grade
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn

class ProfileViewModel(
    profileRepository: ProfileRepository,
) : ViewModel() {

    val profileState: StateFlow<ProfileState?> = profileRepository.observeProfileState()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)
}
