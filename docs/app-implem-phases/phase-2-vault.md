# Phase 2 — Coffre : Mes pièces + Coin detail enrichi

> **Objectif** : construire la première des trois sous-vues du Coffre (`Mes pièces`), avec filtres, tri, grille, et étoffer l'écran Coin detail introduit en Phase 1.

## Dépendances

- Phase 0 (Room, shell nav)
- Phase 1 (Scan pose déjà `VaultRepository` et le flow d'ajout)

## Livrables

### 1. Segmented control en haut du Coffre

`CoffreScreen.kt` :
- Segmented control M3 (`SegmentedButton`) ou `TabRow` avec 3 segments : `Mes pièces` | `Sets` | `Catalogue`.
- État de segment persisté dans le ViewModel (perdu au process death, acceptable v1).
- Phase 2 : seule `Mes pièces` est fonctionnelle, les deux autres affichent un placeholder "à venir Phase 3/4".

### 2. Sous-vue `Mes pièces`

**Layout** : grille 2 colonnes (`LazyVerticalGrid`, `GridCells.Fixed(2)`), cards de pièces avec :
- Image avers (thumbnail, chargement Coil depuis URL stockée)
- Nom court (ou face value + pays si nom trop long)
- Année + pays (flag emoji)
- Mini-badge si scannée récemment (< 24h)
- Tap → `coin/{eurioId}` (detail)

**État vide** : illustration + texte "Ton coffre est vide · Scanne ta première pièce" + CTA qui pulse vers le FAB scan.

### 3. Filtres & tri

Row horizontale sticky sous le segmented control :
- **Filtres** (chips M3) :
  - Pays (multi-select, drop-down avec 21 drapeaux eurozone)
  - Type (`circulation`, `commémo nationale`, `commémo commune`, `starter kit`, `BU set`, `proof`) — issu de l'enum `issue_type`
  - Année (range slider ou multi-select années 1999-2026)
  - Face value (chip : 1c, 2c, 5c, 10c, 20c, 50c, 1€, 2€)
- **Tri** (dropdown) :
  - Date d'ajout (desc par défaut)
  - Pays (alpha)
  - Année (desc)
  - Face value (desc)
- **Recherche** : icône loupe → text field qui filtre par nom (FR/EN), année, pays.

État filtres géré dans le ViewModel, appliqué via query Room paramétrée.

### 4. Repository & queries

`VaultRepository` étoffé :
- `observeVaultEntries(filter: VaultFilter, sort: VaultSort): Flow<List<VaultEntryWithCoin>>` — join avec `coins` pour tout récupérer en une query, renvoie un Flow que l'UI collect
- `contains(eurioId: String): Boolean` — déjà en Phase 1
- `add(eurioId, source, confidence)` — déjà en Phase 1
- `remove(entryId)` — nouveau pour Phase 2 (swipe-to-delete ou depuis détail)
- `count(): Flow<Int>` — pour les badges/stats

Query DAO exemple :
```kotlin
@Transaction
@Query("""
  SELECT v.*, c.*
  FROM vault_entries v
  INNER JOIN coins c ON v.coin_eurio_id = c.eurio_id
  WHERE (:countries IS NULL OR c.country IN (:countries))
    AND (:types IS NULL OR c.issue_type IN (:types))
    AND (:yearMin IS NULL OR c.year >= :yearMin)
    AND (:yearMax IS NULL OR c.year <= :yearMax)
  ORDER BY
    CASE WHEN :sortBy = 'date_desc' THEN v.scanned_at END DESC,
    CASE WHEN :sortBy = 'country' THEN c.country END ASC
""")
fun observeFiltered(...): Flow<List<VaultEntryWithCoin>>
```

### 5. Coin Detail enrichi

Étoffer la destination `coin/{eurioId}` introduite en Phase 1 :
- **Header** : image avers + revers (swipeable carousel ou tabs)
- **Identity** : nom FR/EN, pays + flag, année, face value, type d'émission (chip coloré), mintage si dispo, statut withdrawn si concerné
- **Description** : `design_description` (texte libre)
- **Sets appartenance** : liste des sets dans lesquels cette pièce est membre (clickable → set detail, Phase 3)
- **Série** : si `series_id` non-null → card "Fait partie de la série {nom}" + lien vers vue série (Phase 3 ou placeholder)
- **État vault** :
  - Si déjà possédée : chip `Dans ton coffre · scannée le {date}`, bouton `Retirer du coffre` (avec confirmation)
  - Si pas possédée : bouton pleine largeur `Ajouter au coffre` (utile depuis le Catalogue Phase 4 ou depuis un set Phase 3)
  - Si arrivé `?fromScan=true` : idem "pas possédée" mais le bouton est highlighted
- **Back behavior** : si `fromScan=true`, retour = Scan (viewfinder reprend). Sinon retour = écran précédent (Coffre/Set/Catalogue).

### 6. Persistance état de liste

Pour éviter de perdre la position de scroll / filtres en naviguant vers détail et revenant :
- `rememberSaveable` pour les états filtre/tri/search.
- `LazyGridState` restauré via `rememberLazyGridState()`.
- Si retour depuis Detail Room renvoie un Flow mis à jour automatiquement (ex : pièce supprimée du vault), l'UI se re-compose proprement.

## Acceptance criteria

- [ ] Coffre s'ouvre sur `Mes pièces` avec la liste des pièces scannées
- [ ] Filtres pays/type/année/face value fonctionnent en combinaison (AND)
- [ ] Tri par date/pays/année/face value fonctionne
- [ ] Recherche texte filtre la liste en live
- [ ] État vide affiché quand vault empty
- [ ] Tap sur une card → Coin detail enrichi avec toutes les sections
- [ ] Ajout/suppression d'une pièce depuis le détail met à jour la liste sans refresh manuel
- [ ] Back depuis détail préserve filtres + position de scroll
- [ ] Image avers chargée via Coil avec placeholder + fallback
- [ ] Segmented control présent, les 2 autres segments affichent placeholder

## Risques / questions ouvertes

- **Pièces ajoutées manuellement** (sans scan) : prévu par `VaultEntry.source=manual_add` mais il n'y a pas de UI pour l'ajout manuel en Phase 2. Ça viendra depuis le Catalogue (Phase 4) ou un Set (Phase 3). En Phase 2, `source` sera toujours `scan`.
- **Doublons d'une même pièce** (l'utilisateur scanne 3 fois le même 2€ Slovenia) : pour v1, **on autorise plusieurs entries pour la même coinId** (on garde la date de chaque scan). L'affichage du Coffre dedup par défaut (une card par coinId, badge "×3"), mais les entries individuelles sont préservées pour un futur "journal de scans". À valider avec le user.
- **Performances grille** : ~100-200 pièces max réaliste par vault. `LazyVerticalGrid` gère ça sans souci.
- **Coin detail "Sets appartenance"** : query `SELECT set_id FROM set_members WHERE coin_eurio_id = ?` sur une table ~1000 lignes, pas de souci perf.

## Docs de référence

- `docs/design/vault/` — specs
- `docs/design/coin-detail/` — specs
- `admin/src/features/coins/pages/CoinsPage.vue` + `CoinDetailPage.vue` — référence d'impl pour les filtres et détails
