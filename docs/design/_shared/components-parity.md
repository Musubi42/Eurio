# Parité composants — proto CSS ↔ Android Compose

> Table de correspondance entre les classes CSS réutilisables du proto et les composables Compose de l'app Android. Règle de maintenance : voir [parity-rules.md §R3](parity-rules.md).
>
> **Source CSS canonique = la web app Vue** (`admin/packages/proto/src/styles/components.css` + `shell.css`, importés dans `main.ts`) depuis la refonte 2026-06. `docs/design/prototype/_shared/components.css` est legacy — **conservé** tant que des scènes HTML orphelines (états Android non portés) en dépendent, mais non canonique. Les tokens viennent de `shared/tokens.css` (R2, jamais édité — alias `@shared`). Les classes nommées ci-dessous sont inchangées (copie verbatim) ; seul leur emplacement canonique a bougé.
>
> Toute ligne avec un status ≠ 🟢 est un bout de dette à résorber.

## Légende status

- ⏳ todo — pas encore implémenté côté Android
- 🟡 en cours — implémenté partiellement ou en cours d'alignement
- 🟢 aligné — parité proto ↔ Android validée visuellement
- ⚠️ divergent — delta non trivial, voir colonne notes

## Boutons & actions

| Proto (`components.css`) | Compose (`ui/components/`) | Delta Android | Status |
|---|---|---|---|
| `.btn` (base) | `EurioButton` (base, variantes via param) | ripple M3 (D2) | ⏳ |
| `.btn-primary` | `EurioPrimaryButton` | containerColor = Indigo700 | ⏳ |
| `.btn-gold` | `EurioGoldButton` | background brush (gradient) | ⏳ |
| `.btn-ghost` | `EurioGhostButton` | outline via `border` modifier | ⏳ |
| `.btn-ghost--on-dark` | `EurioGhostButton(onDark = true)` | paramètre onDark | ⏳ |
| `.btn-icon` | `EurioIconButton` | `backdrop-filter: blur` non supporté → fallback alpha | ⚠️ |
| `.btn-danger` | `EurioDangerButton` | containerColor = danger-soft | ⏳ |
| `.btn-gold--lg` | `EurioGoldButton(size = Large)` | taille via param | ⏳ |

## Cards & surfaces

| Proto | Compose | Delta | Status |
|---|---|---|---|
| `.card` | `EurioCard` | élévation M3 au lieu de box-shadow CSS | ⏳ |
| `.card-glass` | `EurioGlassCard` | `backdrop-filter: blur(18px)` non supporté → fond semi-opaque | ⚠️ |
| `.card-dark` | `EurioDarkCard` | linear gradient via Brush | ⏳ |
| `.sheet` | `EurioBottomSheet` | remplacé par `ModalBottomSheet` M3 (D7) | ⏳ |

## Badges, pills, chips

| Proto | Compose | Delta | Status |
|---|---|---|---|
| `.badge` | `EurioBadge` | — | ⏳ |
| `.badge--gold` | `EurioBadge(variant = Gold)` | — | ⏳ |
| `.badge--success` | `EurioBadge(variant = Success)` | — | ⏳ |
| `.badge--danger` | `EurioBadge(variant = Danger)` | — | ⏳ |
| `.badge--soon` | `EurioBadge(variant = Soon)` | — | ⏳ |
| `.pill` | `EurioPill` | — | ⏳ |
| `.pill--ghost-dark` | `EurioPill(onDark = true)` | `backdrop-filter: blur` → alpha fallback | ⚠️ |
| `.chip` | `EurioChip` | — | ⏳ |

## Data display

| Proto | Compose | Delta | Status |
|---|---|---|---|
| `.progress-bar` + `.progress-track` + `.progress-fill` | `EurioProgressBar` | brush linéaire Gold | ⏳ |
| `.stat` (`.stat-value` + `.stat-label`) | `EurioStat` | — | ⏳ |
| `.stat-row` | `EurioStatRow` | — | ⏳ |
| `.divider` | `EurioDivider` | `HorizontalDivider` M3 | ⏳ |
| `.dashed-hr` | `EurioDashedDivider` | Canvas avec dashPathEffect | ⏳ |

## Nav & chrome

