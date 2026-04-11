# Phase 5 — Polish & Beta

> Objectif : l'app est prête pour un test panel fermé. Onboarding fluide, edge cases gérés, navigation complète, UX finalisée.

---

## 5.1 — Onboarding

### Flow

```
Écran 1 — Splash animé
  "Eurio — Chaque pièce raconte une histoire"
  [Commencer]  [Skip →]

Écran 2 — Permission caméra
  "Scanne tes pièces pour découvrir leur valeur"
  → Demande permission Android
  → Si refusé : explication + bouton settings

Écran 3 — Premier scan
  → Ouverture directe sur la caméra
  → "Place une pièce devant la caméra"
  → Premier scan = premier "wow moment"
  → Proposition "Ajouter au Coffre"
```

Pas de compte obligatoire. Scan et collection fonctionnent sans auth.

```kotlin
@Composable
fun OnboardingScreen(onComplete: () -> Unit) {
    val pagerState = rememberPagerState(pageCount = { 3 })

    HorizontalPager(state = pagerState) { page ->
        when (page) {
            0 -> WelcomePage()
            1 -> CameraPermissionPage()
            2 -> FirstScanPage(onComplete)
        }
    }

    // Skip toujours visible
    TextButton(onClick = onComplete) { Text("Skip") }

    // Indicateur de page
    PageIndicator(pagerState)
}
```

---

## 5.2 — Navigation complète

```kotlin
@Composable
fun EurioNavHost() {
    val navController = rememberNavController()

    Scaffold(
        bottomBar = {
            NavigationBar {
                NavigationBarItem(
                    icon = { Icon(Icons.Outlined.Search, "Explorer") },
                    label = { Text("Explorer") },
                    selected = currentRoute == "explore",
                    onClick = { navController.navigate("explore") }
                )
                NavigationBarItem(
                    icon = { Icon(Icons.Filled.CameraAlt, "Scan") },
                    label = { Text("Scan") },
                    selected = currentRoute == "scan",
                    onClick = { navController.navigate("scan") }
                )
                NavigationBarItem(
                    icon = { Icon(Icons.Outlined.Lock, "Coffre") },
                    label = { Text("Coffre") },
                    selected = currentRoute == "vault",
                    onClick = { navController.navigate("vault") }
                )
                NavigationBarItem(
                    icon = { Icon(Icons.Outlined.Person, "Profil") },
                    label = { Text("Profil") },
                    selected = currentRoute == "profile",
                    onClick = { navController.navigate("profile") }
                )
            }
        }
    ) {
        NavHost(navController, startDestination = "scan") {
            composable("explore") { ExploreScreen() }
            composable("scan") { ScanScreen() }
            composable("vault") { VaultScreen() }
            composable("profile") { ProfileScreen() }
            composable("coin/{coinId}") { CoinDetailScreen() }
        }
    }
}
```

---

## 5.3 — Écran Explorer

```kotlin
@Composable
fun ExploreScreen(viewModel: ExploreViewModel) {
    Column {
        // Recherche
        SearchBar(query, onQueryChange = viewModel::search)

        // Sections
        LazyColumn {
            // Nouvelles frappes
            item { SectionHeader("Nouvelles commémoratives") }
            items(newReleases) { CoinPreviewCard(it) }

            // Tendances prix
            item { SectionHeader("En hausse") }
            items(trending) { CoinPreviewCard(it) }

            // Browse par pays
            item { SectionHeader("Par pays") }
            items(countries) { CountryCard(it) }
        }
    }
}
```

---

## 5.4 — Edge cases & robustesse

### Scan

| Cas | Comportement |
|---|---|
| Éclairage insuffisant | "Éclairage insuffisant — rapproche une source de lumière" |
| Objet non-pièce | Pas de résultat (ne jamais afficher un faux positif) |
| Pièce hors catalogue (non-euro) | "Pièce non identifiée — Eurio couvre les pièces euro" |
| Pièce très usée | Suggestions avec confiance basse |
| Caméra occupée | Message d'erreur clair + bouton retry |

### Réseau

