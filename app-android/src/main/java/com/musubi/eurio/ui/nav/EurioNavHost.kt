package com.musubi.eurio.ui.nav

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.musubi.eurio.BuildConfig
import com.musubi.eurio.EurioApp
import com.musubi.eurio.data.repository.CoinRepository
import com.musubi.eurio.data.repository.SetRepository
import com.musubi.eurio.data.repository.StreakRepository
import com.musubi.eurio.data.repository.VaultRepository
import com.musubi.eurio.features.catalog.CatalogCountryScreen
import com.musubi.eurio.features.catalog.CatalogCountryViewModel
import com.musubi.eurio.features.catalog.CatalogViewModel
import com.musubi.eurio.features.coffre.CoffreScreen
import com.musubi.eurio.features.coffre.CoffreViewModel
import com.musubi.eurio.features.coindetail.CoinDetailScreen
import com.musubi.eurio.features.coindetail.CoinDetailViewModel
import com.musubi.eurio.features.profil.ProfileViewModel
import com.musubi.eurio.features.profil.ProfilScreen
import com.musubi.eurio.features.scan.ScanScreen
import com.musubi.eurio.features.scan.ScanViewModel
import com.musubi.eurio.features.sets.SetDetailScreen
import com.musubi.eurio.features.sets.SetDetailViewModel
import com.musubi.eurio.features.sets.SetsListViewModel
import com.musubi.eurio.ml.CoinAnalyzer

@Composable
fun EurioNavHost(
    navController: NavHostController,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val app = context.applicationContext as EurioApp

    NavHost(
        navController = navController,
        startDestination = EurioDestinations.SCAN,
        modifier = modifier,
    ) {
        composable(EurioDestinations.SCAN) {
            val scanVm: ScanViewModel = viewModel(
                factory = ScanViewModelFactory(
                    coinRepository = app.coinRepository,
                    vaultRepository = app.vaultRepository,
                    streakRepository = app.streakRepository,
                    coinAnalyzer = app.coinAnalyzer,
                ),
            )

            // Bind the analyzer → VM callback BEFORE ScanScreen composes
            // (CameraPreview starts CameraX in AndroidView.factory, which
            // runs during composition — the delegate must be ready by then).
            remember(scanVm) {
                app.scanCallbackRelay.delegate = scanVm::onScanResult
            }
            DisposableEffect(scanVm) {
                onDispose { app.scanCallbackRelay.delegate = null }
            }

            ScanScreen(
                viewModel = scanVm,
                versionName = BuildConfig.VERSION_NAME,
                onOpenCoinDetail = { eurioId ->
                    navController.navigate(
                        EurioDestinations.coinDetail(eurioId, fromScan = true)
                    )
                },
            )
        }

        composable(EurioDestinations.COFFRE) {
            val coffreVm: CoffreViewModel = viewModel(
                factory = CoffreViewModelFactory(
                    vaultRepository = app.vaultRepository,
                ),
            )
            val setsListVm: SetsListViewModel = viewModel(
                factory = SetsListViewModelFactory(
                    setRepository = app.setRepository,
                ),
            )
            val catalogVm: CatalogViewModel = viewModel(
                factory = CatalogViewModelFactory(
                    catalogRepository = app.catalogRepository,
                ),
            )

            CoffreScreen(
                viewModel = coffreVm,
                setsListViewModel = setsListVm,
                catalogViewModel = catalogVm,
                onNavigateToScan = {
                    navController.navigate(EurioDestinations.SCAN) {
                        popUpTo(EurioDestinations.COFFRE) { inclusive = false }
                    }
                },
                onNavigateToCoinDetail = { eurioId ->
                    navController.navigate(
                        EurioDestinations.coinDetail(eurioId, fromScan = false)
                    )
                },
                onNavigateToSetDetail = { setId ->
                    navController.navigate(EurioDestinations.setDetail(setId))
                },
                onNavigateToCatalogCountry = { countryCode ->
                    navController.navigate(EurioDestinations.catalogCountry(countryCode))
                },
            )
        }

        composable(EurioDestinations.PROFIL) {
            val profileVm: ProfileViewModel = viewModel(
                factory = ProfileViewModelFactory(
                    profileRepository = app.profileRepository,
                ),
            )
            ProfilScreen(viewModel = profileVm)
        }

        composable(
            route = EurioDestinations.SET_DETAIL_ROUTE,
            arguments = listOf(
                navArgument(EurioDestinations.SET_DETAIL_ARG_SET_ID) {
                    type = NavType.StringType
                },
            ),
        ) { entry ->
            val setId = entry.arguments
                ?.getString(EurioDestinations.SET_DETAIL_ARG_SET_ID)
                .orEmpty()

            val setDetailVm: SetDetailViewModel = viewModel(
                factory = SetDetailViewModelFactory(
                    setId = setId,
                    setRepository = app.setRepository,
                    vaultRepository = app.vaultRepository,
                ),
            )

            SetDetailScreen(
                viewModel = setDetailVm,
                onBack = { navController.popBackStack() },
                onCoinClick = { eurioId ->
                    navController.navigate(
                        EurioDestinations.coinDetail(eurioId, fromScan = false)
                    )
                },
            )
        }

        composable(
            route = EurioDestinations.CATALOG_COUNTRY_ROUTE,
            arguments = listOf(
                navArgument(EurioDestinations.CATALOG_COUNTRY_ARG) {
                    type = NavType.StringType
                },
            ),
        ) { entry ->
            val countryCode = entry.arguments
                ?.getString(EurioDestinations.CATALOG_COUNTRY_ARG)
                .orEmpty()

            val catalogCountryVm: CatalogCountryViewModel = viewModel(
                factory = CatalogCountryViewModelFactory(
                    countryCode = countryCode,
                    catalogRepository = app.catalogRepository,
                    vaultRepository = app.vaultRepository,
                ),
            )

            CatalogCountryScreen(
                countryCode = countryCode,
                viewModel = catalogCountryVm,
                onBack = { navController.popBackStack() },
                onCoinClick = { eurioId ->
                    navController.navigate(
                        EurioDestinations.coinDetail(eurioId, fromScan = false)
                    )
                },
            )
        }

        composable(
            route = EurioDestinations.COIN_DETAIL_ROUTE,
            arguments = listOf(
                navArgument(EurioDestinations.COIN_DETAIL_ARG_EURIO_ID) {
                    type = NavType.StringType
                },
                navArgument(EurioDestinations.COIN_DETAIL_ARG_FROM_SCAN) {
                    type = NavType.BoolType
                    defaultValue = false
                },
            ),
        ) { entry ->
            val eurioId = entry.arguments
                ?.getString(EurioDestinations.COIN_DETAIL_ARG_EURIO_ID)
                .orEmpty()
            val fromScan = entry.arguments
                ?.getBoolean(EurioDestinations.COIN_DETAIL_ARG_FROM_SCAN)
                ?: false

            val detailVm: CoinDetailViewModel = viewModel(
                factory = CoinDetailViewModelFactory(
                    eurioId = eurioId,
                    coinRepository = app.coinRepository,
                    vaultRepository = app.vaultRepository,
                    setRepository = app.setRepository,
                ),
            )

            CoinDetailScreen(
                viewModel = detailVm,
                fromScan = fromScan,
                onBack = { navController.popBackStack() },
            )
        }
    }
}

