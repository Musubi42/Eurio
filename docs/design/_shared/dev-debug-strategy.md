# Dev / debug strategy

> **Objectif** : pouvoir débugger l'app, en particulier le pipeline de scan ML, sur des builds debug ET sur des builds release installés sur un device physique. Sans jamais exposer accidentellement les outils de debug à un user final.
>
> Décidé le 2026-04-14. Inspiration : Uber, Meta, Google (pattern "hidden dev menu" + build variants Android natifs).

---

## Le problème

Eurio a un pipeline de scan ML en développement continu :
- Le `CoinDetector` (YOLO) peut échouer sur de nouvelles pièces ou de nouvelles conditions de lumière.
- Le `CoinEmbedder` (ArcFace) peut produire des embeddings bruités sur des classes qu'il n'a pas vues en training.
- Le `EmbeddingMatcher` peut donner un top-1 avec un écart insuffisant au top-2.

Pour itérer efficacement, Raphaël a besoin de voir en temps réel :
- La bounding box détectée par YOLO
- Les top-K candidats après matching, avec scores
- Les latences par étape
- La possibilité de dumper une frame pour replay offline
- Etc.

**Mais** :
- Cet overlay ne doit **jamais** être visible par un user final en prod.
- Raphaël doit pouvoir le voir sur un **APK release signé** installé sur son téléphone perso, parce que les conditions de test (perf, caméra, cache, permissions) diffèrent entre un debug build et un release build. Un bug de prod ne se reproduit pas toujours en debug.

---

## Les patterns standards dans l'industrie

### Pattern 1 — Build variants Android natifs (`debug` vs `release`)
Code dans `app/src/debug/java/` vs `app/src/main/java/`. Le code `debug/` n'est **littéralement pas** compilé dans l'APK release. Zéro risque de fuite. Standard Android, utilisé par la plupart des apps open source.

### Pattern 2 — `BuildConfig.DEBUG` + branches conditionnelles
`if (BuildConfig.DEBUG) { ... }` — R8/ProGuard strippe le code mort en release. Simple, mais le code reste dans le même fichier, plus facile à oublier.

### Pattern 3 — Hidden dev menu en prod (Uber, Meta, Google, Instagram, Android lui-même)
Le code debug **est shippé en prod** mais accessible uniquement via un geste secret (tap 7× sur le numéro de version, comme Android pour activer les options développeur). Avantages :
- Débugger un APK release sur device physique
- Permettre aux QA/beta testers d'activer le mode dev eux-mêmes
- Investiguer des bugs terrain sans avoir à rebuilder
- Risque quasi nul si le geste est suffisamment obscur

### Pattern 4 — Build flavor `internal` / dogfood (Google, Spotify, Airbnb)
Trois flavors : `dev`, `internal`, `release`. `internal` = release signé + outils dev activés, shippé en closed track Google Play aux employés. **Overkill pour un solo dev.** Pas retenu en v1.

---

## Ce qu'on fait pour Eurio : combinaison Pattern 1 + Pattern 3

### Règles

1. **En build debug** (`./gradlew assembleDebug` / `Run` dans Android Studio) :
   - L'overlay de debug scan est **activé par défaut**.
   - `BuildConfig.DEBUG == true` force `DebugState.isEnabled = true` au démarrage de l'app, ignorant toute préférence persistée.
   - Impossible de désactiver l'overlay — c'est le mode de travail.

2. **En build release** (APK signé, prêt pour Play Store ou install manuelle) :
   - L'overlay est **désactivé par défaut**.
   - L'user final ne voit rien de différent de la prod normale.
   - Accessible uniquement via un **geste secret** qui persiste dans DataStore.

