# Coffre — filtres, recherche, tri

> Comment l'user navigue dans sa collection. Vise l'usage avec 10 à 500 pièces en v1 (au-delà, on revoit les perfs).

---

## Filtres disponibles

| Filtre | Valeurs | Source |
|---|---|---|
| **Pays** | Multi-sélection parmi les 21 pays zone euro + Andorre, Monaco, Saint-Marin, Vatican | `coin.country_iso2` |
| **Année** | Range slider OU liste | `coin.year` |
| **Valeur faciale** | Checkboxes : 1c, 2c, 5c, 10c, 20c, 50c, 1€, 2€ | `coin.face_value_cents` |
| **Type** | Circulation / Commémorative / Émission commune | `coin.is_commemorative` + `coin.national_variants` |
| **Rareté** | Commune / Peu courante / Rare / Très rare | `coin.rarity_tier` (dérivé) |
| **Condition** | UNC / SUP / TTB / TB / B / Non renseignée | `user_collection.condition` |
| **Dans un set** | Toggle : "Ne montrer que les pièces appartenant à un set en cours" | Join avec set definitions |

## Recherche texte libre

- Recherche full-text sur : nom du pays, thème, année, design description.
- Implementation : FTS4 de SQLite via Room (ou LIKE simple si FTS est trop lourd pour la v1).
- Match par substring, case-insensitive, accent-insensitive.

Exemples de recherche :
- `"erasmus"` → toutes les pièces avec ce thème
- `"france 2012"` → France 2012, toutes dénominations
- `"2€ commémo"` → toutes les 2€ commémoratives

## Tri

| Tri | Ordre |
|---|---|
| **Date d'ajout** (default) | Plus récent d'abord |
| **Valeur** | Plus cher d'abord (P50) |
| **Delta d'appréciation** | Meilleur pourcentage d'abord |
| **Pays** | A-Z |
| **Année** | Plus ancien d'abord OU plus récent d'abord |
| **Rareté** | Plus rare d'abord |

---

## Vue grille vs liste

Toggle en haut de l'écran. Préférence persistée en DataStore.

### Vue grille (default)
- Cellule carrée, photo obverse dominante.
- Overlay bas : mini-flag pays + valeur faciale.
- Badge top-right : multiplicateur si > 1 exemplaire (`×3`).
- Halo doré pour les pièces appartenant à un set complet.

### Vue liste
- Ligne compacte 64dp de hauteur.
- Photo miniature 48dp + 2 lignes texte (nom, pays/année) + valeur actuelle + delta.
- Swipe left pour retirer (undo 5s).

---

## Perf

- LazyColumn / LazyVerticalGrid Compose pour un scroll fluide.
- Requêtes Room retournent un `Flow<List<CoinInVault>>` → recomposition auto quand la collection change.
- Les filtres modifient la requête SQL (pas de filtrage en mémoire côté Kotlin, pour tenir 1000+ pièces).

---

## Questions ouvertes

- [ ] Combinaison de filtres : AND strict (plus restrictif) ou OR entre filtres de même catégorie ? → probablement AND entre catégories, OR à l'intérieur (standard).
- [ ] Faut-il sauvegarder les filtres actifs entre sessions ? Ou reset à chaque ouverture ?
- [ ] Search bar : persistante en haut ou déployable via icône loupe ?
- [ ] FTS4 vs LIKE : FTS4 alourdit le schema Room (table shadow). Est-ce que LIKE suffit pour < 3000 pièces canoniques ?
