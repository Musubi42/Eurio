# `_legacy/` — Archive référentiel pré-coin-richness

Scripts conservés pour audit/contexte historique. **Pas importés depuis du
code de production** (les imports internes entre fichiers sont volontairement
laissés cassés — l'archive n'est pas un package fonctionnel).

Archivés en P.9 du chantier coin-richness (2026-05-26).

## Mapping legacy → moderne

| Legacy                              | Remplacé par                                                | Notes |
|-------------------------------------|--------------------------------------------------------------|-------|
| `apply_3a_new_types.py`             | `ml/scripts/refetch_numista_2eur.py` (P.7)                  | Insertion coins + source_refs depuis payload Numista |
| `apply_3b_rematch.py`               | refetch idempotent (P.7), `eurio_id_migrations`             | Rebinding des nids legacy |
| `apply_3c_move_to_variant.py`       | `referential/numista_transforms.coin_variant_row` (P.7c)    | Détection variant côté pure function |
| `apply_3d_add_as_variant.py`        | idem                                                         | Idem |
| `apply_3e_enrich_context.py`        | `coin_observation_rows` (P.7c)                              | Enrichissement = observations multi-source |
| `apply_3e_flag_uncertain.py`        | `eurio_id_migrations(status='pending')`                     | Review queue post-refetch |
| `apply_3f_standards.py`             | `referential/numista_eurio_id.eurio_id_from_numista_payload`| Slug detection inline avec le fetch |
| `audit_apply_common.py`             | `numista_eurio_id.py` (fonction pure unifiée)               | DEPRECATED slug functions |
| `migrate_to_v2.py`                  | `state/schema.sql` (P.3a additif)                           | V2 ↔ SQLite installé directement |
| `wipe_2eur_for_refetch.py`          | `ml/scripts/wipe_referential.py` (P.6)                      | Wipe SQLite-only avec FK recreate |
| `clean_referential.py`              | wipe + refetch (P.6 + P.7)                                  | Greenfield via pipeline |
| `bootstrap_design_groups_2eur.py`   | `design_group_row` (P.7c)                                   | Joint-issue détecté inline |

## Pourquoi pas tout archivé en P.9 ?

Quatre scripts gardent un chemin actif au moment de l'archive :

- `ml/referential/refetch_numista_2eur.py` (Supabase) — encore utilisé par
  `ml/scripts/discover_numista_recent.py` (admin live) pour `api_search` +
  `NUMISTA_ISSUER_CODE`. À découpler en P.8 (admin Vue ← Supabase → API ml).
- `ml/referential/import_numista.py` — 5 importers actifs (batch_fetch_images,
  fetch_review_images, verify_review_queue, enrich_from_numista, admin API).
- `ml/scripts/migrate_canonical_schema.py` — invoqué dynamiquement par
  `ml/api/referential_routes.py:941`. Sera bouclé avec P.8.
- `ml/scripts/bootstrap_coins_from_referential.py` — utilisé par 2 tests
  (`test_bootstrap_coins.py`, `test_ebay_api.py`). Refactor à part.

Ces 4 résidus passeront en `_legacy/` après P.8 (découplage admin) ou via
une session dédiée P.10.
