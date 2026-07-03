# local-sync — schéma de données

## Colonnes additives sur `image_state_events`

| Colonne | Type | Rôle |
|---|---|---|
| `op_id` | TEXT (uuid4 hex, index unique partiel) | identité globale de l'op — idempotence push/pull/replay |
| `machine` | TEXT | machine émettrice (`vps`, `musubi42s-m-436d`, …) |
| `hlc` | TEXT | horloge hybride encodée — voir format ci-dessous |

`NULL` sur les trois = event legacy pré-sync (jamais ré-estampillé, jamais
poussé ; ordonné AVANT tout event stampé à la matérialisation).

Sur les DB existantes, colonnes posées par le **pre-bootstrap** `_ensure_column`
(`ml/store/connection.py`) AVANT `executescript` (les index partiels de
`schema.sql` en dépendent). Fresh DB : dans le `CREATE TABLE`.

## Format HLC

```
'{ts_ms:013d}-{count:04d}-{machine}'      ex: 1783096766971-0003-vps
```

Largeur fixe → **l'ordre lexicographique EST l'ordre HLC** (`WHERE hlc > ?` en
SQL, pas de parse). `count` absorbe les rafales et les horloges qui reculent ;
`machine` départage les ex æquo (ordre total). État persistant dans
`sync_state` : `hlc_last` (monotonie au restart, avancé par `hlc_merge` au
pull → causalité), `machine_id` (généré `<hostname≤11>-<4hex>`, override env
`EURIO_MACHINE_ID` — le VPS est figé à `vps`).

## Nouvelles tables (schema.sql §local-sync)

```sql
sync_outbox        -- file d'envoi locale (PAS le log) : op_id PK, kind event|tombstone,
                   -- event_id FK CASCADE, asset_id, status pending|pushed, pushed_at.
                   -- Purgée avec marge d'un cycle ; vide en mode hub (VPS).
sync_tombstones    -- suppressions (survivent au DELETE CASCADE) : asset_id PK, op_id,
                   -- machine, hlc, storage_path (invalidation cache), reason.
sync_state         -- KV : machine_id, hlc_last, pull_cursor_hlc, last_sync_at,
                   -- last_sync_ok, last_error, last_push_count, last_pull_count.
sync_orphan_events -- events reçus dont l'asset n'existe pas encore localement :
                   -- parkés, rejoués à chaque apply_remote.
```

Pourquoi le statut « traité » n'est PAS une colonne du log : le log est
immuable (audit), `image_state_current.last_event_id` le référence, et la file
rend le push trivial (`WHERE status='pending'`) sans scan.

## Convention de payload `detail_json` (v1)

```json
{
  "v": 1,
  "fields":  {"table.colonne": valeur, ...},   // affectations complètes re-dérivables
  "row_ops": [{"op": "upsert|delete", "table": "...", "key": {...}, "values": {...}}],
  "...":     "clés libres existantes (sim, cohort_id, cache_invalidate, ...)"
}
```

- **`fields`** — LWW-par-champ, clé de ligne implicite : `image_assets` par
  `id=asset_id` (strict), `review_queue` par `image_asset_id` (UPSERT — le
  replay crée la row au besoin, `enqueued_at` posé), `cohort_training_scan_results`
  par `asset_id` (best-effort : UPDATE si la ligne dérivée existe).
- **`row_ops`** — lignes non adressables par asset (dino_class_references) ou
  INSERT complets (snapshot add-crop). Whitelist tables : `image_assets`,
  `review_queue`, `dino_class_references`. Appliqués à l'insertion, pas LWW.
- **Valeurs** : la valeur EXACTE écrite en base (relue après l'UPDATE si
  conditionnelle — jamais l'intention), timestamps inclus (pas de re-now()).
- **`v`** : version de forme du payload ; le replay ignore-avec-warning les
  colonnes inconnues (forward-compat).

## Catalogue des `reason` (mutations autoritatives v1)

| reason | Émis par | fields / row_ops |
|---|---|---|
| `training_eligible` | lab flip include/exclude | `training_eligible`, `quality_reason` (relus) |
| `reassign` | lab reassign | `eurio_id` (+ detail `previous_eurio_id`) |
| `accepted_from_training_set` / `reopened_from_training_set` | lab accept/reopen | image_assets + review_queue complets |
| `intruder_dismiss` | lab dismiss | `cohort_training_scan_results.dismissed` (best-effort) |
| `dino_ref_pin` / `dino_ref_exclude` / `dino_ref_clear` | coin-detail | row_ops upsert/delete `dino_class_references` |
| `reflagged_from_coin` | coin-detail reflag bulk | image_assets + review_queue |
| `human_decided(_lot)` / `trash_*` / `rejected` / `deferred(_lot)` / `restored` | review (lean + heavy) | image_assets + review_queue complets |
| `move_lane` / `requalify` | review heavy | `review_queue.lane(+source)` / `review_queue.kind` |
| `manual_recrop` | crop_edit en place | bbox_json, detection_method, width, height, phash + detail `cache_invalidate` |
| `manual_add_crop` / `manual_add_enqueued` | crop_edit add | row_ops snapshot `image_assets` / fields `review_queue` |
| `bootstrap_backfill` | `client.sync_bootstrap` (actor=system) | diff local→canonique, colonnes autoritatives |
| — tombstone (`manual_delete`) | `crop_edit.delete_crop` | table `sync_tombstones`, terminal |

Hors périmètre v1 (différés, documentés) : `correct_listing`
(listing_text_signals), overlay `source_images.detections_json`.