| Proto | Compose | Delta | Status |
|---|---|---|---|
| `.bottomnav` + `.bottomnav__tab` | `EurioBottomBar` + `NavTab` (dans `ui/nav/`) | M3 `Surface` + `NotchedBarShape` + FAB overlay (D1, D6) | 🟢 |
| `.bottomnav__tab--scan` | `ScanFab` (`ui/components/`) | `Surface(onClick)` avec gradient brush | 🟢 |
| `.bottomnav__tab--soon` | `NavTab(variant = Soon)` | — | ⏳ |
| `.version-badge` + `.version-badge__led` | `VersionBadge` | 7-tap counter persistant | ⏳ (Phase 1) |
| `.statusbar` | — | Remplacé par system status bar + `enableEdgeToEdge` (D1) | 🟢 (delta) |
| `.home-indicator` | — | Remplacé par system nav bar (D1) | 🟢 (delta) |
| `.tabbed-nav` (segmented in-scene) | `EurioSegmentedControl` | `SingleChoiceSegmentedButtonRow` M3 | ⏳ (Phase 2) |

## Feedback éphémère

| Proto | Compose | Delta | Status |
|---|---|---|---|
| `.toast` | `SnackbarHost` + `EurioSnackbarStyle` | Composant natif M3 (D8) | ⏳ |
| `.toast--on-dark` | variant dark du Snackbar | — | ⏳ |
| `.toast--debug` | `DebugSnackbar` | JetBrains Mono + accent Success | ⏳ (Phase 1) |

## Layout & utility

| Proto | Compose | Delta | Status |
|---|---|---|---|
| `.eyebrow` | `EurioEyebrow` (Text style) | `MonoFamily` + letterSpacing 0.22.sp | ⏳ |
| `.u-display` | `MaterialTheme.typography.displayMedium` | — | 🟢 |
| `.u-display-it` | `displayMediumItalic` (à créer dans Type.kt) | — | ⏳ |
| `.u-mono` | `MonoFamily` FontFamily | — | 🟢 |
| `.scene-placeholder` | `EurioEmptyState` | — | ⏳ |

## Cohort test (lab tooling)

Composants spécifiques à la scène `cohort-test-live/index.html` — vivent
sous `app-android/src/cohortTest/java/com/musubi/eurio/cohorttest/components/`,
pas dans `ui/components/` (scope flavor `cohortTest` uniquement).

| Proto | Compose | Delta | Status |
|---|---|---|---|
| `.progress-strip` + segments | `ProgressStrip` (`components/ProgressStrip.kt`) | InfiniteTransition pour le pulse Indigo700 du segment courant | 🟢 |
| `.hero` + `.coin-thumb` + `.chip-row` | `HeroCoinCard` (`components/HeroCoinCard.kt`) | Coil `AsyncImage` pour le thumb (vs SVG du proto), fallback gold-gradient | 🟢 |
| `.viewfinder` (vignette + ring + pill + brackets) | `DetectionViewfinder` (`components/DetectionViewfinder.kt`) | Réutilise `PhotoGuideOverlay` du flavor full pour vignette+ring (DRY) | 🟢 |
| `.snap-btn` + `.snap-helper` | `SnapCta` (`components/SnapCta.kt`) | Gated sur `detectionFlow` (fix bug clavier-matché) | 🟢 |
| `.sheet` + `.verdict-band` + `.compare-row` + `.top3-list` + CTAs | `ResultSheet` (`components/ResultSheet.kt`) | Pattern `slideInVertically(spring())` (mirror `ScanAcceptedCard`), pas `ModalBottomSheet` | 🟢 |
| `.detect-pill` (live state badge) | inline dans `DetectionViewfinder` | `AnimatedVisibility(fadeIn + slideInHorizontally)` | 🟢 |

## Notes générales

- **`backdrop-filter: blur()`** n'est pas supporté par Compose et est fondamentalement coûteux sur Android. Tous les composants `.card-glass`, `.btn-icon`, `.pill--ghost-dark` utilisent un fond semi-opaque comme fallback. Marqué ⚠️ divergent.
- **`drop-shadow(0 6px 10px …)`** pour les `.coin-svg` → Modifier.shadow + Offset. Delta mineur, acceptable.
- **Les couleurs** viennent toutes de `Color.kt` (auto-généré depuis `tokens.css`). Toute divergence = bug du générateur, pas un delta.
