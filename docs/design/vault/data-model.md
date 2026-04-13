# Coffre — data model

> Comment la collection de l'user est stockée, lue, modifiée. Référence le schema défini dans [`../_shared/data-contracts.md`](../_shared/data-contracts.md).

---

## Tables impliquées

### Table `user_collection` (source of truth)

```
user_collection
├── id                    INTEGER PK AUTOINCREMENT
├── eurio_id              TEXT NOT NULL (FK coin.eurio_id)
├── owner_user_id         TEXT NOT NULL   -- UUID local au départ
├── added_at              INTEGER NOT NULL
├── value_at_add_cents    INTEGER         -- P50 au moment de l'ajout
├── user_photo_path       TEXT
├── condition             TEXT
└── note                  TEXT
```

### Table `coin_price_observation` (cache local des prix)

Utilisée pour calculer la valeur totale sans toucher le réseau.

### Table `achievement_state` (dérivée mais cachée)

Recalculée quand le coffre change, mais persistée pour éviter de tout recalculer à chaque ouverture.

---

## Flows

### Ajouter une pièce (happy path)

```
Scan réussi → user tap "Ajouter au coffre"
  ↓
VaultRepository.addCoin(scanResult, userPhotoPath)
  ↓
INSERT user_collection (
  eurio_id = scanResult.eurioId,
  owner_user_id = currentLocalUserId,
  added_at = now(),
  value_at_add_cents = coin_price_observation[eurio_id].p50_cents,  // ou null
  user_photo_path = userPhotoPath,
  condition = null,
  note = null
)
  ↓
Recalculer achievement_state pour les sets impactés
  ↓
Emit flow update → la vue Coffre se recompose
  ↓
Feedback UX : toast discret "Ajouté au coffre" + haptique
```

### Ajouter une pièce manuellement (sans scan)

Flow identique mais :
- Pas de `user_photo_path`
- L'user a navigué depuis Explorer (v2) ou depuis un deep link

### Retirer une pièce

```
Long press OU bouton dans fiche détail
  ↓
Confirmation modale : "Retirer cette pièce du coffre ?"
  ↓
DELETE user_collection WHERE id = collectionId
  ↓
Recalculer achievement_state
  ↓
Si la suppression casse un set complet → notification discrète (pas de modal)
  ↓
Undo toast pendant 5 secondes pour récupérer l'action
```

### Modifier condition / note

```
Fiche détail → tap sur la section "Ton exemplaire"
  ↓
Bottom sheet avec picker condition (UNC / SUP / TTB / TB / B) + textarea note
  ↓
UPDATE user_collection SET condition = ?, note = ? WHERE id = ?
  ↓
Re-emit state
```

---

## Recalcul des achievements

Quand `user_collection` change, on recalcule les états des sets impactés :

```
val impactedSetIds = sets.filter { set -> set.includes(eurioId) }
for (setId in impactedSetIds) {
    val current = countCoinsInSet(setId, ownerUserId)
    val target = set.size
    achievement_state.upsert(setId, ownerUserId, current, target)
    if (current == target && wasNotComplete) {
        // Unlock trigger — notification + animation
    }
}
```

Cette logique tourne **localement**. Pas de backend impliqué.

---

## Sync cloud (v2, opt-in)

Quand l'user active la sync cloud (nécessite auth Supabase complète) :

- Chaque INSERT/UPDATE/DELETE local est dupliqué sur Supabase `user_collections` avec le `user_id` authentifié.
- Au login depuis un autre device, on pull toutes les lignes Supabase vers Room.
- Conflict resolution : last-write-wins par `updated_at`.

**Pas implémenté en v1.** Le schema Room est déjà prêt (`owner_user_id` peut être remplacé du UUID local vers le user_id Supabase lors de l'upgrade).

---

## Calcul de la valeur totale

Requête SQL côté Room :

```sql
SELECT SUM(COALESCE(cpo.p50_cents, c.face_value_cents))
FROM user_collection uc
LEFT JOIN coin c ON uc.eurio_id = c.eurio_id
LEFT JOIN coin_price_observation cpo ON uc.eurio_id = cpo.eurio_id
WHERE uc.owner_user_id = :userId
```

Fallback sur `face_value_cents` si pas de prix connu : évite de gonfler artificiellement ou de masquer une pièce.

Delta depuis l'ajout :

```sql
SELECT 
  SUM(COALESCE(cpo.p50_cents, c.face_value_cents)) as current_value,
  SUM(COALESCE(uc.value_at_add_cents, c.face_value_cents)) as initial_value
FROM user_collection uc
LEFT JOIN coin c ON uc.eurio_id = c.eurio_id
LEFT JOIN coin_price_observation cpo ON uc.eurio_id = cpo.eurio_id
WHERE uc.owner_user_id = :userId
```

Delta = `(current - initial) / initial * 100`.

---

## Questions ouvertes

- [ ] Doit-on dénormaliser la valeur totale dans une table `vault_stats` pour éviter le recalcul à chaque affichage ? Probablement non tant que < 10k pièces par user.
- [ ] Photo user : stockage dans `filesDir` privé (non visible dans MediaStore) ou dans `Pictures/` publique (accessible par d'autres apps) ? → privé par défaut, option d'export si l'user veut.
- [ ] Suppression : soft delete avec flag `deleted_at` pour permettre l'undo long, ou hard delete + undo transient ? → hard delete + undo toast 5s suffit pour la v1.
