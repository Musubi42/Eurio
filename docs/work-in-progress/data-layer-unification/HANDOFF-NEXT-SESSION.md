# Hand-off — reprise data-layer unification

> **Pour qui** : Claude Code (ou humain) qui reprend après la session
> 2026-06-20 (Phase 2b ✅ + Phase 2c ✅ + Phase 3 immédiats ✅).
>
> **À lire d'abord** :
> 1. [`VISION.md`](./VISION.md)
> 2. [`ARCHITECTURE.md`](./ARCHITECTURE.md)
> 3. [`ROADMAP.md`](./ROADMAP.md)
> 4. [`DECISIONS.md`](./DECISIONS.md) (D-01 → D-12)
> 5. Ce doc — par où démarrer concrètement

## 1. État au 2026-06-20 (post 2c-b + Phase 3 immédiats)

### Commits récents

```
<2c-b+3>     feat(review-queue,operations,peer-arb): Phase 2c-b + Phase 3 immédiats
3aa29a44     feat(review-queue): Phase 2c-a — stats/rejected/text-signals + bonus 2b market-quotes
7ee66573     feat(sources): Phase 2b — sources READ
de212985     docs(data-unification): hub doc
fca3d167     feat(coins): Phase 2a — coins via eurio-api
```

### eurio-api endpoints live

- `/auth/*`, `/me`, `/users`, `/me/tokens`
- `/review/*` (C4)
- `/confusion-map/*`, `/audit/sets` (Phase 1)
- `/coins/*` (Phase 2a)
- `/sources/*` + `/source-runs/*` + `/sources/ebay/{quota-status,marketplace-map,
  filter-config,freshness-groups,market-quotes}` (Phase 2b)
- `/review-queue/*` complet (stats, rejected, list, detail, lots, triage-stats,
  text-signals) — Phase 2c
- `/operations/*` (pulse, cohorts, wild-diversity, training-readiness) —
  Phase 3 (fix lean import D-11)
- `/peer-arbitration/*` (list, reviewers, approve, reject) — Phase 3
- `/sets/*` (legacy mount inchangé)

### Studio-local

- `pnpm studio:typecheck` ✅ clean
- `pnpm studio:build` ✅ ok
- Composables migrés cumul : 16 (2a) + 9 (2b) + 4 (2c) + 2 (3 immédiats) = **31**
- Composables restants : ceux qui dépendent d'endpoints lourds non livrés
  sur lean (training, augmentation, referential, bench, crop-bench, ingest,
  dino-suggestions) ou qui ne sont pas data (visual helpers comme
  useConfusionZone).

## 2. Prochain chunk — recommandations

### Option A : Phase 2d — Training READ (2-3h)

Porter `/training-runs/*` sur eurio-api. La table `training_runs` (34 rows)
+ `training_epochs` (534 rows) + `training_steps` (épochs détaillés). Le
composable `useTrainingApi.ts` côté studio-local consomme ces données pour
les pages `TrainingPage` + `IterationDetailPage`.

Pattern : reproduire le layered, lire les rows avec sqlite3 stdlib, pas de
dep ML lourde (pas de modèle à charger en READ-only).

### Option B : Phase 4 — Drop `@supabase/supabase-js` (30min)

Si studio-local n'a plus QUE des appels eurio-api + ML_API, on peut
finaliser le drop du SDK Supabase. Vérifier :
```bash
grep -rn 'from .@supabase\|supabase\.from' admin/packages/studio-local/src
```
Si propre → retirer du package.json + drop `src/shared/supabase/` + clean
vite.config + .envrc.example.

### Option C : Phase 2e — endpoints éditoriaux restants

Mints (29 rows), coin_credits (1350), coin_topics (1795), coin_observations
(10626), design_groups (46), referential_catalog. Pattern identique à 2b/2c
(layered). Composable `useReferentialApi`.

**Recommandation** : Option A en premier (les pages training sont utilisées
plus souvent) puis Option C. Option B en dernier (validation cleanup).

## 3. Commandes utiles

### Setup + healthchecks

```bash
ssh dontpanic@vps
cd /opt/eurio
direnv reload
git pull

PAT='<un-PAT-owner>'; H="Authorization: Bearer $PAT"
B='https://eurio-api.musubi.dev'
# Domaines layered (Phase 2b/2c)
curl -sS -H "$H" "$B/sources/healthcheck"   ; echo
curl -sS -H "$H" "$B/review-queue/healthcheck"; echo
# Endpoints réparés Phase 3
curl -sS -H "$H" "$B/operations/cohorts" | jq '.cohorts | length'
curl -sS -H "$H" "$B/peer-arbitration?limit=2" | jq '.items | length'
```

### Rebuild eurio-api

```bash
cd /opt/eurio/infra/eurio-api
sops exec-env /opt/eurio/secrets/dev.env "docker compose up -d --build"
sleep 4
docker logs --tail 30 eurio-api 2>&1 | grep -iE "mont|skip|error"
```

## 4. Pitfalls connus (mis à jour Phase 2c-b + 3)

- **NE PAS** importer `training.*`, `sources._base.*`, `sources.ebay.*` ou
  `vision.*` dans un module monté sur eurio-api lean. Ports pure-Python OK.
- **NE PAS** utiliser `_store()` lazy-import depuis `serving.server` — il
  charge training. Préférer `serving.server_serve._store` avec fallback
  (pattern D-11).
- **NE PAS** essayer d'utiliser cv2/PIL/torch dans `serving/<domain>/`.
- **NE PAS** créer de helper "qui pourrait servir" — Phase 2c-b a porté
  exactement les helpers nécessaires (_row_to_item etc.). Pas de surface
  inutile.
- **VÉRIFIER avant tout port** : tester `docker exec eurio-api python -c
  'import <module>'` pour s'assurer que toutes les deps existent sur lean.

## 5. Checklist fin de session

- [ ] `git status` propre
- [ ] `pnpm studio:typecheck` ✅ clean
- [ ] `pnpm studio:build` ✅ ok
- [ ] eurio-api up + smoke OK
- [ ] ROADMAP MAJ
- [ ] DECISIONS MAJ si déviations
- [ ] HANDOFF réécrit pour la prochaine cible
- [ ] Commit
