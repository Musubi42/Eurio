# Parité scènes — proto HTML ↔ destinations Android

> Table de correspondance entre les scènes du prototype (`docs/design/prototype/scenes/`) et les destinations de l'app Android Compose. Règle de maintenance : voir [parity-rules.md §R4](parity-rules.md).
>
> Une ligne `❌ à proto'er` **bloque le démarrage de sa phase**. Tant que le proto manque, on ne code pas l'écran Android.

## Légende status

- ❌ à proto'er — n'existe ni en proto ni en Android, bloque la phase
- ⏳ prête — scène proto livrée, pas encore portée en Android
- 🟡 en cours — portage Compose en cours
- 🟢 livré — parité visuelle validée
- — — pas d'écran Android (proto-only ou delta)

## Inventaire (2026-04-16, rev 2)

### Onboarding

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `onboarding-splash.html` | `OnboardingScreen` page 0 → `OnboardingSplashPage` | 0 | 🟡 | Auto-advance 1.4s, gated first-run via `MetaDao` key `onboarding_completed` |
| `onboarding-1.html` | `OnboardingScreen` page 1 → `OnboardingSlide1Page` | 0 | 🟡 | Tutorial slide 1 "Scanne la pièce" — Canvas coin (12 stars) + breathing anim |
| `onboarding-2.html` | `OnboardingScreen` page 2 → `OnboardingSlide2Page` | 0 | 🟡 | Tutorial slide 2 "Ton coffre" — fake vault card + 3×2 coin grid |
| `onboarding-3.html` | `OnboardingScreen` page 3 → `OnboardingSlide3Page` | 0 | 🟡 | Tutorial slide 3 "Complète des séries" — set card 6/8 + 4×2 owned/missing |
| `onboarding-permission.html` | `OnboardingScreen` page 4 → `OnboardingPermissionPage` | 0 | 🟡 | Pre-prompt caméra (Duolingo pattern) — launches native permission dialog on "Autoriser". `ScanScreen` garde l'inline fallback pour le premier scan après "Plus tard". |

### Scan

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `scan-idle.html` | `ScanScreen` state Idle → `ScanIdleLayer` | 1 | 🟡 | Portage Compose livré (L-corners animés + hint pill). Validation device pendante. |
| `scan-detecting.html` | `ScanScreen` state Detecting → `ScanDetectingLayer` | 1 | 🟡 | Portage livré (gold pulse + linear progress). Validation device pendante. |
| `scan-matched.html` | `ScanScreen` state Accepted → `ScanAcceptedCard` | 1 | 🟡 | Portage livré (bottom sheet 2 CTA + swipe-down dismiss + 3s cooldown). Validation device pendante. |
| `scan-not-identified.html` | `ScanScreen` state NotIdentified → `ScanNotIdentifiedSheet` | 1 | 🟡 | Portage livré (red ring + top-5 + face-value picker 8 chips). Validation device pendante. |
| `scan-failure.html` | `ScanScreen` state Failure → `ScanFailureLayer` | 1 | 🟡 | Portage livré (warm orange + auto-retry 3s). Le trigger `ScanState.Failure` reste à définir côté pipeline (actuellement inatteignable). |
| `scan-debug.html` | `ScanScreen` + `ScanDebugOverlay` gated by `debugMode` | 1 | 🟡 | Portage livré (5 panels + tool strip). Le 7-tap version badge fonctionne. `DebugViewData` populée vide pour l'instant — à brancher sur `ScanResult` latences + bboxes réelles. |

### Coin detail

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `coin-detail.html` | `CoinDetailScreen` route `coin/{eurioId}` | 1 (min) / 2 (full) | 🟡 | Phase 2 : identité, description, sets, retirer du coffre dialog |

### Coffre — Mes pièces (sub-view 1)

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `vault-home.html` | `CoffreScreen` sub-view "Mes pièces" — liste peuplée | 2 | 🟡 | Grille 3 col + liste + tri (pays/valeur/date) + segmented control |
| `vault-empty.html` | Même sous-vue — état vide | 2 | 🟡 | Coin illustration Canvas + CTA "Scanner ma première pièce" |
| `vault-filters.html` | Filtres inline dans la sub-view | 2 | 🟡 | Chips M3 multi-select (pays/type/valeur) inline panel animé |
| `vault-search.html` | Icône loupe → overlay search | 2 | 🟡 | BasicTextField live filter 300ms debounce, inline dans toolbar |
| `vault-remove-confirm.html` | Dialog M3 de confirmation | 2 | 🟡 | AlertDialog "Retirer du coffre ?" depuis CoinDetailScreen |

