# 03 — Android : robustesse caméra, intégrité catalogue, dette scan

> Fiche de remédiation auto-portée (audit hardening 2026-07). Périmètre : `app-android/`
> (Kotlin/Compose). Tous les findings ci-dessous ont été vérifiés sur le code réel
> (preuve `file:line`). Aucun fix n'est appliqué par cette fiche — elle décrit quoi
> corriger, où, et comment vérifier.

## Résumé

Deux **bugs UX bloquants** au cœur de l'acte central de l'app (le scan) :

1. **Permission caméra jamais re-demandée après « Plus tard »** — l'onboarding promet
   (en commentaire) que ScanScreen re-demandera la permission, mais `CameraPreview`
   fait un check one-shot dans `remember {}` et affiche un texte statique sans aucun
   bouton ni launcher. L'utilisateur est bloqué **définitivement** sur un écran mort,
   même après avoir accordé la permission via les Réglages système (le `remember`
   sans clé ne recompute jamais).
2. **Échec de bind CameraX avalé en silence** — le `try/catch` autour de
   `bindToLifecycle` a un catch vide dont le commentaire (« surfaces via the host's
   state machine ») est faux : aucun état `CameraError` n'existe, aucun signal n'est
   émis. Caméra occupée par une autre app → écran noir sans feedback ni retry.

