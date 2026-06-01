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

### Cohort test (lab tooling)

| Proto scene | Android destination | Phase | Status | Notes |
|---|---|---|---|---|
| `cohort-test-live/index.html` | `LiveTestsScreen` (flavor `cohortTest`) | Lab | 🟢 | Standalone proto (pas chargé par le router prototype — chrome propre, design-toggle console). Hero card + ProgressStrip + DetectionViewfinder (réutilise `PhotoGuideOverlay`) + SnapCta gaté sur Hough live (fix bug clavier-matché) + ResultSheet slide-up. Backend: bundle v2 enrichi via `ml/utils/i18n.py`. |

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

## Refonte psycho (blueprint `app-pont`, 2026-06-01)

> Écrans/interactions **dérivés de la recherche psycho** ([`docs/mission/app-pont/`](../../mission/app-pont/)) — **plus riches que le proto actuel**. ❌ = bloque le code Compose tant que la scène proto n'existe pas (R1). Ces lignes sont le **handoff de la session « refonte proto »**. Garder la palette/vibe actuelle (`shared/tokens.css`).

| Proto scene (à créer) | Sert | Doc-pont | Status | Notes |
|---|---|---|---|---|
| `onboarding-lentille.html` | question-lentille (Histoire/Valeur/Compléter) | `00-onboarding` | ⏳ prête | **Livré (chunk E)** : 3 options sélection **unique réversible** (re-tap = désélection) + icônes ; « Plus tard » = Découverte ; persiste `state.lens` (`discovery` par défaut). Inséré dans le flux `onboarding-3 → lentille → permission`. Route `#/onboarding/lentille`. *Reste : que le reveal lise `state.lens` pour l'emphase du peek (delta ultérieur).* |
| `onboarding-demo.html` | mode démo (scan guidé sans pièce) | `00-onboarding` | ⏳ prête | **Livré (chunk E)** : caméra guidée distincte de `scan-idle` — pièce-échantillon « prêtée » (coins.json) flottante dans le réticule + ripple de tap + endowed-progress ; tap → **vraie transition 3D `#/scan/transition?id=` → reveal célébré** (cat. 1). « Passer » → `#/scan`. Flux : `lentille → permission (Autoriser) → demo → transition → reveal`. *Reste (mock) : créditer réellement la barre collection au 1ᵉʳ ajout.* |
| `scan-transition-3d.html` | transition diégétique caméra→3D + settle | `01-scan` | ⏳ prête | livré chunk A : vrai 3D via `scenes/_coin3d.js` (moteur extrait de `scan-coin-3d`), morph → flick-spin → settle (halo + haptic + clink WebAudio) ; skippable + `?light=1` + reduced-motion. Route `#/scan/transition`. *Reste : settle → reveal stratifié (chunk B) ; câblage scan-idle→transition une fois B livré.* |
| `reveal-stratifie.html` | héros 3D + **bottom sheet 2 crans** (peek/déployé) + accent contextuel | `02-reveal` | ⏳ prête | livré chunk B (modèle révisé après rétro : sheet draggable au lieu du carrousel) : héros 3D rotatable (`_coin3d.js`, reste visible, se réduit au déploiement) ; **peek** = résumé Découverte ≤3 drives + CTAs ; **tirer la poignée** → sections Histoire/Rareté/Valeur/Complétion (scroll). Variante doublon. Route `#/scan/reveal?id=`. Flux câblé `scan-idle → transition → reveal`. *Contenu = mock déterministe (vrai contrat data ultérieur) ; lien fiche → `coin-detail` (id à unifier).* **Delta jalon (overlay)** : `?milestone=set\|feat` met le reveal en mode fête **sur place** (couche `.reveal-cel` banderole+confettis + ré-accentuation héros/complétion/accent), **sans changer d'écran**. Porte les célébrations cat. 2/4 ; cat. 3 (`country`) viendra avec le chunk D. |
| Célébrations (overlay reveal) | set complété / pays complété / exploit rareté | `02-reveal` | ⏳ prête (3/3) | **Modèle = OVERLAY superposé au reveal** (rétro user 2026-06-01, ni avant ni après : **pas d'écran séparé**). Quand un jalon tombe, le reveal passe en mode fête via `data-milestone` : couche `.reveal-cel` (banderole + confettis `z-index:5` `pointer-events:none`) **+** ré-accentuation en place (héros qui pulse, halo or, complétion/accent mis en avant). Juice partagé `scenes/_celebration.js` (confetti/chime/haptique) ; confettis factorisés `.cel-confetti*` dans `components.css`. **Cat. 1 (nouvelle pièce)** = reveal seul (accent léger, chunk B). **Livré (3/3)** : `?milestone=set` (banderole « Série complète » + complétion X/X), `?milestone=feat` (**le pic** : banderole « Légendaire » + rayons + halo renforcé + confettis denses + accent rareté), `?milestone=country` (banderole « Pays complété » → CTA « Gratter la carte 🪙 » qui enchaîne sur la carte à gratter, chunk D). Échelle d'intensité : set < country < feat. |
| `coin-detail` (enrichir) | bloc **récit** (transportation narrative) | `03-page-piece` | ⏳ fait (chunk F) | **Livré** : bloc récit immersif (indigo) après le hero — kicker « Le récit » + headline + lead + chapitres déroulés (L'événement / Le contexte / Les créateurs / Le lieu), ancré sur thème/pays/année/description. **Emphase pilotée par la lentille** (`state.lens` = Valeur → replié en teaser « Lire le récit »). Lien affilié « Où trouver les N manquantes » sur sets incomplets. *(différé : scène 3D thématique du monument)* |
| `carte-a-gratter.html` | scratch-reveal du pays complété + **redesign belle carte** | `04c-coffre-carte` | ⏳ prête (Chunk D complet) | **Décisions user 2026-06-01** : (1) **vraie carte géo** — paths réels Natural Earth 50m (domaine public) projetés/simplifiés → `scenes/_eurozone-geo.js` (auto-généré par `/tmp/build_eurozone_geo.py`, à committer dans `scripts/` si pérennisé) ; (2) **label ISO2 + compteur** par pays + **3 états** (gravé / en cours / complété), **abandon du dégradé continu** ; (3) tap pays → **liste des pièces inline sous la carte** (plus de redirection). **D1 livré** : carte au trésor or sur indigo, 18 pays dessinés + 3 micro-états (LU/MT/CY) en pastilles à leader ; **31 pays voisins non-euro en contexte bleu muet** (UK, Scandinavie, Suisse comblant le trou alpin, Balkans… — non cliquables, frontières seules) pour ne pas amputer l'Europe ; Bulgarie 0/24 = état gravé, **Portugal complété** coiffé d'une **feuille d'or « GRATTE »** (statique, cible scratch). **Légende = 4 états** (Aucune / En cours / Complète / Hors zone €) — remplace l'ancienne barre « gravé→complet » jugée sans signification. Route `#/vault/catalog` repointée (`vault-catalog-map.html` gardé en réf, sans route). **Liste inline livrée** : tap pays (carte ou liste) → en-tête pays + **grille des pièces inline sous la carte** (vignettes `data.coinSvg`, ✓ possédées / grisées manquantes, tap → fiche `#/coin/:id`), **plus aucune redirection**. Pays voisins + légende 4 états aussi livrés. **D2 scratch livré** : `<canvas>` posé sur la bbox du Portugal, foil or clippé à la silhouette (Path2D), effacé au doigt (`destination-out`), seuil 50 % (échantillonnage alpha) → canvas fondu + **célébration « pays complété » en overlay sur la carte** (confettis + banderole + chime/haptique via `_celebration.js`). Réservé au pays complété (garde-fou). **D3 livré** : reveal `?milestone=country` (overlay « Pays complété ») → « Ajouter au coffre » morphe en **« Gratter la carte 🪙 »** → `#/vault/catalog?scratch=1` qui pré-sélectionne le pays complété + fait **pulser la feuille à gratter**. **Boucle complète : scan → pays complété → grattage → célébration.** Chunk D terminé. ⚠️ Bugs corrigés : `var()` ne passe ni dans `fill-opacity:calc()` ni en attribut SVG `stop-color` (→ JS + stops CSS) ; sidecar doit cibler `.cag-map svg` (pas le 1er svg = icône header — bug latent du `vault-catalog-map.js` de réf). |
| `vault-sets-detail` (enrichir) | célébration set complété + lien affilié sur case manquante | `04b-coffre-sets` | ⏳ fait (chunk G) | **Livré** : banderole **« Série complète »** à l'état complété (data-completed) + **lien affilié « Où trouver les N manquantes »** quand il manque des pièces (toast partenaire mock). Démo complète : `#/vault/sets/starter-ie`. |
| `defis.html` | surface défis adaptatifs | `05-defis` | ❌ à proto'er | ⚠️ **arbitrer l'emplacement** (onglet/Profil/bandeau) AVANT de proto'er — toujours en suspens |
| `profile.html` / `profile-settings.html` (MàJ) | **retirer 🔥 streak** + ajouter réglage **lentille** | `06-profil` | ⏳ fait (chunk G) | **Livré** : aucune streak 🔥 n'existait dans le proto (décisions #6/#8 déjà respectées) ; « Chasses en cours » → **« Tes 3 prochains » plafonné à 3** (anti-Zeigarnik) ; `profile-settings` : nouveau groupe **Reveal · Ta lentille** (segmenté Découverte/Histoire/Valeur/Série → `state.lens`) + **Fréquence** notifs (Discrète/Normale). `profile-unlock` couvre déjà la célébration identitaire mesurée (médaille + arc), pas de delta. |
| `share-piece/completion/carte.html` (×3) | share cards (image générée) | `02-social-partage` | ❌ à proto'er | partage système possible dès v1 (sans compte) |

**Bloquant connu avant de proto'er les défis** : trancher leur emplacement (question produit en suspens). Tous les autres écrans ci-dessus peuvent être proto'és sans dépendre des questions grade/défis.
