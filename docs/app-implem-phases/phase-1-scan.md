# Phase 1 — Scan câblé dans sa destination

> **Objectif** : migrer la pipeline scan existante (monolithique dans l'ancien `MainActivity`) vers la destination `Scan` propre du nouveau shell, ajouter la card post-scan avec CTA `Détail` / `Ajouter au coffre`, le toast "déjà possédée", le streak badge top bar, et scoper le debug mode à cette destination uniquement.

## Dépendances

- Phase 0 terminée (shell nav, Room, bootstrap catalogue).

## Livrables

### 1. Destination `Scan` (feature/scan/)

- `ScanScreen.kt` (Composable) : viewfinder caméra plein écran, overlay detection bboxes, top bar overlay, card/toast post-scan.
- `ScanViewModel.kt` : state holder. Wrap `CoinAnalyzer` existant. Expose :
  - `scanState: StateFlow<ScanState>` (Idle / Detecting / Accepted(result) / Dismissed)
  - `debugMode: StateFlow<Boolean>`
  - `streakCount: StateFlow<Int>`
  - `onCaptureClicked()`, `onToggleDebug()`, `onDismissCard()`, `onAddToVault(coinId)`, `onOpenDetail(coinId)`
- Permissions caméra gérées localement dans `ScanScreen` (pas au démarrage global) via `rememberPermissionState`.

### 2. Migration de la pipeline ML (zéro régression)

Le code ML (`ml/CoinDetector.kt`, `CoinAnalyzer.kt`, `CoinEmbedder.kt`, `EmbeddingMatcher.kt`) **ne bouge pas**. Seul le glue code (init, frame callback, consensus buffer) migre de l'ancien `MainActivity` vers `ScanViewModel`.

Préserver strictement :
- Letterbox YOLO 320×320
- Hough + merge IoU 0.60
- Rerank ArcFace spread-based
- Ring buffer consensus 5/3 sticky
- Interval 400 ms (2.5 fps)
- Debug capture → `externalFilesDir/eurio_debug/` avec rapport txt complet

### 3. Top bar overlay du scan

Row ancrée au top (sur le viewfinder, fond dégradé noir→transparent pour lisibilité) :
- **Gauche** : badge `v0.1.0` (tap counter — 7 taps → toggle `debugMode`). Garde la logique actuelle.
- **Droite** : `StreakBadge` composant — icône flamme 🔥 + count, `MaterialTheme.colorScheme.tertiary`. Toujours visible, quelle que soit la valeur (y compris 0).
- **Mode debug actif** : apparaissent en plus, en dessous de la row principale : toggles YOLO/ArcFace + bouton `CAPTURE`. Overlay bboxes live dessiné par-dessus le viewfinder.

### 4. Card post-scan adaptive

Quand `ScanState.Accepted(result)` :

**Cas A — pièce pas encore dans le vault** :
- Card overlay occupant ~75% du bas de l'écran (au-dessus de la BottomAppBar)
- Image avers (grande), nom, pays, année, face value
- Row 2 CTA :
  - `[Détail]` → navigate vers `coin/{eurioId}?fromScan=true`
  - `[Ajouter au coffre]` → call `vaultRepository.add(coinId, source=scan, confidence)` → la card disparaît avec animation slide-down → scan reprend
- Si l'ajout **complète un set** → surbrillance + toast/snackbar "Set {nom} complété !". Pas d'animation élaborée en v1 (cérémonie future).

**Cas B — pièce déjà dans le vault** :
- Pas de card. À la place : **toast léger** (Snackbar M3) en bas : `Déjà dans ton coffre · Voir le détail`, action "Voir" → navigate détail.
- Le scan continue sans interruption.
- Détection : `vaultRepository.contains(coinId)` appelé au moment de `Accepted`.

**Logique dismiss** : tap ailleurs sur l'écran ou swipe down sur la card → `onDismissCard()` → scan reprend. Pas de dismiss auto après N secondes (l'utilisateur contrôle).

### 5. Streak logic (v1 permissive)

