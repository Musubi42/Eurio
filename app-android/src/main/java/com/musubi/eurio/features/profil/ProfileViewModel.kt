package com.musubi.eurio.features.profil

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.musubi.eurio.data.local.dao.MetaDao
import com.musubi.eurio.data.repository.ProfileRepository
import com.musubi.eurio.data.repository.ProfileState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class ProfileViewModel(
    profileRepository: ProfileRepository,
    private val metaDao: MetaDao? = null,
) : ViewModel() {

    val profileState: StateFlow<ProfileState?> = profileRepository.observeProfileState()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    private val _debugMode = MutableStateFlow(false)
    val debugMode: StateFlow<Boolean> = _debugMode.asStateFlow()

    private val _language = MutableStateFlow("fr")
    val language: StateFlow<String> = _language.asStateFlow()

    init {
        viewModelScope.launch {
            _debugMode.value = metaDao?.getBoolean("debug_mode") ?: false
            _language.value = metaDao?.getString("language") ?: "fr"
        }
    }

    fun toggleDebugMode() {
        val newValue = !_debugMode.value
        _debugMode.value = newValue
        viewModelScope.launch {
            metaDao?.putBoolean("debug_mode", newValue)
        }
    }

    fun setLanguage(lang: String) {
        _language.value = lang
        viewModelScope.launch {
            metaDao?.putString("language", lang)
        }
    }
}