Plus trois dettes structurantes : **`APP_CORE_VERSION` maintenu à la main** (catalogue
silencieusement périmé en release à chaque regen d'`app_core.db` non accompagnée d'un
bump), **double machine à états scan** (legacy `_state` + `ScanReducer`, migration 6.2b
inachevée, désync silencieuse possible), **couleurs hardcodées** dans ~20 fichiers du
scan (violation de l'interdiction repo, alphas incohérents), et **deux composables
Compose complets morts** (~500 lignes) encore documentés comme « portage livré » dans
`scene-parity.md`. S'ajoute un drift doc : CLAUDE.md documente des tasks
`android:snapshot*` qui n'existent plus.

## Table des findings

| Sévérité | Fichier:ligne | Constat |
|---|---|---|
| 🔴 High (bug) | `app-android/src/main/java/com/musubi/eurio/features/scan/components/CameraPreview.kt:67-84` + `features/onboarding/pages/OnboardingPermissionPage.kt:74-76,132` | Après « Plus tard » à l'onboarding, aucune re-demande de permission caméra : check one-shot `remember { checkSelfPermission }` + `Text("Autorisation caméra requise")` statique, zéro `rememberLauncherForActivityResult` dans tout `features/scan/`. Écran mort permanent. |
| 🔴 High (bug) | `app-android/src/main/java/com/musubi/eurio/features/scan/components/CameraPreview.kt:105-134` + `features/scan/ScanUiState.kt:24-53` | Échec `bindToLifecycle` avalé : `catch (_: Exception) { /* surfaces via the host's state machine */ }` — mais aucun `ScanUiState.CameraError` n'existe et `onCameraReady` n'est simplement jamais appelé. Écran Ink noir sans feedback ni retry. |
| 🔴 High (dette) | `app-android/src/main/java/com/musubi/eurio/data/local/bootstrap/AppCoreBootstrapper.kt:39-44,215-218` | `const val APP_CORE_VERSION = 1` maintenu à la main ; en release le bootstrap est skip si `storedVersion >= APP_CORE_VERSION`. Aucun tooling (`ml:build-app-core`, Taskfile, CI) ne bump ni ne vérifie la constante → catalogue silencieusement périmé post-update. |
| 🟡 Medium (arch) | `app-android/src/main/java/com/musubi/eurio/features/scan/ScanViewModel.kt:179-206,364-378` + `domain/scan/ScanReducer.kt` | Deux machines à états scan en parallèle : UI pilotée par le legacy `_state` (mutations directes lignes 786/1007/1204), effets réels pilotés par `_scanMachineState`/ScanReducer via des `emitScanEvent(...)` dispersés. `applySideEffect(ConfirmPossession)` (l.364-378) lit le gate `alreadyOwned` dans le legacy et `eurioId`/`captureId` dans le reducer → désync silencieuse au moindre site non appairé. Auto-documenté « Wiring debt » (l.179-192). |
| 🟡 Medium (tokens) | `app-android/.../features/scan/components/ScanRevealLayer.kt`, `ScanIdleLayer.kt`, `CameraPreview.kt:80` + `scripts/generate_android_tokens.mjs:125` + `shared/tokens.css:79` | `Color.White/Black.copy(alpha=X)` hardcodés partout dans le scan (X = 0.1, 0.3, 0.45, 0.55, 0.7, 0.78, 0.85, 0.92 selon fichier pour un même rôle sémantique). Cause racine : le générateur saute les tokens `rgba()` (`if (!lit) continue`), donc `--scan-idle: rgba(255,255,255,0.55)` n'est jamais émis en Kotlin. Violation de l'interdiction « pas de couleurs hardcodées ». |
| 🟡 Medium (code mort) | `app-android/.../features/scan/components/ScanAcceptedCard.kt` (258 l.), `ScanNotIdentifiedSheet.kt` (247 l.) + `docs/design/_shared/scene-parity.md:35-36` | Deux composables complets jamais appelés (grep : zéro call-site hors de leur propre fichier ; `ScanScreen.kt:33-38` n'importe que Idle/Detecting/Failure/Reveal/DebugOverlay — `ScanRevealLayer` a absorbé matched/not-identified). `scene-parity.md` les affiche pourtant « Portage livré ». |
| 🟡 Medium (doc) | `CLAUDE.md:139-140` + `app-android/Taskfile.yml:298-299` | CLAUDE.md documente `go-task android:snapshot` / `android:snapshot-dry` ; ces tasks n'existent plus (remplacées par `go-task ml:build-app-core`, cf. commentaire P6 dans le Taskfile). Suivre la doc verbatim → « task not found ». |

## Axe A — Robustesse caméra/permission (bugs runtime, priorité 1)

Les deux bugs partagent le même symptôme : le scan — l'acte central de l'app — peut se
retrouver dans un état visuellement mort sans issue.

### A1. Permission caméra : ajouter le chemin de re-demande dans le scan

**État actuel** (`CameraPreview.kt:67-84`) :
- `val hasPermission = remember { ContextCompat.checkSelfPermission(...) == GRANTED }`
  — calculé **une seule fois**, aucune clé, aucun observer lifecycle.
- Si `false` : `Box(Ink)` + `Text("Autorisation caméra requise")`. Pas de bouton,
  pas de launcher, pas de deep-link Réglages.
- Le commentaire d'`OnboardingPermissionPage.kt:74-76` (« permission is re-requested
  at first scan by ScanScreen's own inline check ») décrit un comportement qui
  **n'existe pas** ; `onLater` (l.132) appelle `onComplete` sans rien demander.

**Correction** :
1. Remplacer le `remember {}` par un état mutable rafraîchi sur `ON_RESUME`
   (`LifecycleEventObserver` via `DisposableEffect(lifecycleOwner)`) — couvre le cas
   « permission accordée dans les Réglages puis retour dans l'app ».
2. Ajouter un `rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission())`
   dans l'état sans-permission, avec un bouton « Autoriser la caméra » qui lance le
   dialogue natif et met à jour l'état au callback.
3. Cas « denied définitif » (`shouldShowRequestPermissionRationale == false` après un
   refus) : le bouton bascule sur un intent `Settings.ACTION_APPLICATION_DETAILS_SETTINGS`
   avec libellé « Ouvrir les réglages » — le refresh ON_RESUME du point 1 récupère
   alors la permission au retour.
4. Corriger le commentaire d'`OnboardingPermissionPage.kt:74-76` pour refléter le
   comportement réel.

### A2. Échec bind CameraX : le faire remonter réellement

**État actuel** (`CameraPreview.kt:105-134`) : le fallback 2-usecases est bien loggé
(l.123-126), mais l'échec total tombe dans `catch (_: Exception)` vide (l.132-134).
`ScanUiState.kt:24-53` n'a que `Idle/Detecting/Accepted/NotIdentified/Failure` (les
deux derniers « QA-parity injection only ») — rien pour la caméra.
`ScanScreen.kt:113-120` : `onCameraReady` ne sert qu'à `viewModel.attachCamera(...)`,
aucun timeout, aucun signal d'échec.

**Correction** :
1. Ajouter un callback `onCameraError: (Throwable) -> Unit` à `CameraPreview` et
   l'invoquer dans le catch (en gardant le log).
2. Côté état : ajouter un état d'erreur caméra — soit un case dédié dans
   `ScanUiState`, soit un flag hors machine à états (préférable : ce n'est **pas**
   un état du pipeline scan, cf. axe C1 — ne pas grossir la machine legacy en pleine
   migration). Un `StateFlow<CameraStatus>` séparé dans le ViewModel est propre.
3. UI : overlay « Caméra indisponible » + bouton « Réessayer » qui re-déclenche le
   bind (recomposition de l'AndroidView via une clé, ou retry explicite du
   `ProcessCameraProvider`).
4. Design de l'overlay : voir §Note proto-first (scène proto d'erreur requise).

