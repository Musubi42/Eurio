# 03 — Claim, file & UX du flux

## Le claim atomique (servir des items distincts)

On garantit que **deux reviewers n'aient jamais les mêmes items** par un `UPDATE`
atomique (équivalent SQLite du `FOR UPDATE SKIP LOCKED` de Postgres). Pas de Redis.

```sql
-- un reviewer réclame une FENÊTRE de 10 items, atomiquement,
-- en sautant ceux déjà pris et en récupérant les claims abandonnés
UPDATE review_items
SET status = 'claimed', claimed_by = :token, claimed_at = :now
WHERE id IN (
  SELECT id FROM review_items
  WHERE status = 'open'
     OR (status = 'claimed' AND claimed_at < :now - :LEASE_TTL)  -- récup abandon
  ORDER BY priority, published_at
  LIMIT 10
)
RETURNING *;
```

- Le `UPDATE ... WHERE id IN (SELECT ...)` est exécuté dans une transaction
  `BEGIN IMMEDIATE` → atomique, deux reviewers concurrents repartent avec des
  ensembles disjoints.
- **`LEASE_TTL`** (visibility timeout) : si un ami ferme l'onglet sans finir, ses
  items `claimed` redeviennent réclamables après le TTL (ex. 30 min). Auto-réparant.

## La fenêtre de 10 (décision actée)

Pourquoi 10 et pas 100 :
- **Atteignable** : l'ami voit « 10 à faire », c'est psychologiquement léger.
- **Robuste à l'abandon** : un claim de 100 bloquerait 97 items si l'ami n'en fait
  que 3 ; 10 + TTL limite la casse.
- **Boucle de récompense courte** : à la fin des 10, on félicite et on propose la
  suite.

## Boucle UX

```
1. L'ami arrive (lien avec ?u=Paolo42) → claim auto de 10 items.
2. Carte par carte : il identifie / rejette / passe. Compteur "3 / 10".
3. À 10/10 → écran de félicitation gamifié :
     "🎉 Bien joué Paolo ! 10 pièces reviewées."
     [ Encore 10 ]   [ J'arrête pour aujourd'hui ]
4. "Encore 10" → nouveau claim, compteur repart à 0/10.
```

### Gamification (légère, motivante)
- Compteur de la session (« 10 / 10 ») + total cumulé du reviewer (« 240 au total »).
- Message de félicitation à chaque palier de 10.
- (Évolution possible) petit classement amical entre amis, badges. Voir `05`.

## Actions par item

| Action | Effet sur `review_items` | Crée `decisions` ? |
|---|---|---|
| **Accept** (choisit un candidat) | `status='decided'` | oui (`action='accept'`) |
| **Reject** (pas une pièce / trop mauvais) | `status='decided'` | oui (`action='reject'` + `quality_reason`) |
| **Skip** (je ne sais pas) | `status='open'`, `priority += 50`, claim relâché | non (ou `action='skip'` léger) |

- **Skip** ne ferme rien : l'item resombre dans la file pour un autre reviewer ou
  pour l'arbitrage. C'est l'échappatoire « je ne sais pas » indispensable pour des
  non-techniques.

## Garde-fous concurrence

- `review_items.image_asset_id UNIQUE` + claim → impossible que deux personnes
  décident le même item. Les write-conflicts au sens base n'existent quasiment pas.
- La décision écrit avec un guard : `UPDATE ... WHERE id=? AND claimed_by=?` →
  si le claim a expiré et a été repris, l'écriture est rejetée proprement (le front
  recharge l'item suivant).
