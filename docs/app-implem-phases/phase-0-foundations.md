# Phase 0 — Fondations

> **Objectif** : poser l'ossature technique de l'app multi-écrans. Fin de phase = app qui s'ouvre sur la nav, 2 destinations vides (Coffre, Profil), FAB Scan → destination vide, Room initialisée avec catalogue bootstrappé depuis un snapshot packagé, clé Supabase dispo pour sync delta.

## Dépendances

Aucune. Point de départ = branche actuelle avec `MainActivity` mono-écran scan fonctionnel (pipeline YOLO+Hough+ArcFace).

## Livrables

### 1. Navigation shell Material 3
- `Scaffold` avec `BottomAppBar` notched + `FloatingActionButton` `centerDocked` (64dp, accent brand, élévation 8dp).
- 2 onglets de barre : `Coffre` (gauche), `Profil` (droite). Icônes Material.
- FAB central = destination `Scan`. Comportement par défaut : **l'app s'ouvre sur Scan** (pas sur Coffre).
- Navigation via `androidx.navigation:navigation-compose`. Graph avec 3 destinations top-level : `Scan`, `Coffre`, `Profil`. Sub-destinations futures = child routes.
- Bottom bar **toujours visible** (pas de `hideOnScroll`). Le viewfinder Scan dessine en dessous (overlay).
- Écrans Coffre et Profil = placeholders vides (`Text("Coffre")`, `Text("Profil")`) pour cette phase.

### 2. Theme & tokens
- Couleurs brand (indigo + gold selon proto) chargées en `ColorScheme` M3.
- Typography : Fraunces + Inter Tight + JetBrains Mono (chargées depuis assets, déjà présentes dans le proto).
- `eurio_tokens.xml` ou équivalent Compose (`Color.kt`, `Type.kt`, `Shape.kt`).
- Référence : `docs/design/prototype/_shared/tokens.css` + `shared/tokens.css` si existant.