### Coffre — Sets (sub-view 2)

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `vault-sets-list.html` | `CoffreScreen` sub-view "Sets" — `SetsListScreen` | 3 | 🟡 | Cards sets + mini-planche 8 slots + progress bar + category/state filters. Sorted in-progress first. |
| `vault-sets-detail.html` | `SetDetailScreen` route `set/{setId}` | 3 | 🟡 | Hero fan-collage 4 coins + big % + planche 3-col grid owned/silhouette + reward teaser + manual add long-press. |
| `profile-set.html` | À relocaliser conceptuellement dans Coffre | 3 | ⏳ | Iteration antérieure du pattern planche — conservée pour référence, à migrer ultérieurement dans le namespace vault. |

### Coffre — Catalogue (sub-view 3)

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `vault-catalog-map.html` | `CoffreScreen` sub-view "Catalogue" — `CatalogScreen` | 4 | 🟡 | Canvas map 18 blobs + 3 micro-state pastilles, gold fill by %, peek card, list mode. Toggle Carte/Liste. |
| `vault-catalog-country.html` | `CatalogCountryScreen` route `catalog/country/{iso2}` | 4 | 🟡 | Hero flag + progress + type filter (Tout/Circulation/Commémos) + planche 3-col owned/silhouette + long-press manual add. |

### Profil

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `profile.html` | `ProfilScreen` — hub principal | 5 | 🟡 | Hero indigo gradient + grade ladder + stats cards + streak + badges (unlocked row + next 3) + settings preview |
| `profile-achievements.html` | Section "Badges" dans `ProfilScreen` | 5 | 🟡 | 11 badge definitions, unlocked LazyRow + next-to-unlock with progress bars |
| `profile-settings.html` | Section "Réglages" dans `ProfilScreen` | 5 | 🟡 | Langue/Notifications/Catalogue/À propos preview rows (read-only v1) |
| `profile-unlock.html` | Modale animation débloquage grade/badge | 5 | ⏳ | Transition identitaire |
| `profile-set.html` | Voir section Coffre/Sets ci-dessus | 3 | ⏳ | À relocaliser |

### Marketplace

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `marketplace-soon.html` | — | Futur | — | Pas de Marketplace en v1. Proto conservé pour référence future. |

## Récapitulatif gaps bloquants

**Session 2026-04-16 rev 2 — tous les gaps bloquants sont résolus.** Les 4 scènes manquantes pour les Phases 3 et 4 ont été livrées et sont prêtes pour le portage Compose.

| Phase | Scènes proto | Status |
|---|---|---|
| Phase 1 (Scan) | 6 scènes | ⏳ prêtes |
| Phase 2 (Mes pièces) | 5 scènes | ⏳ prêtes |
| Phase 3 (Coffre Sets) | `vault-sets-list.html`, `vault-sets-detail.html` | ⏳ prêtes |
| Phase 4 (Coffre Catalogue) | `vault-catalog-map.html`, `vault-catalog-country.html` | ⏳ prêtes |
| Phase 5 (Profil) | 5 scènes | ⏳ prêtes (`profile-set.html` à migrer ultérieurement) |

## Composants partagés introduits session 2026-04-16

Extraits dans `docs/design/prototype/_shared/components.css` :

- `.coffre-header` — wrapper du segmented control commun aux 3 sous-vues du Coffre, au-dessus de `.tabbed-nav`
- `.planche` / `.planche__grid` / `.planche__cell` / `.planche__cell--missing` / `.planche__cell__date` — pattern signature "classeur de collection" utilisé dans vault-sets-list (compact), vault-sets-detail et vault-catalog-country
- `.disc` + variantes `--copper` / `--nordic` / `--silver` / `--bimetal` / `--missing` / `--xs` — médaillon CSS-only radial-gradient reposant dans une cavité planche

`vault-home.html` a été refactoré en rev 2 pour partager le même segmented control (`.tabbed-nav`) que les 3 nouvelles sous-vues, garantissant la cohérence visuelle du header Coffre entre les 3 segments. Note : en empty state, le segmented control n'est pas visible — à revoir si on veut permettre la navigation Sets/Catalogue avant le premier scan.
