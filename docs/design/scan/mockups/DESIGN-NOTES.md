# Scan mockups — design notes

> Mockups HTML haute-fidélité pour la vue scan d'Eurio (killer feature) et son overlay de debug.
> Viewport cible : 390 × 844 (iPhone ref, mais build Kotlin Compose pour Android).
> Date : 2026-04-14.

## Fichiers

| # | Fichier | Rôle |
|---|---|---|
| — | `index.html` | Landing avec mini-previews de tous les écrans, grille 4 colonnes. |
| 01 | `01-scan-idle.html` | Caméra active, aucune pièce. Pulse blanc discret. |
| 02 | `02-scan-detecting.html` | Pièce détectée, anneau orange, jauge de confidence en cours. |
| 03 | `03-scan-matched.html` | Match trouvé, flash vert, bottom sheet résultat. |
| 04 | `04-scan-failure-hint.html` | Hint doux après 3s de non-convergence. |
| 05 | `05-scan-not-identified.html` | Échec définitif après 6s, snapshot figé, 3 actions. |
| 06 | `06-debug-overlay-full.html` | Overlay debug complet : bbox + 5 panels. |
| 07 | `07-debug-tools-panel.html` | Drawer outils debug : dumps, force match, session stats. |

## Direction

- **Full bleed camera, dark everywhere.** La caméra est le contenu ; toute UI flotte dessus en verre fumé (backdrop-filter blur + border rgba blanche 0.1).
- **Typographie à trois voix** : Instrument Serif pour les headlines utilisateur (numismatique, patrimoine, un peu d'âme), Inter Tight pour le body et les états, JetBrains Mono pour tout l'overlay debug et les valeurs numériques. Cette séparation donne une intention claire : « quand tu vois du monospace, tu regardes de la donnée technique ».
- **Palette minimale**. L'indigo et l'or ne s'affichent pas sur la vue scan elle-même (la caméra mange tout) — ils réapparaissent dans le bottom sheet et l'overlay debug via les accents de couleur.
- **Pas d'emoji**, jamais, ni dans l'UI user ni dans l'overlay debug. Les icônes sont des SVG line 1.6–1.8 stroke.

## Hiérarchie des composants (par écran)

### 01 — Idle
- Camera feed (vide, texture bois)
- Guide ring 280×280 pulsé (2.2s, opacity 0.5 → 0.8)
- Corners indicatifs 22×22 (jamais une frame bloquante, juste un cadre suggestif)
- State chip « En attente · pointe une pièce »
- Version badge (top-left) avec LED rouge qui clignote toutes les 2.4s
- Scan header « SCAN / Eurio » (Instrument Serif)
- Top-right : flash toggle + help
- Tabbar (Coffre / Scanner · actif / Profil)

### 02 — Detecting
- Coin réel visible dans le cadre (simulé en CSS gradient)
- Ring en orange pulse rapide 0.9s
- Barre de progression 180×2 px bas (orange → or) — secondaire au ring
- State chip « Analyse · 62 % »
- **Pas de bouton capture.** L'utilisateur ne fait rien pendant cet état.

### 03 — Matched
- Ring vert (2px, glow 60px), position remontée pour céder la place au sheet
- Flash vert radial en overlay (rgba 0.18)
- Bottom sheet (24px radius top) avec :
  - Coin thumbnail (pastille ronde réaliste 2€)
  - Row country+flag, h2 « 10 ans de l'Euro » (Instrument Serif 22px), année
  - Ligne de valorisation : prix estimé gros (Instrument Serif 28px) + delta +110 % + range P25/P75
  - Row confidence (92.3 %) en monospace sur fond neutre
  - 2 boutons : « Détails » (ghost) + « Ajouter au coffre » (primary indigo, icône or)
- **Tabbar masquée** pour donner toute la place au sheet.

### 04 — Hint
- Coin petit et décentré (simule « trop loin »)
- Ring orange
- Bulle hint en verre fumé (max 320px), flotte au-dessus du state chip
- State chip « Doute · top-Δ 0.04 » exposant le vocabulaire technique mais en surface user friendly
- Le scan continue en background — l'utilisateur ne doit jamais sentir qu'il est bloqué

### 05 — Not identified
- Camera backgrounded, sheet quasi full-height
- Eyebrow rouge « PIÈCE NON IDENTIFIÉE »
- Headline Instrument Serif 26px en 2 lignes
- Snapshot rect 16:10 avec la frame figée + timestamp + crop corners
- 2 chips partial info (pays probable 62 %, valeur 2 €) — mode dégradé qui permet quand même de progresser
- 3 actions verticales :
  1. « Réessayer » (primary indigo)
  2. « Envoyer au support pour analyse » (ghost, sert de remote fallback)
  3. « Ajouter manuellement comme 2 € France » (link, tag manuel + add to vault)

### 06 — Full debug overlay
Camera feed dimmed (filter brightness 0.7 saturate 0.85) pour améliorer la lisibilité des panels.

- **Layer 1 · BBox** : rectangle dessiné sur la frame avec 4 corner-markers, label `coin · 0.87 · cls 0` en vert. Border 1.5 px + shadow pour lisibilité sur fond clair ou foncé.
- **Layer 2 · Top-5 matches** : panel bas qui prend toute la largeur (moins 12px de chaque côté). Grid 4 colonnes (rank / id / cosine bar / score). `★` + couleur or sur le winner. Ligne Δ top1−top2 = 0.052 marqué en orange « CLOSE ».
- **Layer 3 · Latencies** : mini panel top-right (108 px), avec budgets `det/emb/knn/tot/fps`. Codes couleur `ok` (vert) et `hot` (rouge) — dans cet écran tout est OK.
- **Layer 4 · Runtime** : panel top-left (158 px) avec `model/emb/cam/therm`. Hash embeddings `a7f2c1` pour savoir quel catalogue est chargé.
- **Layer 5 · Histogramme convergence** : strip central-top 72px, 10 bars hauteur variable (rolling window 6s). Couleurs vert/rouge/gris (success/fail/skip). Légende sous les bars.
- **State chip** `MATCH · 92.3 %` en vert, repositionné au-dessus de la toolbar debug.
- **Debug toolbar** : 6 outils (Dump / Replay / Freeze / Force / Embed / Stats) en bande avec icônes SVG monoline et label mono 7px. Aucun emoji.

### 07 — Debug tools drawer
- Camera quasi noire (brightness 0.5) — on est en mode outillage, la frame live n'a plus d'importance
- Session stats callout en haut : 4 cases grid (scans / success / avg tot / fails)
- Force match input box : style terminal CLI avec chevron `›`, caret qui clignote, texte or
- Drawer principal : liste des 3 derniers dumps avec thumbnails miniatures des coins, id timestamped, metadata courte, et badge de status (MATCH / CLOSE / NO-COIN)
- Toolbar en bas du drawer, outil « Dump » actif (border + fond or translucide)

## Interactions (pour l'impl Kotlin Compose)

| Composant | Interaction | Note |
|---|---|---|
| Ring pulse | CSS keyframes dans la maquette, `InfiniteTransition` en Compose | périodes 2.2s (idle) / 0.9s (detecting) |
| Coin detected → matched | Transition snapshot + green flash radial | `animateFloatAsState` + `Crossfade` |
| Bottom sheet | Slide up 220ms ease-out | `ModalBottomSheet` Material 3 |
| Haptique | `HapticFeedbackConstants.CONFIRM` au match | une seule fois par scan |
| Version badge 7-tap | compteur local + reset after 3s inactivity | voir `_shared/dev-debug-strategy.md` |
| LED pastille rouge | opacity blink 2.4s | visible uniquement si `DebugState.isEnabled` |
| Debug panels | `pointerInput { detectDragGestures }` pour déplacer ? | à voir v1.1, statiques en v1 |
| Toolbar Dump button | single tap → écrit sur disk + toast + refresh drawer | `DebugTools.dumpCurrent()` |
| Freeze button | stoppe l'`ImageAnalysis.Analyzer`, fige la dernière frame | `CameraController.clearAnalyzer()` |
| Force match | text input avec autocomplete sur `coin.eurio_id` Room | bypass matching, déclenche flow downstream |

### Tap targets

Tous les tap targets user-facing ≥ 44×44 dp. Les outils de debug peuvent descendre à 36×36 dp (utilisateur technique, pas de contrainte d'accessibilité consumer).

## Data bindings

### Scan states → ViewModel

```kotlin
sealed class ScanState {
  object Idle : ScanState()
  data class Detecting(val bbox: RectF, val confidence: Float) : ScanState()
  data class Matched(val result: ScanResult) : ScanState()
  data class Hint(val reason: FailureReason, val hintText: String) : ScanState()
  data class NotIdentified(val failure: ScanFailure) : ScanState()
}
```

### Debug overlay inputs (toujours exposés, même en release)

```kotlin
data class FrameTimings(val detMs: Int, val embMs: Int, val knnMs: Int, val totMs: Int, val fps: Float)
data class RuntimeContext(val modelVersion: String, val embCount: Int, val embHash: String, val camRes: String, val deviceTempC: Int)
data class TopKMatch(val eurioId: String, val cosine: Float, val rank: Int)
data class ConvergenceWindow(val outcomes: List<Outcome>) // rolling last ~30 frames
```

Le `ScanDebugOverlay` n'a pas de ViewModel propre — il observe directement les StateFlows exposés par `ScanViewModel`. Il est monté dans un `if (debugEnabled)` bloc en fin de `Box` (z-index maxi, par-dessus le bottom sheet).

### Bottom sheet coin data

```kotlin
// Tout ça vient de Room, aucun appel réseau au moment du scan
coin.name, coin.countryIso, coin.faceValue, coin.year, coin.priceP25, coin.priceP50, coin.priceP75, coin.deltaFaceValuePct
```

Confidence score = `ScanResult.confidence` (pas `coin.*`), affiché en bas du sheet.

## États edge non mockés explicitement mais à implémenter

- **Permission caméra refusée** : écran plein qui explique et redirige vers les settings. Pas dans ce lot (onboarding scope).
- **Device trop chaud** (>40°C) : état runtime badge température en rouge dans l'overlay debug, plus message utilisateur (bottom banner) « Le téléphone chauffe, scan ralenti » si throttle.
- **Multi-pièces dans le cadre** : question ouverte (voir `debug-overlay.md`). V1 : on boxe la plus grande.
- **No match avec Δ > seuil mais confidence < 0.85** : variante de 04 (hint) avec message « On hésite entre deux candidats ». Pas mockée, à faire après décision seuil Phase 2B.
- **Dump storage full** : toast neutre « 3 vieux dumps supprimés » à l'ouverture de l'app. Overlay de dumps dans 07 montre le compteur taille (48 MB / 200 MB).

## Décisions de design (synthèse)

1. **Dark-mode forcé sur la vue scan** — la caméra est le contenu, toute UI doit en découler. Le reste de l'app peut rester light.
2. **Instrument Serif sur les headlines utilisateur** — marque le contraste avec l'univers commodity de CoinSnap/CoinManager. Évoque le musée, le patrimoine.
3. **Monospace comme marqueur sémantique** — dès que du monospace apparaît, c'est de la data technique (confidence, bbox, scores). Cohérent avec l'overlay debug qui est 100 % mono.
4. **L'anneau de guide ne se ferme jamais** — les 4 coins sont des L-marks, pas un cercle fermé. Confirme visuellement qu'on n'oblige pas l'utilisateur à aligner.
5. **Bottom sheet ouvert mais pas full-height en matched state** — on laisse voir un bout de la caméra + ring vert derrière pour préserver la continuité (« ça a marché, tu peux continuer à scanner »).
6. **Overlay debug a sa propre grammaire visuelle** — vert/orange/rouge pour les statuts, or pour les headers de panel et les winners, jamais de bleu indigo (qui reste la couleur de l'app user). Ça permet de voir au premier coup d'œil si on est en mode dev ou prod.
7. **Pastille rouge LED + badge version toujours visibles** — même en overlay debug. C'est la promesse cross-vue : quand la pastille est là, l'app est en mode dev, pas de confusion possible.

## Questions ouvertes

- [ ] **Animation de transition matched** : green flash radial + haptique sont ok, mais est-ce qu'on veut en plus une micro-animation du coin qui « se pose » dans le thumbnail du sheet ? À décider à l'impl, peut-être overkill.
- [ ] **Ring color sur matched après l'ouverture du sheet** : reste vert ? devient blanc neutre ? disparaît ? La maquette garde vert pour la lisibilité mais on pourrait le fader à 50 % après 600 ms.
- [ ] **Bottom sheet drag up** : est-ce qu'on laisse l'utilisateur étendre le sheet en full screen pour révéler la fiche complète ? Si oui, à quel moment on bascule vers la vraie fiche pièce (screen à part) ? → à aligner avec l'agent coin-detail.
- [ ] **Force match autocomplete** : faut-il une vraie dropdown dans l'overlay debug ou juste un text input qui valide sur Enter ? Maquette montre la version input brute pour simplicité v1.
- [ ] **Placement des 5 panels debug simultanés sur écran 390** : ça tient mais c'est dense. Sur des écrans plus petits (iPhone SE 375) ça risque d'overflow. À tester. Solution backup : tabs entre panels au lieu de tout afficher en même temps.
- [ ] **Flash light button** : statique dans la maquette, doit-il être auto (détecteur de luminosité) ou manuel uniquement ? Probablement auto en v1.1, manuel en v1.
- [ ] **Hint « Approche un peu »** : apparaît à 3s fixe ou quand le détecteur signale `LOW_CONFIDENCE` quelle que soit la durée ? → probablement basé sur l'état, pas sur un timer.
- [ ] **Force match / Freeze** : est-ce qu'on prévoit un « Unfreeze » explicite ou un tap n'importe où désépingle ? Maquette ne couvre pas l'état frozen.
- [ ] Le **tabbar** est masqué sur 03 (matched) — est-ce cohérent ? Alternative : le garder mais opacité 0.3. Décision à prendre avec le reste de la navigation.

## Fonts

- Instrument Serif : Google Fonts, licence OFL, à bundler dans l'APK (2 styles seulement : regular + italic). Poids bundle ≈ 40 KB.
- Inter Tight : déjà prévu comme base.
- JetBrains Mono : ≈ 90 KB en subset latin.

Total impact APK typo : < 150 KB, négligeable.

## Assets réels à produire côté impl

- Icônes SVG monoline stroke 1.8 pour toutes les toolbars (dump, replay, freeze, force, embed, stats, flash, help, shield, home, tabs). 11 icônes.
- Flags circulaires pour les 21 pays eurozone (pour le country chip dans le bottom sheet). À générer une fois depuis `coin_catalog.json` + assets SVG communs (wikipedia).
- Placeholder coin thumbnail (pour quand l'image canonique n'est pas encore téléchargée) : cercle brossé or avec un `?` centré.
