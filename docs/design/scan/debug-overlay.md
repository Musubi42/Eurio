# Scan — debug overlay

> **Objectif** : afficher en temps réel tout ce qui se passe dans le pipeline de scan ML, pour pouvoir développer, tester et débugger le détecteur + l'embedder + le matcher sur des pièces réelles.
>
> **Activation** : voir [`../_shared/dev-debug-strategy.md`](../_shared/dev-debug-strategy.md). Toujours on en build debug, togglable via 7-tap sur le numéro de version en build release.
>
> **Status** : à implémenter en parallèle de la vue scan v1.

---

## Ce que l'overlay affiche

### Layer 1 — Détection (CoinDetector / YOLO)

- **Bounding box** dessinée autour de la pièce détectée, en overlay de la preview caméra.
- **Couleur** : vert si détection confiante (conf > 0.7), orange si hésitante (0.4–0.7), rouge si rejetée.
- **Label au-dessus de la box** : `coin: 0.87` (confidence du détecteur).
- **Multi-pièces** : si plusieurs boxes détectées, toutes affichées. La plus confiante est highlightée.

### Layer 2 — Embedding + matching (CoinEmbedder + EmbeddingMatcher)

Panel flottant en bas de l'écran, semi-transparent :

```
┌─────────────────────────────────────────────┐
│ TOP-5 MATCHES                               │
│                                             │
│ 1. fr-2012-2eur-10ans-euro         0.923 ★  │
│ 2. eu-2012-2eur-10ans-euro         0.871    │
│ 3. fr-2012-2eur-standard           0.612    │
│ 4. fr-2011-2eur-standard           0.587    │
│ 5. be-2012-2eur-10ans-euro         0.541    │
│                                             │
│ Δ (top1 - top2) = 0.052  ⚠ CLOSE            │
└─────────────────────────────────────────────┘
```

- `★` sur la meilleure correspondance (celle qui serait renvoyée comme résultat en prod).
- `Δ` = écart entre top-1 et top-2. Indicateur clé : si trop petit, le matcher n'est pas sûr → warning visuel.
- Code couleur : vert si Δ > 0.15, orange si 0.05–0.15, rouge si < 0.05 (ambiguïté critique).

### Layer 3 — Latences par étape

Panel en haut à droite, mini :

```
┌──────────────────┐
│ det:  23 ms      │
│ emb:  87 ms      │
│ knn:  12 ms      │
│ tot: 122 ms      │
│ fps: 4.8         │
└──────────────────┘
```

- `det` = CoinDetector
- `emb` = CoinEmbedder
- `knn` = EmbeddingMatcher (KNN search)
- `tot` = total de la frame
- `fps` = taux de frames traitées par seconde

Couleur rouge si une étape dépasse son budget (30ms / 100ms / 20ms respectivement), pour spotter les régressions de perf immédiatement.

### Layer 4 — Contexte runtime

Petit panel coin bas-droite, très discret :

```
model: arcface_v0.3.2
embeddings: 2938 (hash a7f2c1)
camera: 1280×720
device: 34°C
```

- Version du modèle TFLite actuellement chargé
- Nombre d'embeddings canoniques en mémoire + hash du `.npy` (pour savoir si on utilise le bon catalogue)
- Résolution caméra active
- Température du device (thermique) — si > 40°C, throttle activé, affiché en rouge

### Layer 5 — Histogramme de convergence (dernière seconde)

Bandeau sur le côté gauche, hauteur de l'écran :

```
Success ████████░░
Fail    ░░░░░░░░░░
Skip    ░░░░░░░░░░
```

- Rolling window des N dernières frames (ex : 30 frames = ~6 secondes).
- Success = match trouvé avec Δ > seuil.
- Fail = détection OK mais matching ambigu.
- Skip = pas de pièce détectée du tout.

Permet de voir en un coup d'œil si le scan "prend" ou s'il part en vrille.

---

## Outils de debug (boutons d'action)

Bande d'icônes en bas, accessible uniquement en mode debug :