Règle finale :
- **1 scan quelconque (accepté) par jour** = streak préservé.
- **Grace period** : si l'utilisateur skip 1 jour, streak reste (au lieu de reset à 0). Reset uniquement après 2 jours consécutifs sans scan.
- Stocké dans `CatalogMetaEntity` (clés `streak_count`, `streak_last_day`, `streak_grace_used`).
- Incrémenté à chaque `onAddToVault` **et** à chaque `Accepted` (même si déjà possédé — on veut pas pénaliser le scan de confirmation). Décision : incrément à chaque `Accepted`, qu'on ajoute ou pas.
- `StreakRepository.tick()` appelé depuis le ViewModel à chaque scan accepté.

### 6. Debug mode scoping

- `debugMode` est stocké dans `ScanViewModel` (scope écran), pas global.
- Les toggles YOLO/ArcFace + CAPTURE + overlay bboxes **ne s'affichent que dans la destination Scan**.
- Si l'utilisateur navigue vers Coffre/Profil, `debugMode` reste true côté state mais aucun UI debug n'est visible là-bas (Phase 1 : rien ne change dans Coffre/Profil).
- Futurs debug hooks (e.g. voir les logs de sync dans Coffre) seront opt-in dans chaque feature, pas automatiques.

### 7. Écran Coin Detail minimal

Pour que `[Détail]` depuis la card fonctionne, il faut une destination `coin/{eurioId}` existante dès Phase 1, même minimaliste :
- Image + nom + pays + année + face value + description (si dispo)
- **Bouton persistant "Ajouter au coffre"** quand on arrive `?fromScan=true` et que la pièce n'est pas encore dans le vault
- Back button → retour au Scan (viewfinder reprend immédiatement)

Cette destination sera étoffée en Phase 2, Phase 1 se contente du minimum viable pour boucler le flow post-scan.

## Intégration avec l'existant

- `MainActivity.kt` monolithique → **supprimé en fin de Phase 1** une fois que `ScanViewModel` porte toutes ses responsabilités.
- `go-task android:pull-debug` → inchangé, toujours fonctionnel.
- Repository layer : `VaultRepository`, `StreakRepository`, `CoinRepository` (tous nouveaux, introduits ici ou en Phase 0 selon ce qui est pratique).

## Acceptance criteria

- [ ] App s'ouvre sur Scan, viewfinder live immédiat.
- [ ] Top bar affiche `v0.1.0` à gauche, streak 🔥 à droite (toujours visible, même à 0).
- [ ] 7 taps sur le badge version → debug mode actif, toggles + CAPTURE apparaissent, overlay bboxes visible.
- [ ] Scan d'une pièce nouvelle → card pleine avec 2 CTA. `Ajouter au coffre` → card disparaît, pièce insérée dans Room `vault_entries`, streak incrémenté.
- [ ] Scan d'une pièce déjà possédée → toast bas, scan continue.
- [ ] `Détail` depuis card → écran détail, bouton `Ajouter au coffre` visible quand non possédée, ajout depuis détail → back au Scan et la card n'est plus affichée pour cette même pièce.
- [ ] Complétion d'un set (tout set, même un set de 2 pièces pour tester) → highlight visuel + toast.
- [ ] Debug capture → rapport complet dans `eurio_debug/` avec la même richesse qu'aujourd'hui.
- [ ] Aucune régression sur la pipeline ML (benchmark latence, consensus stable).

## Risques / questions ouvertes

- **Card vs toast timing** : si le scan re-accepte immédiatement la même pièce après un dismiss, on risque de re-afficher la card en boucle. Solution : après dismiss, mettre en place un "cooldown" de 3s pendant lequel on ignore la même classe (ou on downgrade en toast).
- **Navigation quand caméra active** : passer de Scan à Coffre doit couper proprement la caméra et la redémarrer au retour. Utiliser `DisposableEffect` + lifecycle awareness.
- **Streak increment quand app en background** : ne pas incrémenter si l'app est pas au premier plan au moment du scan (edge case si quelqu'un lance un scan, lock screen). Vérifier lifecycle.
- **Coin detail minimal en Phase 1 vs étoffé en Phase 2** : Phase 1 pose juste les routes + UI basique. Phase 2 ajoute les relations (pièces du même set, séries liées, etc.).

## Docs de référence

- `docs/research/detection-pipeline-unified.md` — état pipeline actuel
- `docs/design/scan/README.md` — flow détaillé
- `docs/design/scan/debug-overlay.md` — debug
- `docs/design/scan/ml-pipeline.md` — détails techniques ML
- `docs/app-implem-phases/research-01-scan-collect-apps.md` — rationale card vs toast, streak
