# Phase 3 — Coffre : Sets browser + grille silhouette

> **Objectif** : rendre fonctionnelle la sous-vue `Sets` du Coffre. Liste des sets avec progression visible, drill-down vers détail set affichant la grille silhouette (pattern Pokémon Pocket). Connecter la complétion de set au flow scan (highlight en Phase 1 devient vrai affichage ici).

## Dépendances

- Phase 0 (Room, entités `sets`, `set_members`)
- Phase 2 (segmented control Coffre)

## Livrables

### 1. Sous-vue `Sets`

`SetsListScreen.kt` composable affiché dans le segment `Sets` du Coffre.

**Layout** : `LazyColumn` de cards set, chaque card contient :
- **Header row** : titre (FR), sous-titre (description courte), chip catégorie (`country` / `theme` / `tier` / `personal` / `hunt`)
- **Mini-grille silhouette** : 8 premiers slots visibles en miniature (remplis/vides) donnant un aperçu visuel de la complétion
- **Progress footer** : `X / Y pièces collectées` + progress bar linéaire + pourcentage

**Tri** : par défaut, sets pas encore complétés en haut, triés par % desc (tu es proche → motivation). Sets complétés en bas (visible mais pas dominants).

**Filtres** : chips en haut
- Catégorie (country / theme / tier / personal / hunt)
- État (tous / en cours / complétés / non commencés)
- Pays (pour les sets de type structural "country")

**État vide** : si aucun set dans Room, afficher "Aucun set disponible — vérifie ta connexion" (ne devrait pas arriver grâce au bootstrap).

### 2. Écran Set Detail (drill-down)

Route `set/{setId}` :

- **Header** : hero image (si définie dans le set, sinon collage des 4 premières pièces), nom, description longue, chip catégorie, badge kind (structural / curated / parametric)
- **Progression** : grand pourcentage + progress bar + `X / Y`. Si 100% → couronne + mention "Complété le {date}".
- **Grille silhouette** : `LazyVerticalGrid(GridCells.Adaptive(100.dp))`, chaque slot = une pièce membre du set :
  - **Slot possédé** : image avers de la pièce (Coil), tap → coin detail
  - **Slot non possédé** : silhouette stylisée (image en monochrome/gris ou icône placeholder circulaire), tap → coin detail (pour voir la pièce qui manque et la scanner plus tard)
- **Récompense / reward** : si le set définit `reward` (badge / xp), afficher un teaser "Débloque : badge {nom}" en bas. En Phase 3 on se contente de l'afficher, la logique reward vraie est Phase 5.

**Long-press** sur un slot non possédé → menu "Marquer comme déjà possédée" (ajout manuel au vault). Utile si le user a la pièce physiquement mais pas encore scannée.

### 3. Logique de résolution set → coins

Pour les sets `curated` : trivial, on lit `set_members`.

Pour les sets `structural` : le `criteria` JSON définit une DSL (`country=FR AND issue_type=commemo-national`). **En Phase 3 on ne parse pas la DSL côté Android**. On résout les sets structurals **au moment du bootstrap** (côté ml/seed_sets.py ou un script dédié) et on matérialise le résultat dans `set_members` dans le snapshot packagé. Android ne voit que `set_members` déjà peuplées.

Pour les sets `parametric` : même approche, résolution côté bootstrap.

**Conséquence** : le script `ml/export_catalog_snapshot.py` (Phase 0) doit évaluer la DSL sur le catalogue et peupler `set_members` pour les sets structural/parametric avant d'exporter. Ce travail existe peut-être déjà dans `ml/seed_sets.py` — à vérifier et reprendre.

**À trancher avec le user** : est-ce que les sets parametric (e.g., "toutes les 2€ de {pays}" paramétré) génèrent UN set par valeur de param, ou un set "template" avec une UI qui demande le param ? Les docs design (`sets-architecture.md`) tranchent probablement — à lire avant d'implémenter.

### 4. Hook complétion depuis scan

Quand un scan ajoute une pièce au vault (Phase 1), vérifier si ça complète un set :

```kotlin
suspend fun onCoinAdded(eurioId: String): SetCompletionEvent? {
    val impactedSets = setMemberDao.findSetsContaining(eurioId)
    for (set in impactedSets) {
        val total = setMemberDao.countInSet(set.id)
        val owned = vaultDao.countOwnedInSet(set.id)
        if (owned == total && !set.alreadyCelebrated) {
            return SetCompletionEvent(set)
        }
    }
    return null
}
```

`SetCompletionEvent` remonte au `ScanViewModel` et déclenche :
- **v1 (ici)** : highlight visuel sur la card scan ("Set {nom} complété !" + toast)
- **Futur** : cérémonie audiovisuelle complète (animation, sound, etc.)

Persist `alreadyCelebrated` dans un champ `SetEntity.completedAt` (null tant que pas complété une fois).

### 5. Progress tracking côté repository

`SetRepository` :
- `observeAll(filter: SetsFilter): Flow<List<SetWithProgress>>`
- `observeById(setId): Flow<SetWithDetails>`
- `computeProgress(setId): Flow<SetProgress(owned: Int, total: Int, percent: Float)>`

Toutes les queries observent les flows Room, la progression se met à jour automatiquement quand le vault change.

## Acceptance criteria

- [ ] Onglet `Sets` du Coffre affiche la liste complète des sets (depuis le bootstrap)
- [ ] Chaque card affiche mini-silhouette + progression `X/Y` + pourcentage
- [ ] Tri par défaut : en cours en haut, complétés en bas
- [ ] Filtres catégorie / état / pays fonctionnent
- [ ] Drill-down vers détail set affiche la grille silhouette complète
- [ ] Slot possédé → image ; slot non possédé → silhouette grise
- [ ] Tap slot → coin detail
- [ ] Long-press slot non possédé → option "Marquer comme possédée" fonctionnelle
- [ ] Quand un scan complète un set, un `SetCompletionEvent` est levé et la card scan affiche "Set X complété"
- [ ] `SetEntity.completedAt` renseigné, la cérémonie ne se déclenche qu'une fois
- [ ] Progression des sets se met à jour automatiquement quand le vault change (sans refresh manuel)

## Risques / questions ouvertes

- **Résolution DSL côté bootstrap** : travail à faire dans `ml/seed_sets.py` / `export_catalog_snapshot.py` pour que `set_members` soit peuplée exhaustivement avant export. À clarifier avec le user en début de phase — peut-être déjà fait par le script existant.
- **Sets parametric** : comment l'UI les présente vs les structural. Voir `docs/design/_shared/sets-architecture.md` pour le design trancheé.
- **Silhouette rendering** : soit on génère les silhouettes à l'export (grises + downscale), soit on applique un `ColorFilter.tint(gray)` côté Compose sur l'image originale. Option 2 = moins de travail, préférable.
- **Très gros sets** (100+ pièces) : grille silhouette devient longue. Acceptable visuellement (c'est le point — montrer l'ampleur du défi). Lazy grid gère.
- **`reward` champ dans SetEntity** : le schéma Supabase l'a. En Phase 3 on l'affiche, en Phase 5 on implémente la logique.

## Docs de référence

- `docs/design/_shared/sets-architecture.md` — **à lire absolument** (DSL criteria, 3 kinds, expected_count)
- `admin/src/features/sets/` — référence d'impl (SetsListPage, CriteriaBuilder, CuratedMembersPicker)
- `ml/seed_sets.py` — script seed existant, base pour export snapshot
- `docs/app-implem-phases/research-01-scan-collect-apps.md` — rationale silhouette grids
