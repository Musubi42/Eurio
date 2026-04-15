# Phase 4 — Coffre : Catalogue complet + carte eurozone interactive

> **Objectif** : rendre fonctionnelle la 3ème sous-vue du Coffre (`Catalogue`), avec comme vue par défaut une **carte interactive de l'eurozone 21 pays** où le fill de chaque pays indique le % de pièces possédées. Drill-down par pays → liste des pièces existantes (silhouettes pour les non-possédées). C'est le différenciateur UX le plus fort d'Eurio.

## Dépendances

- Phase 0 (Room, bootstrap)
- Phase 2 (segmented control Coffre)
- Phase 3 (pattern silhouette déjà en place, à réutiliser)

## Livrables

### 1. Sous-vue `Catalogue` — vue par défaut = carte

`CatalogScreen.kt` affiché dans le segment `Catalogue`.

**Composition** :
- **Header** : toggle `[Carte]` / `[Liste]` (segmented button). Défaut : Carte.
- **Carte eurozone** (quand toggle = Carte) :
  - SVG de l'Europe avec 21 pays eurozone colorables individuellement
  - Chaque pays rempli selon le % de pièces possédées (gradient : `surface` à 0%, `primary` à 100%)
  - Tap sur un pays → drill-down vers liste pays
  - Pan/zoom via `Modifier.transformable` (ou bibliothèque tierce si plus simple)
  - Badge par pays : `X/Y` en petit au-dessus
  - Légende en bas : gradient + "0% — 100% possédées"
- **Liste plate** (quand toggle = Liste) : fallback classique pour les users qui préfèrent. Liste groupée par pays, chaque pays = section expandable avec sous-liste de pièces (silhouettes pour non-possédées).

### 2. Carte SVG — implémentation

**Source SVG** : prendre une carte de l'Europe en SVG (Wikimedia Commons ou Natural Earth), isoler les 21 pays eurozone (2026-04-16, Bulgarie inclue — voir `reference_eurozone_21`), chaque pays = un `<path>` avec un id = code ISO 2 lettres.

**Rendu** : deux options, à trancher en début de phase :

- **Option A — AndroidSVG + Canvas** : parser le SVG, dessiner chaque path sur un Compose Canvas avec couleur par path. Gestion tap via hit-testing sur les paths. Contrôle total. Plus de code.
- **Option B — WebView avec JS** : embed le SVG dans une WebView, JS gère le coloring + tap, remonter les events via JSBridge. Plus rapide à coder, plus lourd runtime. Debuggable via Chrome DevTools.

**Recommandation** : **Option A**. Zéro WebView, tout Compose, feel plus natif, perfs meilleures. Effort de dev raisonnable pour 21 paths.

**Détection tap pays** : pour chaque path, précalculer son bounding box + test précis via `Path.contains(x, y)` ou `PixelMap` sampling. Précalcul à l'init, hit-test constant au tap.

### 3. Drill-down pays

Route `catalog/country/{countryCode}` :

**Layout** :
- Header : flag + nom pays + `X/Y possédées` + progress bar
- Filtres : toggle `Tout` / `Circulation` / `Commémoratives` (issue_type)
- Grille silhouette (réutilise le composant de Phase 3) : toutes les pièces du pays
  - Possédée → image avers
  - Non possédée → silhouette grisée
  - Tap → coin detail
  - Long-press non possédée → "Marquer comme possédée" (ajout manuel vault)

### 4. Vue Liste globale (quand toggle = Liste)

`LazyColumn` avec sections par pays :
- Header section = pays + flag + `X/Y`
- Contenu expandable (collapsed par défaut) = grille silhouette du pays (même composant que drill-down)
- Option de tri global : par pays (alpha), par % possédées (desc), par nombre de pièces

### 5. Repository queries

`CatalogRepository` :
- `observeCountryProgress(): Flow<Map<CountryCode, CountryProgress>>` — renvoie pour chaque pays eurozone `(owned, total, percent)`. Query avec GROUP BY country.
- `observeCoinsForCountry(country, typeFilter): Flow<List<CoinWithOwnership>>` — liste des pièces avec flag `isOwned`.
- `observeAllCoinsGroupedByCountry(): Flow<Map<CountryCode, List<CoinWithOwnership>>>` — pour la vue liste globale.

Query exemple country progress :
```kotlin
@Query("""
  SELECT
    c.country,
    COUNT(*) as total,
    COUNT(DISTINCT v.coin_eurio_id) as owned
  FROM coins c
  LEFT JOIN vault_entries v ON v.coin_eurio_id = c.eurio_id
  WHERE c.country IN (:eurozoneCodes)
  GROUP BY c.country
""")
fun observeCountryProgress(eurozoneCodes: List<String>): Flow<List<CountryProgressRow>>
```

### 6. Recherche globale dans le catalogue

Icône loupe dans le header → full-screen search :
- Text field
- Résultats live (titre / pays / année / face value)
- Filtrage Room `WHERE name_fr LIKE '%query%' OR name_en LIKE '%query%' OR year = :year`
- Tap résultat → coin detail

## Acceptance criteria

- [ ] Onglet `Catalogue` affiche la carte eurozone par défaut
- [ ] Les 21 pays sont colorés selon le % possédé
- [ ] Tap pays → drill-down avec liste + silhouettes
- [ ] Toggle Carte/Liste fonctionne, la vue liste groupe par pays
- [ ] Filtres issue_type dans le drill-down fonctionnent
- [ ] Recherche globale fonctionne (nom, année, pays)
- [ ] Long-press sur silhouette → marquage manuel
- [ ] Mise à jour auto quand le vault change (pan vers carte ↑ % immédiatement)
- [ ] Bulgarie présente et colorable (eurozone 21 à jour)

## Risques / questions ouvertes

- **SVG eurozone précis** : trouver ou construire le SVG 21 pays. Natural Earth + pipeline mapshaper pour extraire les pays eurozone. Travail ponctuel à faire au début de la phase.
- **Taille APK** : SVG européen léger (<100KB). Pas d'impact.
- **Zoom/pan fluidité** : Canvas Compose tient sans souci pour 21 paths modérément complexes.
- **Certains pays géographiquement très petits** (Malte, Chypre, Luxembourg) : hit-test peut être frustrant sur mobile. **Solution** : ajouter des `hit zones` agrandies autour des petits pays (cercle 48dp minimum) qui override le hit-test SVG.
- **Territoires d'outre-mer** : la carte doit gérer les DOM-TOM français, portugais, espagnols si la codebase les considère comme leur métropole. Probablement à ignorer (rester sur la projection Europe continentale).
- **Projection** : prendre une projection Lambert ou Albers centrée Europe, éviter Mercator qui déforme trop au nord.

## Docs de référence

- `reference_eurozone_21` (mémoire) — 21 pays dont Bulgarie depuis 2026-01-01
- `docs/design/vault/` — specs si la carte y est déjà pensée
- `docs/app-implem-phases/research-01-scan-collect-apps.md` — rationale carte CoinSnap
- Natural Earth data — source SVG recommandée