### 3. Base de données locale Room
- Dépendance `androidx.room:room-runtime` + `room-ktx` + `room-compiler` (KSP).
- **Entités** (miroir du schéma Supabase, simplifié pour les besoins mobile) :
  - `CoinEntity` : `eurioId` (PK, String), `country`, `year`, `faceValue`, `issueType` (enum), `seriesId` (nullable), `nameFr`, `nameEn`, `imageObverseUrl`, `imageReverseUrl`, `mintage`, `isWithdrawn`, `designDescription`
  - `CoinSeriesEntity` : `id` (PK), `country`, `designationFr`, `designationEn`, `mintingStartedAt`, `mintingEndedAt`
  - `SetEntity` : `id` (PK, String/UUID), `kind` (enum structural/curated/parametric), `nameFr`, `nameEn`, `descriptionFr`, `descriptionEn`, `criteriaJson` (String — on ne parse la DSL qu'à la lecture), `category`, `displayOrder`, `expectedCount`, `active`
  - `SetMemberEntity` : `setId` (FK), `coinEurioId` (FK), composite PK
  - `VaultEntryEntity` : `id` (PK auto), `coinEurioId` (FK), `scannedAt` (timestamp), `source` (enum : scan / manual_add), `confidence` (float), `notes` (nullable String)
  - `CatalogMetaEntity` : `key` (PK), `value` — stocke `catalog_version`, `bootstrap_at`, `last_sync_at`
- **DAOs** : un par entité, queries basiques en lecture + insertions bulk pour le bootstrap + queries de jointure pour "combien de pièces du set X sont dans mon vault".
- **Migrations** : juste v1 pour Phase 0. Pas de schéma legacy à respecter.

### 4. Bootstrap catalogue depuis snapshot packagé
- À chaque build release (et debug), l'APK embarque `app-android/src/main/assets/catalog_snapshot.json` :
  ```json
  {
    "catalog_version": "2026-04-15T00:00:00Z",
    "coins": [ ... ],
    "coin_series": [ ... ],
    "sets": [ ... ],
    "set_members": [ ... ]
  }
  ```
- Au premier lancement (détection via `CatalogMetaEntity.bootstrap_at IS NULL`) : parse le JSON, insert-bulk dans Room, set `catalog_version` + `bootstrap_at`.
- Script de génération du snapshot : `ml/export_catalog_snapshot.py` (nouveau). Fetch Supabase, dump en JSON, écrit dans `app-android/src/main/assets/`. Appelé via `go-task android:snapshot` (nouvelle commande).
- **Pas de téléchargement d'images** pendant le bootstrap — les URLs sont stockées, les images sont fetchées à la demande par Coil (cache disque local géré par Coil, pas par nous).

### 5. Client Supabase
- Migrer `SupabaseCoinClient.kt` existant vers un `SupabaseClient` propre dans `data/remote/`.
- Config : `BuildConfig.SUPABASE_URL` + `BuildConfig.SUPABASE_ANON_KEY`, déjà en place.
- Endpoints exposés pour cette phase : aucun de nouveau. Le client existant reste, on le réorganise juste en package `data/remote/`.
- **Sync delta** : stubbed pour Phase 0 (méthode `syncIfStale()` qui no-op pour l'instant). L'implémentation réelle arrivera quand on aura un besoin concret (probablement Phase 4 ou 5).

### 6. Architecture package
Proposition de structure :
```
com.musubi.eurio/
├── EurioApp.kt                      (Application class, init Room, init OpenCV)
├── MainActivity.kt                   (host unique, Scaffold + NavHost)
├── ui/
│   ├── theme/                       (Color, Type, Shape, EurioTheme)
│   ├── nav/                         (EurioNavHost, EurioBottomBar, destinations)
│   └── components/                  (réutilisables : CoinCard, StreakBadge, etc.)
├── features/
│   ├── scan/                        (Phase 1)
│   ├── vault/                       (Phase 2)
│   ├── sets/                        (Phase 3)
│   ├── catalog/                     (Phase 4)
│   └── profile/                     (Phase 5)
├── data/
│   ├── local/                       (Room DB, entities, DAOs)
│   ├── remote/                      (Supabase client)
│   └── repository/                  (CoinRepository, SetRepository, VaultRepository)
├── ml/                              (existant : CoinDetector, CoinAnalyzer, etc.)
└── domain/                          (modèles métier purs, enums Issue, SetKind, etc.)
```

### 7. OpenCV init + permissions caméra
- Déjà en place dans `MainActivity` existant. Lors de la migration vers le nouveau shell, déplacer l'init OpenCV dans `EurioApp.onCreate()` et la demande de permission caméra dans le feature scan uniquement (pas au démarrage global).

## Intégration avec l'existant

- `MainActivity.kt` actuel (monolithique, ~860 lignes) → **split** :
  - La partie ML analyzer + state holder → déplacée dans `features/scan/` (Phase 1)
  - La partie UI Compose → remplacée par le `Scaffold` + `NavHost` (Phase 0)
  - La partie init OpenCV → `EurioApp.kt`
- Le pipeline ML (`ml/CoinDetector.kt`, `ml/CoinAnalyzer.kt`, etc.) **ne bouge pas**. Phase 0 ne touche à rien dans `ml/`.

## Acceptance criteria

- [ ] App s'ouvre sur la destination Scan (placeholder vide pour Phase 0, viewfinder pour Phase 1).
- [ ] BottomAppBar visible avec 2 onglets + FAB central cliquable.
- [ ] Tap FAB → navigue vers Scan. Tap Coffre → navigue vers `Coffre` (placeholder). Tap Profil → navigue vers `Profil` (placeholder).
- [ ] Room DB créée et peuplée au premier lancement : `SELECT COUNT(*) FROM coins` > 0 visible dans un log de debug ou un écran temporaire.
- [ ] `catalog_version` stockée en meta, lisible depuis un helper.
- [ ] `go-task android:snapshot` génère le JSON depuis Supabase et le copie dans les assets.
- [ ] Build debug + release tournent tous les deux sans erreur.

## Risques / questions ouvertes

- **Taille du snapshot JSON** : ~500 coins + ~50 sets + ~1000 set_members. Estimation : 500-800 KB JSON. Pas bloquant mais à vérifier. Si ça dérive, envisager protobuf ou découpage par pays.
- **Kapt vs KSP** pour Room : aller direct en **KSP**, pas de dette.
- **Navigation Compose version** : utiliser la dernière stable 2.x, compatible Material 3.
- **MainActivity split risqué** : le MainActivity actuel tient tout — ML state, camera state, debug state, UI. La migration vers les features/ demande de bien identifier les frontières. **Stratégie** : Phase 0 laisse le MainActivity monolithique en place mais désactivé (non référencé dans AndroidManifest), introduit un nouveau `MainActivity` propre avec le Scaffold, et Phase 1 migre le contenu du vieux fichier dans la destination Scan. Zéro perte de fonctionnalité entre Phase 0 et Phase 1.

## Docs de référence

- `docs/design/_shared/data-contracts.md` — schéma local
- `docs/design/_shared/offline-first.md` — stratégie sync
- `supabase/migrations/20260415_cleanup_and_coin_series.sql` — source de vérité du schéma
- `docs/app-implem-phases/research-02-nav-patterns.md` — décisions nav
