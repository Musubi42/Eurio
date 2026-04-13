# Achievements engine

> Comment les sets sont définis, comment l'état est calculé, comment les déblocages sont détectés.

---

## Modèle conceptuel

Un **set** est une collection cohérente de pièces définies par une **règle de matching** sur le référentiel.

```kotlin
sealed class SetRule {
    // Toutes les pièces de circulation d'un pays (1c → 2€, 8 pièces)
    data class CirculationOf(val countryIso2: String) : SetRule()

    // Une pièce de chaque pays d'une liste (ex: fondateurs zone euro)
    data class OneFromEachCountry(val countries: List<String>) : SetRule()

    // Toutes les 2€ commémoratives d'un pays
    data class CommemorativesOf(val countryIso2: String) : SetRule()

    // Toutes les pièces frappées une année donnée par un pays (ou tous pays)
    data class MintYear(val year: Int, val countryIso2: String? = null) : SetRule()

    // Au moins une pièce de chaque pays de la zone euro (21 en 2026)
    object GrandChase : SetRule()

    // N pièces dont la valeur de marché > M × face value
    data class HighValueCount(val n: Int, val faceValueMultiplier: Double) : SetRule()
}

data class SetDefinition(
    val id: String,
    val nameKey: String,        // clé i18n
    val rule: SetRule,
    val difficulty: Difficulty,
    val iconKey: String
)
```

Chaque set a une **fonction d'évaluation** qui, étant donné une collection (`List<UserCollectionEntry>`), retourne :
- `List<String>` — les `eurio_id` nécessaires
- `List<String>` — les `eurio_id` possédés parmi ces nécessaires
- Un booléen `isComplete`

---

## Évaluation

```kotlin
interface SetEvaluator {
    fun requiredCoins(catalog: List<Coin>): List<String>        // eurio_ids nécessaires
    fun ownedAmongRequired(
        required: List<String>,
        collection: List<UserCollectionEntry>
    ): List<String>
}
```

Exemple pour `CirculationOf("FR")` :

```
requiredCoins = coin where country_iso2='fr' AND is_commemorative=0 AND year = DERNIERE_ANNEE_DISPO
→ 8 eurio_ids (1c, 2c, 5c, 10c, 20c, 50c, 1€, 2€)

ownedAmongRequired = intersection avec collection.eurio_id
```

Exemple pour `GrandChase` :

```
requiredCoins = null (le set ne demande pas des eurio_id spécifiques, juste une couverture de pays)
evaluation custom : count distinct countries in collection
isComplete = (count == 21)
```

## Catalogue de sets v1 (défini statiquement)

```kotlin
val V1_SETS = listOf(
    SetDefinition("circulation-fr", "set.circulation_country", CirculationOf("FR"), EASY, "flag_fr"),
    SetDefinition("circulation-de", "set.circulation_country", CirculationOf("DE"), EASY, "flag_de"),
    // ... un par pays de la zone

    SetDefinition("eurozone-founding", "set.eurozone_founding",
        OneFromEachCountry(listOf("AT","BE","DE","ES","FI","FR","GR","IE","IT","LU","NL","PT")),
        MEDIUM, "star_eu"),

    SetDefinition("grand-chase", "set.grand_chase", GrandChase, HARD, "globe_eu"),

    SetDefinition("vintage-2002", "set.vintage_year",
        MintYear(2002), VERY_HARD, "calendar"),

    SetDefinition("coffre-dor", "set.high_value",
        HighValueCount(n = 10, faceValueMultiplier = 10.0),
        VERY_HARD, "trophy"),

    // Commémoratives par pays
    SetDefinition("commemo-fr", "set.commemoratives_country", CommemorativesOf("FR"), HARD, "flag_fr_star"),
    SetDefinition("commemo-de", "set.commemoratives_country", CommemorativesOf("DE"), HARD, "flag_de_star"),
    // ...
)
```

Où est-ce que ça vit ? Probablement dans un fichier Kotlin `app/src/main/java/com/musubi/eurio/achievements/SetCatalog.kt`. Statique. Pas de table Room. Modifiable uniquement par une release.

**Alternative** : table Room `set_definition` pour permettre des mises à jour via sync Supabase. Question ouverte, voir ci-dessous.

---

## Déclenchement des déblocages

À chaque modification de `user_collection` :

```
VaultRepository.addCoin(eurioId)
  → VaultRepository.removeCoin(id)
    ↓
AchievementEngine.recompute(userId)
    ↓
    Pour chaque SetDefinition :
      val state = evaluator.evaluate(set, collection)
      val previousState = achievement_state.get(set.id, userId)
      val wasComplete = previousState?.isUnlocked ?: false
      
      achievement_state.upsert(set.id, userId, state.progressCurrent, state.progressTarget, ...)
      
      if (state.isComplete && !wasComplete) {
          // 🎉 Unlock event
          AchievementNotifier.notify(set, firstTime = true)
      }
```

La `AchievementNotifier` peut :
- Afficher une animation plein écran (première fois seulement)
- Envoyer une notification Android si l'app est en background (opt-in)
- Ajouter une entrée dans un "log d'événements" pour l'historique du profil

---

## Notifications de chasse

Message : *"Il te manque 2 pièces pour compléter la série France"*.

Calcul : les sets "presque complets" (`progressCurrent / progressTarget >= 0.75`). Pour chacun, lister les pièces manquantes.

Fréquence : max 1 notification par semaine par user, max 3 sets mentionnés. **Jamais intrusif.**

Settings : toggle on/off par défaut off. L'user doit opt-in.

---

## Questions ouvertes

- [ ] Catalogue de sets : statique dans le code Kotlin OU table Room mise à jour via sync Supabase ?
  - **Statique** : simple, typé, version-locked avec le code. Mais chaque nouveau set = release APK.
  - **Room** : dynamique, permet d'ajouter des sets commémoratifs temporels (ex : "Set JO Paris 2024" uniquement pendant les JO). Plus compliqué.
  - **Recommandation provisoire** : statique en v1, migration vers Room quand on aura besoin de sets temporels.
- [ ] Comment gérer les sets qui évoluent (ex : la série circulation FR peut inclure de nouveaux millésimes chaque année) ? Freeze à une année donnée ou rolling window ?
- [ ] Comment détecter un set "impossible à compléter" (ex : pièce retirée de la circulation) et soft-archiver l'achievement ?
- [ ] Performance : à chaque ajout au coffre on recompute **tous** les sets ? Ou on maintient un index inverse `eurio_id → [sets impactés]` ?
