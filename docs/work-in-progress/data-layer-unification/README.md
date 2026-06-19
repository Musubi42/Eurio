# data-layer-unification

> Chantier 2026-06-19 → en cours. Unifier toute la donnée Eurio derrière
> `eurio-api.musubi.dev` (SQLite source de vérité). Décommissionner les
> deux côtés (MinIO `eurio-db` bucket + accès Supabase direct depuis le
> frontend studio-local).

## Docs

- [`IMPLEMENTATION.md`](./IMPLEMENTATION.md) — plan complet 6 phases.

## TL;DR état actuel

- ✅ VPS local `eurio.db` contient déjà les 65 tables éditoriales +
  6 tables auth (identical row-count vs canonical MinIO 2026-06-17)
- ✅ Mac/PC ne détient pas le lease (vérifié 2026-06-19)
- ⬜ Phase 1 — migrer 2 tables Supabase orphelines (`coin_confusion_map`,
  `sets_audit`) vers SQLite
- ⬜ Phase 2 — endpoints eurio-api (par batch, incrémental)
- ⬜ Phase 3 — refactor composables studio-local (parallèle 2)
- ⬜ Phase 4 — drop `@supabase/supabase-js`
- ⬜ Phase 5 — kill MinIO eurio-db bucket + lease workflow
- ⬜ Phase 6 — (optionnel) ML compute local = client HTTP eurio-api
