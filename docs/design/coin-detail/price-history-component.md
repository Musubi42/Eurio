# Composant historique de prix — empty-compatible

> **Objectif** : créer le composant dès la v1 avec la bonne API et le bon schema, même si les données eBay ne sont pas encore là. Quand la Phase 2C.4+ populera les observations, le composant se remplira automatiquement sans redesign.
>
> **Décidé le 2026-04-13** : ne pas attendre les vraies données pour construire le composant. Shipper un skeleton + états vides bien gérés.

---

## API du composable

```kotlin
@Composable
fun PriceHistoryChart(
    state: PriceHistoryState,
    faceValueCents: Int,
    onExtendClicked: () -> Unit = {},   // passe à la vue 5 ans
    modifier: Modifier = Modifier
)
```

## États gérés dès la v1

| État | Affichage |
|---|---|
| `Loading` | Skeleton shimmer, même hauteur que le graphe final (pas de layout jump) |
| `Empty` | Message "Pas encore de données de marché" + icône + texte explicatif "Les prix eBay sont calculés hebdomadairement. Cette pièce n'a pas encore été observée sur le marché." |
| `Loaded(points.size < 6)` | Message "Historique insuffisant pour tracer une tendance. {N} points disponibles." (PRD §5.5 : minimum 6 points pour la projection) |
| `Loaded(points.size >= 6)` | Sparkline + stats (min/max/médian) + indicateur tendance + bouton "Étendre 5 ans" |

## Design visuel

**12 mois** (affichage par défaut dans la fiche) :
```
        ╭╮
      ╭─╯╰╮    ╭─╮
 ────╯    ╰──╯  ╰───
 ↗ +12% sur 3 mois · min 6 € · médian 11 € · max 15 €
 [ Étendre 5 ans → ]
```

**5 ans** (modal plein écran après tap sur "Étendre") :
- Graphe plus détaillé avec axes visibles.
- Sélecteur de période (1m / 3m / 6m / 1a / 5a).
- Tooltip au tap qui montre le prix et la date.

## Règles strictes

1. **Jamais d'invention de données.** Si on n'a pas de point, on ne trace pas une droite plate imaginaire. On affiche un état vide explicite.
2. **Toujours afficher la fraîcheur.** "MAJ il y a 3 jours" ou "Données obsolètes". L'user doit savoir ce qu'il regarde.
3. **Incertitude visible.** Si moins de 20 points, on peut afficher une bande de confiance grisée autour de la courbe. Pas de fausse précision.
4. **Pas de valeur exacte future.** La projection ne dit jamais "vaudra 14,32 €". Elle dit "dans 5 ans : 12 € à 18 €" (PRD §5.5).

## Composant projection

```kotlin
@Composable
fun PriceProjection(
    history: List<PricePoint>,     // au moins 6 points
    horizonYears: Int = 5,
    rarityTier: RarityTier,        // pondération selon rareté
    modifier: Modifier = Modifier
)
```

Affiche :
- Un range (P_low, P_high) plutôt qu'une valeur exacte.
- Une mention "estimation indicative" obligatoire.
- Un disclaimer discret "ceci n'est pas un conseil financier".

**Si `history.size < 6`** : le composant ne s'affiche pas du tout, remplacé par un message "Projection disponible après plus de données de marché".

---

## Modèle de calcul v1

Régression linéaire simple sur log(prix) vs date. PRD §5.5 :
- Input : minimum 6 points sur 12 mois.
- Output : pente + intercept + erreur standard.
- Projection = extrapolation linéaire × facteur de rareté (UNCOMMON = 1.0, RARE = 1.2, VERY_RARE = 1.5).
- Bande de confiance = ±2σ.

Modèle v2 (plus tard) : TBD. Peut-être une régression avec saisonnalité si on détecte des patterns (commémoratives qui remontent à l'anniversaire de l'événement).

---

## Intégration avec Room

Le composant ne lit **pas** Room directement. Il reçoit un `PriceHistoryState` via son viewmodel parent, qui est responsable de la requête.

Flow :
1. `CoinDetailViewModel` observe `coin_price_observation` pour avoir la dernière snapshot.
2. À l'ouverture, lance un fetch Supabase async pour les observations historiques.
3. Met à jour `priceHistory: StateFlow<PriceHistoryState>` : `Loading → Loaded(points) | Empty`.
4. Le composable se recompose.

Cache : les points d'historique fetchés sont gardés en mémoire pendant la session. Pas stockés en Room (trop de volume, time series).

---

## Questions ouvertes

- [ ] Faut-il stocker une partie de l'historique en local pour avoir un graphe même offline ? Ou exiger le réseau pour voir l'historique ? → probablement : dernière snapshot en Room (déjà prévu), historique complet uniquement online.
- [ ] Format des points eBay depuis Supabase `source_observations` : est-ce qu'on stocke un point par snapshot ou on agrège par semaine ? Décision bootstrap pipeline, pas app.
- [ ] Couleurs du graphe : une seule couleur neutre ou teinte selon la tendance (vert up, rouge down) ? Attention aux daltoniens.
- [ ] Animation à l'apparition des données (Loading → Loaded) : fade ou morph ? Question UX pure.
