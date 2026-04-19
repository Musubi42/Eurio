package com.musubi.eurio.features.onboarding

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.musubi.eurio.features.onboarding.pages.OnboardingPermissionPage
import com.musubi.eurio.features.onboarding.pages.OnboardingSlide1Page
import com.musubi.eurio.features.onboarding.pages.OnboardingSlide2Page
import com.musubi.eurio.features.onboarding.pages.OnboardingSlide3Page
import com.musubi.eurio.features.onboarding.pages.OnboardingSplashPage
import com.musubi.eurio.ui.theme.Indigo800
import kotlinx.coroutines.launch

// Host of the 5-step first-run onboarding flow (splash + 3 tutorial slides +
// camera permission pre-prompt). The ViewModel owns the "onboarding_completed"
// flag so NavHost can react by swapping startDestination.
//
// Proto parity: scenes/onboarding-{splash,1,2,3,permission}.html
private const val PAGE_SPLASH = 0
private const val PAGE_SLIDE_1 = 1
private const val PAGE_SLIDE_2 = 2
private const val PAGE_SLIDE_3 = 3
private const val PAGE_PERMISSION = 4
private const val TOTAL_PAGES = 5

@Composable
fun OnboardingScreen(
    viewModel: OnboardingViewModel,
    onComplete: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val pagerState = rememberPagerState(initialPage = PAGE_SPLASH) { TOTAL_PAGES }
    val scope = rememberCoroutineScope()
    val currentPage by viewModel.currentPage.collectAsStateWithLifecycle()

    // Mirror pager position → ViewModel so UI that needs the page index (e.g.
    // dot indicators rendered outside the pager) can observe it reactively.
    LaunchedEffect(pagerState) {
        snapshotFlow { pagerState.currentPage }.collect { viewModel.setCurrentPage(it) }
    }

    fun goTo(page: Int) {
        scope.launch { pagerState.animateScrollToPage(page) }
    }

    fun finish() {
        viewModel.completeOnboarding(onComplete)
    }

    // Hardware back on slides 2-3 returns to the previous page ; on splash or
    // slide 1 it defers to the system (exits the app). On the permission page
    // it also exits since no tutorial can precede the decision.
    BackHandler(enabled = currentPage in PAGE_SLIDE_2..PAGE_SLIDE_3) {
        goTo(currentPage - 1)
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(Indigo800),
    ) {
        HorizontalPager(
            state = pagerState,
            modifier = Modifier.fillMaxSize(),
            userScrollEnabled = false,
        ) { page ->
            when (page) {
                PAGE_SPLASH -> OnboardingSplashPage(
                    onAdvance = { goTo(PAGE_SLIDE_1) },
                )
                PAGE_SLIDE_1 -> OnboardingSlide1Page(
                    onNext = { goTo(PAGE_SLIDE_2) },
                    onSkip = { goTo(PAGE_PERMISSION) },
                )
                PAGE_SLIDE_2 -> OnboardingSlide2Page(
                    onNext = { goTo(PAGE_SLIDE_3) },
                    onBack = { goTo(PAGE_SLIDE_1) },
                    onSkip = { goTo(PAGE_PERMISSION) },
                )
                PAGE_SLIDE_3 -> OnboardingSlide3Page(
                    onNext = { goTo(PAGE_PERMISSION) },
                    onBack = { goTo(PAGE_SLIDE_2) },
                    onSkip = { goTo(PAGE_PERMISSION) },
                )
                PAGE_PERMISSION -> OnboardingPermissionPage(
                    onComplete = { finish() },
                    onSkip = { finish() },
                )
            }
        }
    }
}
