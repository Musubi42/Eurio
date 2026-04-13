# Fiche pièce — data schema

> Quels champs sont affichés, d'où ils viennent, et comment on assemble un `CoinDetailViewModel` depuis Room + cache images.

---

## ViewModel

Sketch conceptuel. L'implémentation Kotlin adaptera.

```kotlin
data class CoinDetailViewState(
    // Identité (toujours présent, depuis Room coin)
    val eurioId: String,
    val country: String,             // "France"
    val countryIso2: String,         // "FR" — pour le drapeau
    val year: Int,
    val faceValueLabel: String,      // "2 €" (formatté depuis face_value_cents)
    val theme: String?,              // "10 ans de l'euro fiduciaire" ou null pour circulation
    val isCommemorative: Boolean,
    val designDescription: String?,
    val rarityTier: RarityTier,      // enum COMMON | UNCOMMON | RARE | VERY_RARE
    val mintageTotal: Long?,         // null si inconnu
    val nationalVariants: List<String>,  // vide ou liste ISO2 pour émissions communes

    // Images (optionnelles, fallback en cascade)
    val imageObverseSource: ImageSource,
    val imageReverseSource: ImageSource,

    // Contexte (set au runtime, pas en base)
    val context: Context,

    // Valorisation (optionnelle, depuis Room coin_price_observation)
    val market: MarketValuation?,

    // Historique (optionnel, fetch à la demande depuis Supabase)
    val priceHistory: PriceHistoryState,  // Loading | Empty | Loaded(points)

    // Sets liés (calculés depuis achievement_state)
    val linkedSets: List<LinkedSet>
)

sealed class Context {
    data class ScanResult(val capturedPhotoPath: String, val confidence: Float) : Context()
    data class OwnedCoin(
        val collectionId: Long,
        val userPhotoPath: String?,
        val addedAt: Instant,
        val valueAtAddCents: Int?,
        val condition: String?
    ) : Context()
    object ReferenceOnly : Context()
}

sealed class ImageSource {
    data class Local(val path: String) : ImageSource()             // asset shippé ou cache disque
    data class Remote(val url: String) : ImageSource()              // Supabase Storage CDN
    object Placeholder : ImageSource()                              // icône générique valeur faciale
}

data class MarketValuation(
    val p25Cents: Int,
    val p50Cents: Int,
    val p75Cents: Int,
    val sampledAt: Instant,
    val source: String,                 // "ebay_market"
    val trend3m: Trend,                 // UP | STABLE | DOWN | UNKNOWN
    val deltaVsFaceValuePercent: Int    // calculé
)

sealed class PriceHistoryState {
    object Loading : PriceHistoryState()
    object Empty : PriceHistoryState()          // aucun point connu
    data class Loaded(val points: List<PricePoint>) : PriceHistoryState()
}

data class PricePoint(val at: Instant, val medianCents: Int)

data class LinkedSet(
    val setId: String,
    val setName: String,
    val progressCurrent: Int,
    val progressTarget: Int,
    val isUnlocked: Boolean
)
```

---

## Sources de chaque champ

| Champ | Source | Cache |
|---|---|---|
| `eurioId`, `country*`, `year`, `faceValue*`, `theme`, `isCommemorative`, `designDescription`, `nationalVariants`, `mintageTotal` | Room `coin` (miroir du seed + delta fetch) | Room |
| `rarityTier` | Calculé localement depuis `mintageTotal` et/ou règles statiques | En mémoire |
| `imageObverseSource`, `imageReverseSource` | 1. Asset shippé dans APK (BCE) → 2. Cache disque (Numista fetchée) → 3. Placeholder | Disque local |
| `market` | Room `coin_price_observation` | Room (sync depuis Supabase `source_observations`) |
| `priceHistory` | Supabase `source_observations` filtré par eurio_id + source=ebay_market, time series | Fetché à la demande à l'ouverture de la fiche, cache en mémoire pendant la session |
| `linkedSets` | Calculé depuis Room `achievement_state` et la définition statique des sets | En mémoire |
| `context` | Set par le caller (ScanViewModel, VaultViewModel, ...) | N/A |

## Règle de fallback des images

Une pièce peut avoir 0, 1 ou 2 faces dispos dans nos assets. La règle de cascade :

```
Pour chaque face (obverse/reverse) :
  1. Chercher dans Room coin.image_{face}_path  (chemin local = asset shippé ou cache)
  2. Si null et online : tenter un fetch depuis Supabase Storage
     URL construite : {SUPABASE_STORAGE}/coins/{eurio_id}/{face}.jpg
     En cas de succès, sauvegarder localement et mettre à jour Room
  3. Si fetch échoue ou offline : afficher Placeholder
```

## Calcul de `rarityTier`

Règle provisoire à affiner :

| Tier | Critère |
|---|---|
| `COMMON` | Pièce de circulation standard, pas commémorative |
| `UNCOMMON` | Commémorative avec tirage > 5M |
| `RARE` | Commémorative avec tirage entre 500k et 5M |
| `VERY_RARE` | Commémorative avec tirage < 500k, OU pièces Vatican/Monaco/Saint-Marin |

Ces seuils sont arbitraires pour la v1. Peuvent être affinés avec les données réelles eBay (prix > 10× face value → upgrade du tier).

---

## Questions ouvertes

- [ ] Où vit la définition statique des sets (Millésime 2012, Eurozone founding, ...) ? Dans le code Kotlin (enum) ou dans Room (table `set_definition`) ? Impact : facilité de mise à jour + taille binaire.
- [ ] Faut-il pré-calculer `rarityTier` côté bootstrap `ml/` et le stocker en base, ou le calculer côté Android à chaque affichage ?
- [ ] Comment on gère l'i18n des noms de pays ? Via la locale Android + une table statique `country_iso2 → nom localisé` ?
- [ ] `national_variants` : pour une émission commune, faut-il afficher les drapeaux des 21 pays ou juste un compteur "21 pays participants" ?
