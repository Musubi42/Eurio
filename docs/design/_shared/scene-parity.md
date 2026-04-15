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

## Inventaire (2026-04-16)

### Onboarding

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `onboarding-splash.html` | Non planifié | — | ⏳ | Premier run, à planifier |
| `onboarding-1.html` | Non planifié | — | ⏳ | Tutorial slide 1 |
| `onboarding-2.html` | Non planifié | — | ⏳ | Tutorial slide 2 |
| `onboarding-3.html` | Non planifié | — | ⏳ | Tutorial slide 3 |
| `onboarding-permission.html` | In-line dans `ScanScreen` | 1 | ⏳ | Permission caméra demandée localement au scan |

### Scan

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `scan-idle.html` | `ScanScreen` state Idle | 1 | ⏳ | Viewfinder live par défaut |
| `scan-detecting.html` | `ScanScreen` state Detecting | 1 | ⏳ | Overlay "détection…" entre Idle et Matched |
| `scan-matched.html` | `ScanScreen` state Accepted + `CoinResultCard` | 1 | ⏳ | Card 2 CTA (Détail / Ajouter) |
| `scan-not-identified.html` | `ScanScreen` state NotIdentified | 1 | ⏳ | Rejet spread-based, encourage retry |
| `scan-failure.html` | `ScanScreen` state Failure | 1 | ⏳ | Erreur ML / caméra indisponible |
| `scan-debug.html` | `ScanScreen` avec `debugMode = true` | 1 | ⏳ | Toggles YOLO/ArcFace + CAPTURE + overlay bboxes |

### Coin detail

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `coin-detail.html` | `CoinDetailScreen` route `coin/{eurioId}` | 1 (min) / 2 (full) | ⏳ | CTA "Ajouter au coffre" persistant si `?fromScan=true` |

### Coffre — Mes pièces (sub-view 1)

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `vault-home.html` | `CoffreScreen` sub-view "Mes pièces" — liste peuplée | 2 | ⏳ | Grille + filtres + tri |
| `vault-empty.html` | Même sous-vue — état vide | 2 | ⏳ | CTA pulse vers FAB scan |
| `vault-filters.html` | Filtres inline dans la sub-view | 2 | ⏳ | Chips M3 multi-select |
| `vault-search.html` | Icône loupe → overlay search | 2 | ⏳ | Text field live filter |
| `vault-remove-confirm.html` | Dialog M3 de confirmation | 2 | ⏳ | Delete depuis Coin detail |

### Coffre — Sets (sub-view 2)

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| **(manquant)** | `CoffreScreen` sub-view "Sets" — liste | 3 | ❌ **à proto'er** | Cards de sets avec mini-grille silhouette + progress |
| **(manquant)** | `SetDetailScreen` route `set/{setId}` | 3 | ❌ **à proto'er** | Grille silhouette complète (pattern Pocket) |
| `profile-set.html` | À relocaliser conceptuellement dans Coffre | 3 | ⏳ | Base existe mais dans le namespace profile, à adapter |

### Coffre — Catalogue (sub-view 3)

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| **(manquant)** | `CoffreScreen` sub-view "Catalogue" — carte eurozone | 4 | ❌ **à proto'er** | 21 pays interactifs, fill par % possédé |
| **(manquant)** | `CatalogCountryScreen` route `catalog/country/{iso2}` | 4 | ❌ **à proto'er** | Grille silhouette des pièces du pays |

### Profil

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `profile.html` | `ProfilScreen` — hub principal | 5 | ⏳ | Grade + streak + stats + sections |
| `profile-achievements.html` | Section "Badges" dans `ProfilScreen` | 5 | ⏳ | Débloqués + next-goal |
| `profile-settings.html` | Section "Réglages" dans `ProfilScreen` | 5 | ⏳ | Langue, debug, about, reset |
| `profile-unlock.html` | Modale animation débloquage grade/badge | 5 | ⏳ | Transition identitaire |
| `profile-set.html` | Voir section Coffre/Sets ci-dessus | 3 | ⏳ | À relocaliser |

### Marketplace

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `marketplace-soon.html` | — | Futur | — | Pas de Marketplace en v1. Proto conservé pour référence future. |

## Récapitulatif gaps bloquants

Avant de pouvoir démarrer une phase de dev, voici les scènes à proto'er :

| Phase | Nb scènes manquantes | Scènes à créer |
|---|---|---|
| Phase 3 (Coffre Sets) | 2 | `vault-sets-list.html`, `vault-sets-detail.html` |
| Phase 4 (Coffre Catalogue) | 2 | `vault-catalog-map.html`, `vault-catalog-country.html` |

Phase 1 (Scan) et Phase 2 (Mes pièces) ont tout ce qu'il faut dans le proto et peuvent démarrer immédiatement.
Phase 5 (Profil) a 95% de ce qu'il faut, `profile-set.html` peut servir de base.