| Cas | Comportement |
|---|---|
| Pas de connexion | Scan OK (on-device). Coffre OK (Room). Prix = cache local |
| Connexion lente | Sync en background, zéro blocage UI |
| Première ouverture sans réseau | Scan OK. "Prix non disponible — connecte-toi pour les mettre à jour" |

### Données

| Cas | Comportement |
|---|---|
| Pièce sans prix eBay | Fallback cote Numista |
| Pièce sans aucune donnée de prix | Afficher valeur faciale + "Données insuffisantes" |
| Pièce très rare | "Pièce rare — consultez un spécialiste" |

---

## 5.5 — Performance

### Objectifs

| Métrique | Cible |
|---|---|
| Cold start → caméra prête | < 2 secondes |
| Scan → résultat | < 3 secondes |
| Navigation entre onglets | Instantané (< 100ms) |
| Taille APK | < 25 MB |
| RAM | < 150 MB |
| Battery drain (5 min scan) | < 5% |

### Optimisations

- TFLite INT8 quantifié
- Images lazy loaded + cache (Coil)
- CameraX STRATEGY_KEEP_ONLY_LATEST (pas de queue de frames)
- Embeddings en mémoire (~500 KB)
- Room avec Flow (pas de requêtes bloquantes)

---

## 5.6 — Partage (v1 light)

```kotlin
fun shareCoinSheet(context: Context, coin: CoinUiModel) {
    val shareIntent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT,
            "${coin.name} — Valeur estimée : ${coin.price}€\n" +
            "Découvert avec Eurio"
        )
    }
    context.startActivity(Intent.createChooser(shareIntent, "Partager"))
}
```

---

## 5.7 — Profil & Settings

```kotlin
@Composable
fun ProfileScreen() {
    Column {
        // Niveau collectionneur
        CollectorLevelCard(level, progress)

        // Stats
        StatsRow(coinCount, countryCount, setsCompleted)

        // Badges
        BadgeWall(achievements)

        // Settings
        SettingsSection {
            ThemeToggle()           // Clair / Sombre
            ScanSensitivitySlider() // Seuil de confiance
            DataSyncButton()        // Forcer la sync
            AboutButton()           // Version, crédits, licences
            FeedbackButton()        // Email / formulaire
        }
    }
}
```

---

## 5.8 — Test panel fermé

### Distribution

```bash
# Build APK release
./gradlew assembleRelease

# Ou via Firebase App Distribution (gratuit, plus pratique)
# → Upload l'APK
# → Inviter les testeurs par email
```

### Panel cible

- 10-20 testeurs
- Mix : curieux (jamais collectionné) + collectionneurs hobby
- Distribution via APK direct ou Firebase App Distribution

### Métriques (analytics locales)

```kotlin
// Pas de SDK tiers — compteurs simples dans SharedPreferences ou Room
object Analytics {
    fun trackScan(result: ScanResult) { /* compteur */ }
    fun trackAddToVault(coinId: String) { /* compteur */ }
    fun trackScreenView(screen: String) { /* compteur */ }
    fun trackScanDuration(ms: Long) { /* moyenne */ }
}

// Export en JSON pour analyse manuelle
```

### Feedback

- Formulaire simple (Google Forms) accessible depuis Settings
- Sessions de test en personne quand possible
- Focus : premier scan, compréhension UI, envie de revenir

---

## 5.9 — Livrables Phase 5

- [ ] Onboarding 3 écrans (skip, permission, premier scan)
- [ ] Navigation bottom bar (4 onglets)
- [ ] Écran Explorer (catalogue, recherche, tendances)
- [ ] Gestion de tous les edge cases
- [ ] Performance validée (métriques ci-dessus)
- [ ] Profil + Settings
- [ ] Partage via share sheet
- [ ] APK release distribuable
- [ ] Panel de testeurs invité
- [ ] Feedback collecté et priorisé

---

## Durée estimée

**7-10 jours**
- 2-3 jours : onboarding + navigation + explorer
- 2-3 jours : edge cases + robustesse + performance
- 1-2 jours : profil + settings + partage
- 2 jours : build release + distribution + suivi tests
