# Scan — data flow

> Qu'est-ce que le scan lit, qu'est-ce qu'il écrit, qu'est-ce qu'il renvoie.

---

## Inputs

| Source | Donnée | Quand |
|---|---|---|
| CameraX | Frame ARGB_8888 (preview, ~720p) | Continu, 3-5 fps |
| Permission caméra | Granted (sinon écran de demande) | Au premier tap sur l'onglet Scan |
| Room `coin` + `coin_embeddings` (via EmbeddingMatcher) | Tous les embeddings canoniques + métadonnées pièces | Chargé en mémoire au démarrage de l'activité Scan |

## Traitement on-device

Voir [`ml-pipeline.md`](./ml-pipeline.md). Rien ne sort du device dans le flow nominal.

## Outputs (happy path)

Quand un match est trouvé :

```kotlin
data class ScanResult(
    val eurioId: String,                // "fr-2012-2eur-10ans-euro"
    val confidence: Float,              // 0.92
    val topKAlternatives: List<Pair<String, Float>>,  // pour debug / suggestions
    val detectedBoundingBox: RectF,     // dans les coords de la frame
    val capturedFramePath: String?      // chemin local de la snapshot figée
)
```

Cet objet est consommé par :
1. **Le composable FicheCoin** pour afficher la pièce (voir [`../coin-detail/README.md`](../coin-detail/README.md)).
2. **Le flow d'ajout au coffre** si l'user tap "Ajouter" → insertion dans Room `user_collection` avec `user_photo_path = capturedFramePath`.

## Outputs (échec)

```kotlin
data class ScanFailure(
    val reason: FailureReason,          // TOO_DARK | NO_COIN_DETECTED | LOW_CONFIDENCE | MODEL_UNCERTAIN
    val bestGuess: String?,             // eurio_id de la meilleure tentative, si une
    val bestGuessConfidence: Float?,
    val hint: String?,                  // "Approche un peu" | "Meilleure lumière" | ...
    val capturedFramePath: String?      // pour permettre un upload manuel
)
```

Utilisé par l'écran "pièce non identifiée" (voir [`README.md`](./README.md) → flow échec).

---

## Ce que le scan NE fait PAS

- **Pas d'appel réseau.** Ni Supabase, ni ailleurs. Le scan est 100% on-device.
- **Pas d'écriture Room directe.** L'ajout au coffre est une étape séparée déclenchée par l'user. Le scan produit juste un `ScanResult`.
- **Pas de cache de photos.** Les snapshots de frames ne sont gardées que si l'user ajoute la pièce au coffre (→ `user_photo_path`). Sinon elles sont supprimées dans les 5 secondes.
- **Pas de télémétrie qui sort du device** sans opt-in explicite de l'user.

---

## Interactions avec Supabase (opt-in, PAS au scan)

Ces sync sont **asynchrones et découplées du scan**. Elles tournent en background via WorkManager, et leurs résultats sont écrits dans Room. Le scan lit ensuite depuis Room sans savoir qui a écrit quoi.

- Sync du référentiel (`coin` table update)
- Sync des embeddings (`coin_embeddings` delta fetch)
- Sync des prix (`coin_price_observation` lazy fetch à l'ouverture de la fiche, pas au scan)

Voir [`../_shared/data-contracts.md`](../_shared/data-contracts.md) pour les détails.

---

## Events à tracker (télémétrie locale, opt-in)

Si l'user accepte la télémétrie anonyme :

| Event | Payload | Pourquoi |
|---|---|---|
| `scan_started` | timestamp | Volume d'usage |
| `scan_success` | eurio_id, confidence, latency_ms | Qualité du modèle en prod |
| `scan_failure` | reason, bestGuess?, latency_ms | Détecter les régressions |
| `scan_added_to_vault` | eurio_id | Taux de conversion scan → ajout |

Ces events peuvent être utilisés pour valider l'Option B vs Option C du [`remote-fallback.md`](./remote-fallback.md).

**Jamais** de photo envoyée dans un event de télémétrie. Jamais.
