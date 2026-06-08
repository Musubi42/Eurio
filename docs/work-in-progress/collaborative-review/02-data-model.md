# 02 — Modèle de données

Deux bases concernées : `review.db` (NOUVELLE, sur le VPS) et des additions
légères côté `eurio.db` (canonique).

## `review.db` (VPS) — schéma proposé

### `reviewers`
Les amis autorisés. Le token est à la fois identité **et** mot de passe.

```sql
CREATE TABLE reviewers (
  token         TEXT PRIMARY KEY,   -- ex. 'Paolo42' (secret partagé en privé)
  display_name  TEXT NOT NULL,      -- ex. 'Paolo'
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  last_seen_at  TEXT
);
```

### `review_items`
Miroir des items `status='open'` poussés depuis `eurio.db` (cf. `07`). Contient
tout ce qu'il faut pour reviewer **hors-ligne du canonique** : pas de jointure
vers `eurio.db`.

```sql
CREATE TABLE review_items (
  id                TEXT PRIMARY KEY,   -- = review_queue.id de eurio.db
  image_asset_id    TEXT NOT NULL UNIQUE,
  crop_url          TEXT NOT NULL,      -- URL MinIO du crop
  source            TEXT,               -- ebay / numista / ...
  listing_title     TEXT,
  candidates_json   TEXT,               -- top-5 Dino [{eurio_id,label,thumb_url,sim}]
  target_eurio_id   TEXT,               -- cible pré-sélectionnée si scrape ciblé
  dino_top1         TEXT,
  priority          INTEGER NOT NULL DEFAULT 100,
  status            TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','claimed','decided','skipped')),
  claimed_by        TEXT REFERENCES reviewers(token),
  claimed_at        TEXT,               -- pour le visibility timeout
  published_at      TEXT NOT NULL
);
CREATE INDEX idx_items_claimable ON review_items(status, priority, published_at);
```

### `decisions`
Une ligne par décision d'un reviewer. **1 reviewer par item** en v1, mais la table
est append-friendly si on ajoute le double-vote plus tard.

```sql
CREATE TABLE decisions (
  id                  TEXT PRIMARY KEY,
  review_item_id      TEXT NOT NULL REFERENCES review_items(id),
  reviewer_token      TEXT NOT NULL REFERENCES reviewers(token),
  action              TEXT NOT NULL CHECK (action IN ('accept','reject','skip')),
  decided_eurio_id    TEXT,            -- si accept
  decided_face        TEXT,            -- obverse/reverse
  decided_variant_kind TEXT,
  quality_reason      TEXT,            -- si reject : not_a_coin / too_low_quality
  notes               TEXT,
  decided_at          TEXT NOT NULL,
  reconciled_at       TEXT             -- NULL tant que pas tiré dans eurio.db
);
CREATE INDEX idx_decisions_unreconciled ON decisions(reconciled_at)
  WHERE reconciled_at IS NULL;
```

> **Note** : `skip` ne crée pas forcément une `decisions` ; il peut juste relâcher
> le claim (item revient `open`, priorité abaissée). À trancher en `03`.

## Additions côté `eurio.db` (canonique)

Les décisions des amis **n'entrent pas directement** dans le référentiel canonique.
Elles atterrissent en **staging**, en attente de l'arbitrage de Raphaël (cf. `05`).

### `peer_review_decisions` (staging)
```sql
CREATE TABLE peer_review_decisions (
  id                  TEXT PRIMARY KEY,   -- = decisions.id du review.db
  image_asset_id      TEXT NOT NULL,
  reviewer_token      TEXT NOT NULL,
  reviewer_name       TEXT NOT NULL,
  action              TEXT NOT NULL,
  decided_eurio_id    TEXT,
  decided_face        TEXT,
  decided_variant_kind TEXT,
  quality_reason      TEXT,
  notes               TEXT,
  decided_at          TEXT NOT NULL,
  imported_at         TEXT NOT NULL,
  arbitration_status  TEXT NOT NULL DEFAULT 'pending'
                      CHECK (arbitration_status IN ('pending','approved','rejected')),
  arbitrated_at       TEXT,
  arbitration_notes   TEXT
);
```

- Quand Raphaël **approuve** une ligne → on applique la *vraie* décision via le
  chemin `decide()` existant (`review_queue_routes.py`), avec
  `decided_by = '<token>'`, `decision_engine_version = 'peer@v1'`, et un niveau de
  confiance **`peer_review`** dans le trust model (cf. `project_trust_model_referential`).
- Quand il **rejette** → l'item peut être re-publié vers le service review ou
  fermé, selon le motif.

> **Pourquoi le staging et pas l'écriture directe ?** Le trust model dit qu'aucune
> source n'est totale et que les divergences passent en review éditoriale. Les amis
> = une provenance de confiance moindre → elles transitent par l'arbitrage avant de
> toucher le canonique. Ça réutilise la doctrine existante au lieu d'en inventer une.
