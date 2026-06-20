# Hand-off — reprise data-layer unification

> **Pour qui** : Claude Code (ou humain) qui reprend après la session
> 2026-06-20 (Phase 2b ✅ + Phase 2c-a ✅ partielle).
>
> **À lire d'abord** :
> 1. [`VISION.md`](./VISION.md)
> 2. [`ARCHITECTURE.md`](./ARCHITECTURE.md)
> 3. [`ROADMAP.md`](./ROADMAP.md)
> 4. [`DECISIONS.md`](./DECISIONS.md) (D-01 → D-10)
> 5. Ce doc — par où démarrer concrètement

## 1. État au 2026-06-20 (post 2c-a)

### Commits récents

```
<commit Phase 2c-a>  feat(review-queue): Phase 2c-a — stats/rejected/text-signals + bonus 2b market-quotes
7ee66573             feat(sources): Phase 2b — sources READ
de212985             docs(data-unification): hub doc
fca3d167             feat(coins): Phase 2a — coins via eurio-api
```

### eurio-api endpoints live

- `/auth/*`, `/me`, `/users`, `/me/tokens`
- `/review/*` (C4 — audit/validation)
- `/confusion-map/*`, `/audit/sets` (Phase 1)
- `/coins/*` (Phase 2a)
- `/sources/*` + `/source-runs/*` (Phase 2b — layered)
  - dont bonus `/sources/ebay/market-quotes` (porté en 2c-a)
- `/review-queue/{healthcheck,stats,rejected,{id}/text-signals,asset/{id}/text-signals}` (Phase 2c-a — layered)

### Studio-local

- `pnpm studio:typecheck` ✅ clean
- `pnpm studio:build` ✅ ok
- Composables refactorés cumul : 16 (2a) + 9 (2b) + 2 (2c-a : useTextSignals, useReviewApi-partiel) = 27
- Composables restants : ~10

## 2. Prochain chunk : Phase 2c-b — review-queue endpoints lourds

### 2.1 Objectif

Porter les 5 endpoints lourds restants de `review_queue` :
- `GET /review-queue` (list, ~180 lignes legacy)
- `GET /review-queue/{review_id}` (single)
- `GET /review-queue/triage-stats`
- `GET /review-queue/lots`
- `GET /review-queue/lots/{listing_key}`

### 2.2 Sub-tasks

**Sub 1 — Élargir models.py (~30 min)**

Compléter `ml/serving/review_queue/models.py` avec les types riches :
- `ReviewItem` (20+ champs : bbox, candidates, group_candidates,
  standard_candidates, dino_top1, listing_kind, condition, …)
- `ReviewCandidate`, `ReviewBbox`
- `LotListItem`, `LotListResponse`, `LotDetail`, `LotImage`, `LotDetection`,
  `LotCrop`
- `TriageStats`, `TriageVerdictCounts`, `TriageLaneCounts`

Référence : `ml/review/review_queue_routes.py` lignes 129-205, 1250-1306.

**Sub 2 — Helpers SQL dans repository.py (~1h)**

Porter :
- `_LISTING_KEY_SQL` constant
- `_NOT_RESTORED_SQL` + `_RESTORED_NOTE = "restored"`
- `_VALID_KINDS`, `_VALID_LANES`
- `_build_target_candidate(row, target_eurio_id)`
- `_build_dino_top1_candidate(conn, eurio_id, sim)`
- `_fetch_group_candidates(conn, pairs)` (1 requête par pair (country, year))
- `_fetch_standard_candidates(conn, countries)` (avec `canonical_obverse_url`)
- `_row_to_item(row, group_map, conn, std_map)` (~80 lignes)

`canonical_obverse_url` vit dans `serving/_coin_helpers.py` — import direct OK,
il est livré dans l'image lean.

**Sub 3 — Endpoint `/review-queue` list (~1h)**

Le plus complexe — porter la SQL `SELECT … FROM review_queue rq JOIN
image_assets a JOIN source_images s LEFT JOIN listing_text_signals lts
LEFT JOIN coins t LEFT JOIN image_asset_dino_predictions p …`

Gérer les 3 scopes :
- `review_ids` (CSV IDS explicites — prioritaire)
- `eurio_id` (avec exception standards : pool pays large)
- `cohort_id` (besoin `cohort_jobs` lookup — repris depuis 2c-a `list_rejected`)

**Sub 4 — Endpoint `/review-queue/{id}` (~30 min)**

Single item — réutilise les helpers Sub 2. Lecture d'une row + même
post-processing.

**Sub 5 — Endpoint `/triage-stats` (~1h)**