| Icône | Action |
|---|---|
| 📸 **Dump** | Sauvegarde la frame actuelle + bounding box + top-5 + embedding brut dans `filesDir/debug-dumps/{timestamp}/`. Utilisable pour replay offline côté `ml/`. |
| 📁 **Dumps** | Liste les dumps sauvegardés, permet de les partager via share sheet Android (ex : envoyer à soi-même par mail pour reprise ordinateur). |
| 🔄 **Replay** | Re-joue un dump sauvegardé (charge l'image, refait passer par le pipeline, compare résultat) — utile pour tester un nouveau modèle sur d'anciennes frames. |
| ⏸ **Freeze** | Stoppe la capture caméra et fige la dernière frame. Permet d'inspecter tranquillement. |
| 🎯 **Force match** | Sélectionne manuellement un `eurio_id` pour déclencher le flow downstream (fiche pièce, ajout coffre) sans passer par le matching. Tester l'UI aval sans dépendre du modèle. |
| 🔍 **Inspect embedding** | Affiche le vecteur d'embedding brut (128 ou 256 floats) avec min/max/mean/std. Détecte les embeddings "morts" (tout zéro) ou saturés. |
| 📊 **Session stats** | Résumé de la session : N scans, taux de succès, latence moyenne, pièces les plus fréquentes. |

**Note implémentation** : les outils qui accèdent au filesystem (Dump, Replay) vivent dans `app/src/debug/` via l'interface `DebugTools`. En release, `DebugTools` a une impl no-op qui affiche un toast "Not available in this build" → code strippé par R8.

### Stockage des dumps

**Décidé le 2026-04-14** : les dumps sont écrits dans `context.getExternalFilesDir("debug-dumps")`.

Avantages d'`externalFilesDir` sur `filesDir` :
- **Accessible via USB sans root** — Raphaël peut brancher son téléphone à son Mac et parcourir les dumps directement dans Finder pour les récupérer côté `ml/`. C'est le workflow principal.
- **Nettoyé automatiquement à l'uninstall de l'app** — pas de résidu permanent sur le device.
- **Pas besoin de permissions runtime** (`READ/WRITE_EXTERNAL_STORAGE`), parce que `externalFilesDir` est le dossier privé de l'app sur le stockage externe.

Structure :
```
/Android/data/com.musubi.eurio/files/debug-dumps/
├── 20260414-153022-a7f2c1/
│   ├── frame.jpg              (la frame caméra au moment du dump)
│   ├── detection.json         (bounding box + confidence YOLO)
│   ├── embedding.bin          (vecteur d'embedding brut, 128 ou 256 floats)
│   ├── matches.json           (top-5 avec scores)
│   └── context.json           (modèle version, hash embeddings, camera config)
├── 20260414-153145-b8e3d0/
│   └── ...
```

### Rotation automatique

**Décidé le 2026-04-14** : double contrainte.

- **Taille totale max** : 200 MB. Au-delà, suppression des plus anciens dumps en FIFO jusqu'à repasser sous la limite.
- **Âge max** : 90 jours. Tout dump plus vieux que ça est supprimé automatiquement.

Les deux règles sont appliquées à chaque ouverture de l'app (check rapide dans `DebugTools.cleanupOldDumps()`). Celle qui se déclenche en premier gagne. Un toast discret informe si une rotation a eu lieu : *"3 vieux dumps supprimés (limite atteinte)"*.

Raison du double critère :
- La taille protège contre l'accumulation en période de dev intensive.
- L'âge protège contre l'oubli — un dump de 3 mois n'a quasi plus aucune valeur parce que le modèle a évolué entre temps.

Pour désactiver la rotation temporairement (ex : session de dev où Raphaël veut tout garder), un bouton "🔒 Lock session" dans les outils de debug épingle les dumps en cours et ignore la rotation pour ceux-là. À re-implémenter si le besoin apparaît — pas en v1.

---

## Organisation des composables

```kotlin
@Composable
fun ScanScreen(viewModel: ScanViewModel) {
    val debugEnabled by DebugState.isEnabled.collectAsState()

    Box {
        CameraPreview(/* ... */)
        
        ScanResultBottomSheet(/* ... */)  // toujours présent
        
        if (debugEnabled) {
            ScanDebugOverlay(
                detection = viewModel.lastDetection,
                matches = viewModel.topKMatches,
                timings = viewModel.frameTimings,
                context = viewModel.runtimeContext,
                onDump = viewModel::dumpCurrentFrame,
                // ...
            )
        }
    }
}
```

Le composable `ScanDebugOverlay` est purement UI. Il reçoit des StateFlow de `ScanViewModel` et les dessine. Zéro logique métier, zéro appel direct aux modèles ML.

Le `ScanViewModel` expose les états intermédiaires (`lastDetection`, `topKMatches`, `frameTimings`) **toujours**, pas seulement en debug. C'est juste qu'en release, personne ne les consomme. Coût mémoire négligeable.

---

## Ce que l'overlay ne doit PAS faire

- **Pas de logs réseau.** Si l'overlay affichait des payloads HTTP, il pourrait accidentellement exposer des clés API ou des tokens user lors d'un screenshot partagé.
- **Pas d'accès au coffre user.** L'overlay scan ne lit pas `user_collection`. Il vit dans le pipeline ML uniquement.
- **Pas de capture vidéo permanente.** Dumper = opt-in explicite (tap sur le bouton). Jamais de recording en background.
- **Pas de télémétrie auto vers un serveur.** Tous les dumps restent locaux. L'user (Raphaël en l'occurrence) choisit explicitement de les partager via share sheet Android.

---

## Évolution future

- **Mode "A/B comparison"** : tester deux modèles en parallèle sur la même frame et comparer les top-5. Utile quand on hésite entre deux checkpoints ArcFace.
- **Mode "Auto-dump on fail"** : quand un scan échoue (pas de match ou Δ trop petit), dump automatique pour analyse a posteriori. Permet d'accumuler un dataset des cas difficiles.
- **Télémétrie opt-in** (v2, après beta) : envoyer des métriques anonymes au backend (latence, taux d'échec, versions modèles) pour détecter les régressions de perf après déploiement. **Jamais** de photos, **jamais** d'infos personnelles.

---

## Questions ouvertes

- [ ] Taille de la police et densité du panel top-5 : comment rester lisible sans écraser la vue caméra ? → à itérer à l'impl.
- [ ] Format de dump exact : image JPG + JSON metadata séparés (décidé, voir "Stockage des dumps") ou archive .zip par dump ? → séparés pour inspection facile, archive envisageable si besoin de partager un dump unique via share sheet.
- [ ] Faut-il une option "recording" qui enregistre toute une session pour rejouer plus tard ? → probablement overkill pour v1, à voir si besoin réel.
- [ ] Mécanisme "Lock session" pour épingler des dumps et bypasser la rotation ? → pas en v1, à ajouter si besoin émerge.