3. **Le code de l'overlay vit dans `app/src/main/`**, pas dans `app/src/debug/`.
   - Raison : on veut qu'il soit compilé en release aussi pour le pattern 3.
   - Les *outils* de debug qui n'ont absolument aucune raison d'exister en prod (replay de frames, dump complet de l'état interne, mock data) peuvent vivre dans `app/src/debug/` et être no-op en release via une interface.

### Flag runtime

```kotlin
object DebugState {
    private val _isEnabled = MutableStateFlow(BuildConfig.DEBUG)
    val isEnabled: StateFlow<Boolean> = _isEnabled.asStateFlow()

    fun toggle(newValue: Boolean) {
        if (BuildConfig.DEBUG) return  // ignoré en debug, toujours on
        _isEnabled.value = newValue
        // Persister en DataStore
    }
}
```

Initialisé dans `Application.onCreate()` :
- Debug build → `isEnabled = true` toujours
- Release build → `isEnabled = read from DataStore (default false)`

### Geste d'activation (v1 provisoire)

**Approche v1 simple** : un numéro de version affiché en haut à gauche de la vue racine de l'app (onglet scan, coffre, profil — visible partout). 7 tap sur ce numéro → toggle `DebugState.isEnabled` et affiche un toast "Mode développeur activé" ou "désactivé".

```
┌─────────────────────────┐
│ v0.1.0                  │ ← 7 tap ici pour activer
│                         │
│     [Contenu de la vue] │
```

**Évolution future** : quand l'app aura une vraie structure de UI (version réelle, branding, Settings), le numéro de version migrera dans la section "À propos" des settings, comme Android lui-même. À ce moment, on supprimera l'affichage en haut à gauche.

**Pourquoi 7 tap et pas un menu dédié** : volonté d'obscurité. Un user final qui tape 7 fois par erreur sur un numéro de version, ça n'arrive pas. Et ça évite de mettre une ligne "Activer le mode développeur" dans les settings, qui serait immédiatement cliquée par 10% des users curieux.

### Persistance (release build uniquement)

```
DataStore : preferences.debug_mode_enabled : Boolean (default false)
```

Une fois activé, le mode dev reste activé entre les sessions. Un 2ème cycle de 7 taps le désactive.

### Cas couverts

| Cas | Build | `BuildConfig.DEBUG` | `DataStore.debug_mode` | `DebugState.isEnabled` | Overlay visible |
|---|---|---|---|---|---|
| Dev quotidienne en Android Studio | debug | `true` | N/A | `true` | ✅ toujours |
| APK release propre sur un device user | release | `false` | `false` | `false` | ❌ jamais |
| APK release sur device Raphaël, après 7 taps | release | `false` | `true` | `true` | ✅ |
| APK release après désactivation par Raphaël | release | `false` | `false` | `false` | ❌ |

---

## Garde-fous

- **`DebugState.toggle` est un no-op en build debug.** On ne peut pas accidentellement désactiver le mode dev pendant qu'on bosse.
- **Jamais de code secret en dur** dans le dépôt. Pas de "tape 1-2-3-4 pour entrer en mode dev avec un token". Le geste est volontairement simple et public parce qu'il ne protège rien de sensible.
- **Release builds minifiés** (`isMinifyEnabled = true` + R8) : les classes debug sont conservées en release (contrairement à Pattern 1 pur) mais shrink normalement. Pas de perte de perf significative.
- **Pas de données sensibles** dans les logs debug. Jamais de clés API, jamais de tokens, jamais de photos uploaded qui n'ont pas été explicitement demandées par l'user.

---

## Où vit quoi

```
app/src/main/java/com/musubi/eurio/
├── debug/
│   ├── DebugState.kt                  # le flag runtime
│   ├── DebugVersionBadge.kt           # le composable du badge top-left avec 7-tap detector
│   └── scan/
│       ├── ScanDebugOverlay.kt        # l'overlay scan (voir scan/debug-overlay.md)
│       └── ScanDebugViewModel.kt
```

Note : `app/src/main/java/.../debug/` existe bien en **main**, pas en source set debug. Le dossier s'appelle `debug` pour la sémantique, mais c'est du code de prod minifié.

Pour les features qui doivent VRAIMENT être strippées en release (mock data, replay tools qui accèdent à un dossier spécifique) :

```
app/src/main/java/com/musubi/eurio/debug/
└── DebugTools.kt              # interface + default no-op impl

app/src/debug/java/com/musubi/eurio/debug/
└── DebugTools.kt              # impl réelle avec replay, mock, dump
```

Le pattern interface + `debugImplementation` garantit que le code n'est pas présent en release, même désobfusqué.

---

## Applicabilité aux autres vues

**Question tranchée** : seule la vue scan a besoin d'un overlay debug. Les autres vues (coffre, profil, onboarding) n'ont pas de logique ML temps réel à observer.

Si un besoin ponctuel arrive plus tard (ex : débugger le calcul de valeur totale), on ajoutera un écran `DebugScreen` accessible via le même flag `DebugState.isEnabled`, avec des panneaux par feature. Pas la peine de le designer maintenant.

---

## Indicateur visuel "mode dev actif"

**Décidé le 2026-04-14** : quand `DebugState.isEnabled = true` en build release, l'app affiche en permanence une **pastille rouge** discrète pour signaler qu'on est en mode dev. Objectif : éviter qu'un beta tester (ou Raphaël lui-même) oublie qu'il a activé le mode dev et signale comme bug un comportement qui n'existe que dans l'overlay.

Implémentation :
- Une petite pastille rouge (6–8 dp) accolée au badge de version en haut à gauche.
- Visible sur **toutes les vues** de l'app, en même temps que le badge de version.
- En build debug (`BuildConfig.DEBUG = true`), la pastille est aussi affichée — c'est le comportement normal, on est en mode dev par définition.
- Pas de tooltip, pas de popup au tap. C'est juste un indicateur passif.

```
┌─────────────────────────┐
│ v0.1.0 ●                │ ← pastille rouge si debug on
│                         │
│     [Contenu de la vue] │
```

Pourquoi rouge et pas une autre couleur : le rouge est universellement interprété comme "attention", c'est visible même en vision périphérique, et ça contraste avec toute la palette de l'app (qui sera plutôt bleu/doré pour l'univers numismatique). Pas de risque de confusion.

---

## Questions ouvertes

- [ ] Comment gérer le partage d'une préférence de debug avec un autre device (ex : Raphaël installe l'app sur une tablette pour tester) ? → à la main pour l'instant, 7 taps re-activation.
- [ ] R8 strippe-t-il efficacement le code de `DebugState.toggle` si la branche release est suffisamment contrainte ? → à vérifier avec un APK analyzer à la première release.