Porter `compute_auto_validate_verdict_from_row` (50 lignes pure Python) +
`DINO_VERDICT_THRESHOLDS` (constantes) dans `service.py`. Référence :
`ml/training/foundation/auto_validate.py` et `thresholds.py`. Note : le
module `training` n'a PAS besoin d'être livré — c'est juste un copy de
la logique pure dans un module qui sait servir.

**Sub 6 — Endpoints `/lots` + `/lots/{key}` (~1.5h)**

`/lots` : porter le GROUP BY listing_key avec le scope (cohort_id,
target_eurio_id, design_group). Pour `design_group` : porter
`design_group_lot_scope` (logique simple ~30 lignes) dans `service.py`.

`/lots/{key}` : RISQUE — le legacy lit `detections_json` persistées + a
une voie de re-détection live qui dépend de cv2/`normalize_listing_with_detections`.
**Décision recommandée** : porter UNIQUEMENT la lecture des détections
persistées (`_lot_detections_from_json`), retourner `[]` quand
`detections_json` est NULL. Documenter qu'une re-détection live reste
sur ML_API legacy (Phase 6).

**Sub 7 — Refactor composables (~1h)**

- `useReviewApi.fetchReviewQueue` → `eurioApi.get`
- `useReviewApi.fetchReviewItem` → `eurioApi.get`
- `useReviewApi.fetchTriageStats` → `eurioApi.get`
- `useLotReview` (composable complet — fetch lots + lot detail)

**Sub 8 — Commit + docs (~10 min)**

- MAJ ROADMAP Phase 2c → ✅
- MAJ DECISIONS si déviations sur le detail des lots
- Réécrire ce fichier pour la prochaine session (cible Phase 2d Training READ)
- Commit `feat(review-queue): Phase 2c-b — list/detail/triage/lots`

### 2.3 Estimation

5-7h focused (similaire à Phase 2b en volume).

## 3. Commandes utiles

### Setup machine

```bash
ssh dontpanic@vps
cd /opt/eurio
direnv reload
git pull
docker ps --filter name=eurio-api
```

### Rebuild eurio-api

```bash
cd /opt/eurio/infra/eurio-api
sops exec-env /opt/eurio/secrets/dev.env "docker compose up -d --build"
sleep 4
docker logs --tail 30 eurio-api 2>&1 | grep -iE "mont|skip|migration|error"
```

### Smoke endpoints actuels

```bash
PAT='<un-PAT-owner>'
H="Authorization: Bearer $PAT"
B='https://eurio-api.musubi.dev'

# Phase 2c-a (live)
curl -sS -H "$H" "$B/review-queue/stats" | jq
curl -sS -H "$H" "$B/review-queue/rejected?limit=3" | jq 'length'

# Pick a review_id qui a des text-signals
RID=$(docker exec eurio-api python -c "
import sqlite3
c=sqlite3.connect('/var/lib/eurio/eurio.db'); c.row_factory=sqlite3.Row
r=c.execute('''SELECT rq.id FROM review_queue rq
               JOIN image_assets a ON a.id=rq.image_asset_id
               JOIN listing_text_signals lts ON lts.source_image_id=a.source_image_id
               LIMIT 1''').fetchone()
print(r['id'])
")
curl -sS -H "$H" "$B/review-queue/$RID/text-signals" | jq '.coverage'
```

## 4. Pitfalls connus (mis à jour)

- **NE PAS** importer `training.foundation` ni `sources.ebay.standards` —
  ces packages ne sont pas livrés sur l'image lean. Porter la logique pure
  (verdict, design_group_lot_scope) en duplication dans `service.py`.
- **NE PAS** importer `review.review_queue_routes` (cv2 + sources + training
  au top-level).
- **NE PAS** oublier que `_LISTING_KEY_SQL` doit être inlinable dans `repository.py`
  (constante string utilisée par f-string).
- **NE PAS** changer le shape JSON entre legacy `localhost:8042` et nouveau
  eurio-api — les composables compilent déjà sur ces types.
- **CONNAISSANCE COURANTE** : `cohort_jobs` est la table qui porte les cohorts
  (cf. logique cohort_clause dans `list_rejected` 2c-a). Pas besoin d'importer
  `_store().get_cohort()` — un simple `SELECT eurio_ids_json FROM cohort_jobs
  WHERE id = ?` suffit.

## 5. Checklist fin de session

- [ ] `git status` propre
- [ ] `pnpm studio:typecheck` ✅ clean
- [ ] `pnpm studio:build` ✅ ok
- [ ] eurio-api up + smoke OK
- [ ] ROADMAP MAJ
- [ ] DECISIONS MAJ si déviations
- [ ] HANDOFF réécrit pour Phase 2d Training
- [ ] Commit