private class ScanViewModelFactory(
    private val coinRepository: CoinRepository,
    private val vaultRepository: VaultRepository,
    private val streakRepository: StreakRepository,
    private val coinAnalyzer: CoinAnalyzer,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return ScanViewModel(
            coinRepository = coinRepository,
            vaultRepository = vaultRepository,
            streakRepository = streakRepository,
            coinAnalyzer = coinAnalyzer,
        ) as T
    }
}

private class CoinDetailViewModelFactory(
    private val eurioId: String,
    private val coinRepository: CoinRepository,
    private val vaultRepository: VaultRepository,
    private val setRepository: SetRepository,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return CoinDetailViewModel(
            eurioId = eurioId,
            coinRepository = coinRepository,
            vaultRepository = vaultRepository,
            setRepository = setRepository,
        ) as T
    }
}

private class CoffreViewModelFactory(
    private val vaultRepository: VaultRepository,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return CoffreViewModel(
            vaultRepository = vaultRepository,
        ) as T
    }
}

private class SetsListViewModelFactory(
    private val setRepository: SetRepository,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return SetsListViewModel(
            setRepository = setRepository,
        ) as T
    }
}

private class SetDetailViewModelFactory(
    private val setId: String,
    private val setRepository: SetRepository,
    private val vaultRepository: VaultRepository,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return SetDetailViewModel(
            setId = setId,
            setRepository = setRepository,
            vaultRepository = vaultRepository,
        ) as T
    }
}

private class CatalogViewModelFactory(
    private val catalogRepository: com.musubi.eurio.data.repository.CatalogRepository,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return CatalogViewModel(
            catalogRepository = catalogRepository,
        ) as T
    }
}

private class CatalogCountryViewModelFactory(
    private val countryCode: String,
    private val catalogRepository: com.musubi.eurio.data.repository.CatalogRepository,
    private val vaultRepository: VaultRepository,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return CatalogCountryViewModel(
            countryCode = countryCode,
            catalogRepository = catalogRepository,
            vaultRepository = vaultRepository,
        ) as T
    }
}

private class ProfileViewModelFactory(
    private val profileRepository: com.musubi.eurio.data.repository.ProfileRepository,
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return ProfileViewModel(
            profileRepository = profileRepository,
        ) as T
    }
}
