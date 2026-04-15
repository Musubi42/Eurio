# Parité composants — proto CSS ↔ Android Compose

> Table de correspondance entre les classes CSS réutilisables du proto HTML et les composables Compose de l'app Android. Règle de maintenance : voir [parity-rules.md §R3](parity-rules.md).
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

## Notes générales

- **`backdrop-filter: blur()`** n'est pas supporté par Compose et est fondamentalement coûteux sur Android. Tous les composants `.card-glass`, `.btn-icon`, `.pill--ghost-dark` utilisent un fond semi-opaque comme fallback. Marqué ⚠️ divergent.
- **`drop-shadow(0 6px 10px …)`** pour les `.coin-svg` → Modifier.shadow + Offset. Delta mineur, acceptable.
- **Les couleurs** viennent toutes de `Color.kt` (auto-généré depuis `tokens.css`). Toute divergence = bug du générateur, pas un delta.
