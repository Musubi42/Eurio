# 07 — Réconciliation (pont eurio.db ↔ review.db)

Deux flux batch, déclenchés par Raphaël (go-task), jamais en continu.

```
eurio.db ──(1) publish──▶ review.db   (items à reviewer)
eurio.db ◀──(2) reconcile── review.db  (décisions des amis → staging)
```

## (1) Publish — `go-task review:publish`

Pousse les items `status='open'` de `eurio.db` vers le service review.

Étapes :
1. SELECT les items `review_queue.status='open'` (filtrables : lane=`manual`,
   cohorte, source…) qui ne sont **pas déjà** dans `review.db`.
2. Pour chacun : résoudre `crop_url` (MinIO), `candidates_json` (top-5 Dino +
   vignettes), `listing_title`, `target_eurio_id`.
3. UPSERT dans `review_items` (clé `image_asset_id` UNIQUE → idempotent).
4. Optionnel : retirer du service les items entre-temps résolus côté canonique
   (auto-accept, etc.) pour ne pas faire reviewer du déjà-fait.

Transport : appel HTTP authentifié vers le service review (`POST /admin/publish`
avec un token admin), ou écriture directe si le script tourne sur le VPS. À
trancher en `08`.

## (2) Reconcile — `go-task review:reconcile`

Tire les décisions non encore réconciliées et les met en **staging** côté canonique.

Étapes :
1. GET `decisions WHERE reconciled_at IS NULL` depuis le service review.
2. Pour chacune : INSERT dans `eurio.db.peer_review_decisions`
   (`arbitration_status='pending'`), avec `reviewer_token` + `reviewer_name`.
   **Idempotent** : clé = `decisions.id` (PRIMARY KEY) → un re-run ne duplique pas.
3. Marquer `reconciled_at` côté `review.db`.
4. (Rien n'entre encore au canonique : l'arbitrage de Raphaël fait la promotion,
   cf. `05`.)

## Idempotence & sécurité des données

- **Publish** : UPSERT par `image_asset_id` → rejouable sans doublon.
- **Reconcile** : INSERT par `decisions.id` (PK) → rejouable sans doublon
  (`INSERT OR IGNORE`).
- Aucune écriture destructive : le canonique ne bouge qu'à l'**arbitrage**, via le
  chemin `decide()` existant (qui respecte déjà `UNIQUE(image_asset_id)` et les
  guards de statut, cf. `feedback_store_autocommit_unique`).

## Articulation avec le lease eurio.db

- `publish` et `reconcile` **lisent/écrivent `eurio.db`** → ils doivent tourner
  quand Raphaël **détient le lease** (sur Mac typiquement). Ce sont des opérations
  courtes (pas des heures), donc pas de souci de blocage.
- Le service review, lui, est **toujours allumé** et indépendant du lease : les amis
  reviewent même quand personne ne tient le lease eurio.db.

## Routes du service review (esquisse)

| Route | Qui | Rôle |
|---|---|---|
| `POST /auth` | ami | échange token → cookie |
| `POST /claim` | ami | réclame 10 items (claim atomique) |
| `POST /items/{id}/decide` | ami | enregistre une décision |
| `POST /items/{id}/skip` | ami | relâche le claim |
| `GET /me/stats` | ami | compteur session + total (gamification) |
| `POST /admin/publish` | admin | reçoit les items à reviewer |
| `GET /admin/decisions?unreconciled=1` | admin | exporte les décisions |
| `POST /admin/decisions/ack` | admin | marque `reconciled_at` |