**Vérification A** (device ou émulateur) :
- Flow permission : install propre → onboarding → « Plus tard » → onglet Scan →
  le bouton « Autoriser la caméra » est visible → tap → dialogue natif → accorder →
  la preview démarre sans relancer l'app.
- Flow Settings : refuser deux fois → le bouton devient « Ouvrir les réglages » →
  accorder dans les Réglages → retour app → preview démarre (test du refresh ON_RESUME).
- Flow bind : `adb shell am start` d'une app tierce qui verrouille la caméra (ou
  forcer une exception dans le bind en debug) → Eurio affiche l'overlay erreur +
  « Réessayer » fonctionne une fois la caméra libérée.

## Axe B — Intégrité catalogue : automatiser `APP_CORE_VERSION`

**État actuel** (`AppCoreBootstrapper.kt`) : en release (`forceReload = BuildConfig.IS_QA`,
l.39), le bootstrap est skip si `storedVersion >= APP_CORE_VERSION` (l.41) ;
`APP_CORE_VERSION = 1` (l.218) n'est bumpé par **aucun** tooling. `go-task
ml:build-app-core` (Taskfile.yml:84, script `ml/export/build_app_core.py`) régénère
l'asset sans toucher la constante → un asset frais shippé avec constante inchangée
n'est **jamais chargé** chez les utilisateurs existants.

**Deux options, préférence pour l'option 2 (hash)** :

1. **Générer la constante depuis le build** : `build_app_core.py` écrit aussi un
   fichier versionné (ex. `app-android/src/main/assets/app_core.version` ou une
   constante Kotlin générée style R2/tokens) incrémenté ou timestampé à chaque export.
   Inconvénient : reste un compteur à discipline (l'export doit toujours passer par
   le script), et un fichier généré de plus à committer en paire.
2. **Dériver la version d'un hash de l'asset** (recommandé) : au bootstrap, calculer
   un digest (SHA-256 tronqué suffit) de `assets/app_core.db` en streaming, le
   comparer à la valeur stockée dans `meta` (`KEY_APP_CORE_VERSION` devient une
   string hash). Asset changé ⇒ hash changé ⇒ reload, **zéro discipline humaine,
   zéro constante**. Coût : un hash de l'asset au cold start (fichier de quelques Mo,
   négligeable, et seulement à l'ouverture — peut être fait sur le même thread IO que
   l'extraction actuelle). La constante `APP_CORE_VERSION` et son commentaire
   disparaissent ; le chemin QA `forceReload` peut même être simplifié (le hash rend
   le force-reload QA redondant, à garder ou non selon le confort parité).

**Fichiers** : `AppCoreBootstrapper.kt` (l.30-50, 211-221), éventuellement
`ml/export/build_app_core.py` (option 1 uniquement).

**Vérification B** : build release-like (IS_QA=false) → installer → lancer (bootstrap
loggé) → regénérer `app_core.db` via `go-task ml:build-app-core` (ou modifier un octet)
→ rebuild → réinstaller **sans** `pm clear` → le logcat montre le re-bootstrap
(« version stockée=… → … ») et une donnée modifiée du catalogue apparaît dans l'app.
Contre-test : réinstaller le même APK → skip bootstrap loggé.

**Au passage (doc-drift)** : corriger `CLAUDE.md:139-140` — remplacer
`android:snapshot`/`android:snapshot-dry` par `go-task ml:build-app-core` (cf.
`app-android/Taskfile.yml:298-299`).

## Axe C — Dette de refonte scan

### C1. Finir la migration 6.2b : ScanReducer = source unique

**État actuel** (`ScanViewModel.kt:179-206`) : le commentaire « Wiring debt » décrit
lui-même la cible — « Once 6.2b makes the reducer the source of truth, those tryEmits
become the only place those events fire ». Aujourd'hui : `_state` (legacy, mutations
directes l.786/1007/1204) pilote l'UI ; `_scanMachineState` (alimenté par
`ScanReducer.reduce` via `_scanEvents`, l.604-626) pilote les side effects (lock
caméra, capture, `SideEffect.ConfirmPossession`). Point chaud : `applySideEffect`
(l.364-378) mixe les deux mondes — `alreadyOwned` lu dans `_state.value as?
ScanUiState.Accepted`, `eurioId`/`captureId` pris dans l'effect du reducer.

**Correction** (chunk dédié, le plus gros de la fiche) :
1. Inventorier chaque site de mutation directe de `_state` et vérifier qu'un
   `emitScanEvent` équivalent existe (le commentaire l.179-192 dit que c'est déjà
   câblé inline — à auditer site par site).
2. Dériver `ScanUiState` (UI) de `_scanMachineState` par un mapping pur
   (`ScanState → ScanUiState`), supprimer les mutations directes de `_state`.
3. `applySideEffect(ConfirmPossession)` : lire `alreadyOwned` depuis l'état reducer,
   plus jamais depuis le legacy.
4. Supprimer le champ legacy une fois le mapping en place ; supprimer le bloc
   « Wiring debt ».

**Vérification C1** : suite de tests existante du reducer verte + flow device complet
(scan → reveal → ajout coffre → pièce présente dans Room ; re-scan de la même pièce →
gate `alreadyOwned` toujours correct) + grep : plus aucune écriture `_state.value =`
hors du mapping unique.

### C2. Tokens rgba : faire émettre les couleurs translucides par le générateur

**État actuel** : `scripts/generate_android_tokens.mjs:125` (`if (!lit) continue //
skip rgba, var refs, etc.`) saute les tokens `rgba()` de `shared/tokens.css` (ex.
`--scan-idle: rgba(255,255,255,0.55)`, tokens.css:79). Résultat : `ScanRevealLayer.kt`,
`ScanIdleLayer.kt`, `CameraPreview.kt:80` (et ~20 fichiers scan/dev/onboarding)
hardcodent `Color.White.copy(alpha=…)` avec des alphas divergents pour le même rôle.

**Correction** (respecte R2 — jamais d'édition manuelle de `Color.kt`) :
1. Étendre le générateur : parser `rgba(r,g,b,a)` et émettre
   `val ScanIdle = Color(0x8CFFFFFF)`-style (alpha dans l'ARGB) dans `Color.kt`
   auto-généré. Les `var()` refs restent résolues ou skippées comme aujourd'hui.
2. Ajouter dans `shared/tokens.css` les tokens overlay manquants pour les alphas
   récurrents du scan (rôles sémantiques : scrim, dim-text, hairline…) — **côté proto
   d'abord** si un nouveau rôle visuel apparaît (R1), sinon simple factorisation de
   valeurs existantes.
3. `go-task tokens:generate`, committer tokens.css + Color.kt ensemble (règle R2),
   puis remplacer les `Color.White/Black.copy(alpha=…)` du scan par les vals générées.
4. `go-task tokens:check` doit passer.

**Vérification C2** : `grep -rn "Color.White.copy\|Color.Black.copy" app-android/src/main/java/com/musubi/eurio/features/scan/`
→ zéro résultat ; rendu visuel scan inchangé (comparaison screenshots avant/après).

### C3. Supprimer les composables morts + MAJ scene-parity

**État actuel** : `ScanAcceptedCard.kt` (258 l.) et `ScanNotIdentifiedSheet.kt` (247 l.)
n'ont **aucun** call-site (grep : seules mentions = leurs propres fichiers + un
commentaire dans `Coin3DViewer.kt:294`). `ScanScreen.kt:33-38` n'importe que
Idle/Detecting/Failure/Reveal/DebugOverlay — `ScanRevealLayer` (387 l.) a absorbé
matched/not-identified. Pourtant `docs/design/_shared/scene-parity.md:35-36` les
affiche « Portage livré ».

**Correction** :
1. `git rm` des deux fichiers (pas de rebranchement : le reveal-sheet est le pattern
   retenu, cf. décision « reveal = bottom sheet pull-up »).
2. Nettoyer la mention dans `Coin3DViewer.kt:294` si elle référence un fichier supprimé.
3. MAJ `scene-parity.md:35-36` : pointer scan-matched / scan-not-identified vers
   `ScanRevealLayer` avec le delta réel (les entrées « Portage livré » vers les
   composants supprimés sont du drift au sens de R3).

**Vérification C3** : `go-task android:build` vert ; grep `ScanAcceptedCard\|ScanNotIdentifiedSheet` → zéro hit ; scene-parity.md relu sans entrée orpheline.

## Plan par chunks

| Chunk | Contenu | Fichiers principaux | Critère de vérification | Effort |
|---|---|---|---|---|
| **1** | A1 permission (launcher + refresh ON_RESUME + bouton Settings) | `CameraPreview.kt:67-84`, `OnboardingPermissionPage.kt:74-76` | Flow « Plus tard → Scan → bouton autoriser → preview live » + flow Réglages/retour | ~2-3 h |
| **2** | A2 bind failure (callback erreur + état + overlay retry) | `CameraPreview.kt:105-134`, `ScanViewModel.kt`, `ScanScreen.kt:113-120` (+ scène proto, cf. note R1) | Caméra occupée → overlay erreur + « Réessayer » fonctionnel | ~2-3 h (+ proto ~1 h) |
| **3** | B hash-based bootstrap (+ fix CLAUDE.md:139-140) | `AppCoreBootstrapper.kt:30-50,211-221`, `CLAUDE.md` | Asset modifié ⇒ re-bootstrap loggé sans bump manuel ; APK identique ⇒ skip | ~1-2 h |
| **4** | C3 suppression composables morts + scene-parity | `ScanAcceptedCard.kt`, `ScanNotIdentifiedSheet.kt`, `scene-parity.md:35-36` | Build vert, grep zéro hit | ~30 min |
| **5** | C2 générateur rgba + remplacement hardcodes scan | `generate_android_tokens.mjs:125`, `shared/tokens.css`, fichiers scan | `tokens:check` vert, grep `.copy(alpha` scan = 0, screenshots identiques | ~2-3 h |
| **6** | C1 migration 6.2b — reducer source unique | `ScanViewModel.kt:179-206,364-378`, `ScanReducer.kt` | Tests reducer verts + flow device scan→coffre + gate alreadyOwned + zéro mutation `_state` directe | ~0,5-1 j |

Chunks 1-2 sont indépendants de 3-6 ; 4 avant 5 (moins de fichiers à migrer) ; 6 en
dernier (le plus risqué, à faire seul dans sa PR). Conforme au workflow chunk-by-chunk :
livrer chunk par chunk, attendre la rétro avant d'enchaîner.

## Note proto-first (R1) — tranché

- **A1 (écran permission dans le scan)** : c'est une **adaptation technique Android
  exemptée** au sens de R1 — le dialogue de permission est un mécanisme OS sans
  équivalent web (le proto PWA a son propre modèle de permission navigateur), et
  `parity-rules.md` §R6 classe précisément ce genre de delta systémique hors parité.
  **Nuance** : le *pré-état* (fond Ink + message + bouton « Autoriser ») est un rendu
  visuel. Tant qu'on reste sur la composition existante (fond Ink + texte + un CTA
  stylé avec les composants/tokens déjà portés — même famille visuelle que le
  pre-prompt d'onboarding qui, lui, a sa scène proto `onboarding-permission`), pas de
  scène proto requise. Verdict : **exempté, pas de scène proto** pour A1.
- **A2 (overlay « Caméra indisponible » + Réessayer)** : c'est un **nouvel état
  visuel** (état error d'une scène), explicitement dans le champ de R1 (« nouveaux
  états (empty/loading/error) »). Verdict : **scène proto d'abord** — ajouter l'état
  caméra-erreur dans la scène Scan du proto (`admin/packages/proto/`) avant le
  Compose. C'est le « + proto ~1 h » du chunk 2.

## Effort & priorité

| Priorité | Quoi | Pourquoi | Effort total |
|---|---|---|---|
| **P0** | Chunks 1-2 (axe A) | Bugs runtime sur l'acte central ; l'app peut être définitivement inutilisable après un simple « Plus tard » | ~1 jour |
| **P1** | Chunk 3 (axe B) | Bombe à retardement release : la première regen d'`app_core.db` shippée sans bump rend le catalogue périmé en silence chez tous les installés | ~1-2 h |
| **P2** | Chunks 4-5 (C3, C2) | Hygiène : dette visible, faible risque, débloque la conformité R2/R3 | ~3-4 h |
| **P3** | Chunk 6 (C1) | Refactor le plus lourd ; le désync est théorique tant que les sites restent appairés, mais chaque évolution du scan augmente le risque | ~0,5-1 j |

**Total estimé : ~2,5 à 3 jours** en chunks séparés.
