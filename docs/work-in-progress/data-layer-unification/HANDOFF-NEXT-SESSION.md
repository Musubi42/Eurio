# Hand-off — reprise data-layer unification

> **Pour qui** : Claude Code (ou humain) qui reprend le chantier
> data-layer-unification après la session 2026-06-19/20.
>
> **À lire d'abord** :
> 1. [`VISION.md`](./VISION.md) — la cible et les 3 principes
> 2. [`ARCHITECTURE.md`](./ARCHITECTURE.md) — pattern layered backend
> 3. [`ROADMAP.md`](./ROADMAP.md) — état d'avancement par phase
> 4. [`DECISIONS.md`](./DECISIONS.md) — décisions clés (D-01 → D-08)
> 5. Ce doc — par où démarrer concrètement

## 1. État au 2026-06-20

### Infra prod sur le VPS (`nixos`)

| Service | URL | État |
|---|---|---|
| Authentik (IDP) | `https://authentik.musubi.dev` | ✅ |
| eurio-api (FastAPI) | `https://eurio-api.musubi.dev` | ✅ container up, lean image |
| admin-vps (panel léger) | `https://eurio-admin.musubi.dev` | ✅ déployé, OIDC + Users + Tokens |
| MinIO | `https://eurio-s3.musubi.dev` | ✅ (bucket `eurio-db` à supprimer en Phase 5) |
| eurio-review (legacy) | container `eurio-review:8048` | ✅ tourne, à éteindre plus tard |

### Code state — branche `sources-jo-wikipedia`

Commits récents par ordre antéchronologique :

```
fca3d167  feat(coins): Phase 2a data-layer-unification — coins via eurio-api
cc4b7e92  feat(eurio-api): Phase 1 — orphan tables migrated
3eeabc40  docs(data-unification): plan d'implémentation 6 phases
415ade40  docs(auth-redesign): parquer F8/F9 admin-vps
4eb980cc  feat(admin-vps): vue Users
5a2669ad  feat(admin-vps): vue Mes Tokens
6cc778a2  chore: retire legacy review-admin
0939b842  feat(studio-local): rip Supabase auth
dfb9ca5b  WIP (utilisateur)
```

À pull sur la machine de reprise.

### Studio-local en chiffres

- `pnpm studio:typecheck` ✅ **100% clean** (état atteint en Phase 2a)
- Composables refactorés : 7 (cf. `ROADMAP.md` §Tracking)
- Composables restants à refactorer : ~22 (cf. ROADMAP)

### eurio-api endpoints live (vérifié 2026-06-20)

- `/auth/*` (OIDC + cookie)
- `/me`, `/users`, `/me/tokens` (auth/RBAC)
- `/review/*` (C4)
- `/confusion-map/*`, `/audit/sets` (Phase 1)
- `/coins/*` (Phase 2a — étendu avec cross-refs + filtres year/series/variant/mintage)
- `/sets/*`, `/operations/*`, `/peer_arbitration/*` (mont via `_CANDIDATES` legacy)

Endpoints skippés sur image lean (dep manquantes — à régler une à la fois si besoin) :
- `referential` (PIL)
- `review_queue`, `coin_assets` (cv2)

## 2. Prochain chunk : Phase 2b — Sources READ endpoints

### 2.1 Objectif

Porter sur `eurio-api` les ~15 endpoints **read-only** sources que
studio-local utilise. Refactor les 6 composables sources vers `eurioApi`.

**C'est la première application en grandeur réelle du pattern layered**
(cf. ARCHITECTURE.md §2). Sois soigneux — la qualité de cette
implémentation sert de modèle pour Phase 2c/2d/2e.

### 2.2 Sub-tasks (ordre d'exécution)

**Sub 1 — Setup commun (~30min)**

- Créer `ml/serving/deps.py` avec `db_connection()` (dependency FastAPI
  qui yield une connexion sqlite3.Row + foreign_keys ON, close en
  finally). Cf. ARCHITECTURE.md §3.1
- Vérifier qu'aucun router existant ne s'effondre si on l'utilise plus
  tard (juste ajouter, ne pas refactorer pour l'instant)

**Sub 2 — Sources domain skeleton (~30min)**

- `mkdir -p ml/serving/sources/`
- Créer `__init__.py`, `models.py` (vide), `repository.py` (vide),
  `service.py` (vide), `router.py` (squelette FastAPI APIRouter)
- Câbler dans `server_serve.py` :
  ```python
  from serving.sources import router as sources_router
  app.include_router(sources_router)
  ```
- Retirer `("sources", ...)` du `_CANDIDATES` (legacy) — il pointait
  vers l'ancien `sources_routes.py` qui ne se monte de toute façon pas
- Smoke : `curl … /sources/healthcheck` (créer un endpoint trivial pour
  vérifier le câblage) → 200

**Sub 3 — Endpoint par endpoint (par ordre de priorité front)**

Pour chaque endpoint ci-dessous, créer/étendre `models.py` +
`repository.py` + `router.py`. Le service.py reste optionnel (créer
seulement si business logic non-triviale).

| Ordre | Endpoint | Tables source | Notes |
|---|---|---|---|
| 1 | `GET /sources` | `source_registry` (11 rows) | liste des sources configurées |
| 2 | `GET /sources/{id}` | `source_registry` + agrégats | header source detail |
| 3 | `GET /source-runs?source_id=…` | `source_runs` (73 rows) | liste runs filtrée |
| 4 | `GET /source-runs/{run_id}` | `source_runs` | snapshot d'un run |
| 5 | `GET /source-runs/{run_id}/funnel` | `source_runs` + `source_images` + `image_assets` | counts par étape |
| 6 | `GET /source-runs/{run_id}/breakdown` | idem | breakdown par axe (search, marketplace) |
| 7 | `GET /source-runs/{run_id}/listings` | `source_images` + `image_assets` + `coin_observations` | liste paginée |
| 8 | `GET /source-runs/{run_id}/searches` | `discovery_searches` | searches du run |
| 9 | `GET /source-runs/{run_id}/discarded` | `discarded_listings` | listings rejetés |
| 10 | `GET /source-runs/{run_id}/log` | `source_runs.log_path` (filesystem) | tail des logs |
| 11 | `GET /sources/status` | aggregator multi-tables | dashboard SourcesPage |
| 12 | `GET /sources/ebay/quota-status` | `api_call_log` | quotas eBay |
| 13 | `GET /sources/ebay/filter-config` | `source_registry.config_json` | config filtres |
| 14 | `GET /sources/ebay/marketplace-map` | `coin_market_quotes` agrégé | map marketplace |
| 15 | `GET /sources/ebay/freshness-groups` | `coin_market_quotes` + dates | freshness |

Pour chaque endpoint :
1. Lire le code de `ml/serving/sources_routes.py` correspondant (le
   legacy a déjà fait le SQL — récupérer la requête, la transposer dans
   `repository.py` avec types propres)
2. Pydantic models dans `models.py` (request filter, response shape)
3. Repository function dans `repository.py`
4. Service function si non-trivial
5. Route dans `router.py` avec `Depends(require_scope("sources:read"))`
6. Smoke test (`curl` avec PAT, comparer avec localhost:8042 idéalement)
7. Commit incrémental (`feat(sources): GET /source-runs (Phase 2b §N)`)

Estime ~20-30min par endpoint simple, jusqu'à 1h pour les agrégats
(funnel, breakdown). Total Sub 3 = 4-5h.

**Sub 4 — Refactor composables studio-local (~1-2h)**

Pour chaque composable, remplacer les `fetch(${ML_API}/sources/...)`
par `eurioApi.get(...)` :

```diff
- import { ML_API } from '@/features/training/composables/useTrainingApi'
+ import { eurioApi } from '@/shared/api/eurio-api'

  // ...
- const resp = await fetch(`${ML_API}/sources/${id}/runs/${runId}/funnel`)
- if (!resp.ok) throw new Error(...)
- return resp.json()
+ return eurioApi.get<RunFunnel>(`/source-runs/${runId}/funnel`)
```

**Attention** : on profite du refactor pour aligner les URL côté API
(`/sources/{id}/runs/{run_id}/funnel` → `/source-runs/{run_id}/funnel` —
`run_id` est globalement unique, pas besoin de scope par source).
Le frontend doit donc aussi changer ses chemins, pas juste le préfixe.

À refactorer :
- `useSourcesApi.ts` (status)
- `useSourceDetail.ts` (header + runs + images)
- `useRunFunnel.ts`
- `useRunBreakdown.ts`
- `useRunListings.ts`
- `useRunDiscarded.ts`
- `useRunSearches.ts`
- `useMarketplaceMap.ts`
- `useFilterConfig.ts`

Smoke test : pages SourcesPage, SourceDetailPage, SourceRunDetailPage,
SourceRunListingsPage — toutes doivent fonctionner en `pnpm dev` sur Mac
(browser hit `eurio-api.musubi.dev` via Bearer PAT depuis `.env.local`).

**Sub 5 — Commit final Phase 2b (~5min)**

- `git status` propre
- MAJ `ROADMAP.md` §Tracking + statut Phase 2b → ✅
- MAJ `DECISIONS.md` si déviations vs ce plan
- Commit `feat(sources): Phase 2b data-layer-unification — sources READ`
- Optionnel : commit doc `docs(data-unification): marquer Phase 2b ✅`

### 2.3 Estimation totale Phase 2b

Si pattern propre, sans détour : **4-6h** focused. Si on rencontre des
schémas SQL surprenants (jointures `coin_market_quotes` aggregée
correctement, etc.), peut monter à 7-8h.

### 2.4 Critères d'acceptation Phase 2b

- [ ] Tous les 15 endpoints listés répondent 200 avec un PAT owner
- [ ] Shape JSON identique à ce que retournait `localhost:8042` (les
      composables front doivent compiler sans changement de type)
- [ ] Studio-local typecheck ✅ clean après refactor
- [ ] Pas un seul `fetch(${ML_API}/sources/...)` ne reste dans `src/features/sources/`
- [ ] La pattern layered (model/repository/service/router) est appliquée
      proprement à `ml/serving/sources/` — pas de SQL dans le router

## 3. Commandes utiles pour reprendre

### Setup machine

```bash
ssh dontpanic@vps
cd /opt/eurio
direnv reload   # charge SOPS + envs
git pull        # récupère dernier état

# Vérif containers
docker ps --filter name=eurio-api --filter name=eurio-admin

# Vérif endpoints critiques
curl -sS -o /dev/null -w "%{http_code}\n" https://eurio-api.musubi.dev/healthz
PAT='eurio_Ed8OX5JDcM247lv_0QUPZknUSLhEi-D_xIhtMpqAu1Y'   # ⚠ démo, à remplacer
curl -sS -H "Authorization: Bearer $PAT" https://eurio-api.musubi.dev/me | head -c 200
```

### Rebuild eurio-api après modif backend

```bash
cd /opt/eurio/infra/eurio-api
sops exec-env /opt/eurio/secrets/dev.env "docker compose up -d --build"
sleep 4
docker logs --tail 30 eurio-api 2>&1 | grep -iE "mont|skip|migration|error"
```

### Inspecter eurio.db (en lecture)

```bash
docker exec eurio-api python -c "
import sqlite3
c = sqlite3.connect('/var/lib/eurio/eurio.db')
c.row_factory = sqlite3.Row
# Schema d'une table
r = c.execute(\"SELECT sql FROM sqlite_master WHERE name='source_runs'\").fetchone()
print(r[0])
# Sample row
for r in c.execute('SELECT * FROM source_runs LIMIT 1'):
    print(dict(r))
"
```

### Smoke test endpoint nouveau

```bash
PAT='...'
curl -sS -H "Authorization: Bearer $PAT" \
  https://eurio-api.musubi.dev/source-runs?limit=2 | jq .
```

### Studio-local en dev (côté Mac/PC)

```bash
# Sur Mac/PC, pas sur VPS
cd <chemin>/admin/packages/studio-local
# Si .env.local pas encore là :
cp .env.example .env.local
# ajouter VITE_EURIO_API_BASE + VITE_EURIO_PAT
pnpm dev   # ouvre http://localhost:5173
```

## 4. Pitfalls connus à éviter

- **NE PAS** importer `sources._base.*`, `cv2`, `torch`, `PIL` en top-level
  d'un module qui sera monté sur le VPS lean. Lazy-import dans la fonction
  si vraiment nécessaire.
- **NE PAS** copier-coller `sources_routes.py` legacy tel quel — il a des
  imports lourds. Repartir de zéro avec les requêtes SQL extraites.
- **NE PAS** oublier `Depends(require_scope("sources:read"))` sur chaque
  endpoint sources. Pas de route sans auth.
- **NE PAS** changer le format de réponse JSON entre legacy `localhost:8042`
  et nouveau eurio-api sans MAJ correspondante côté composable front.
  Garder le shape identique simplifie le diff.
- **NE PAS** introduire des nouveaux types Pydantic qui dupliquent les
  legacy. Réutiliser les types existants dans `coins_routes.py` /
  `sources_routes.py` si la shape est correcte — juste les déplacer dans
  `serving/sources/models.py`.
- **NE PAS** se laisser distraire par les `_CANDIDATES` legacy qui
  skippent. C'est par design, on ne les touche pas dans ce chunk.

## 5. Si l'on rencontre un blocage

- Si une requête SQL legacy est trop complexe à porter proprement :
  documente ça dans `DECISIONS.md` avec ID `D-NN`, propose une
  simplification, et attaque-toi à la version simple. Mieux vaut un
  endpoint sub-optimal qui marche qu'un endpoint parfait jamais livré.
- Si un composable studio-local utilise un endpoint absent côté API :
  vérifie côté legacy `localhost:8042` ce qu'il retourne, puis crée
  l'endpoint correspondant côté eurio-api.
- Si tu doutes d'une décision archi : relis `ARCHITECTURE.md` + ce que
  Phase 2a a livré (`ml/serving/coins_routes.py` est encore fat-controller
  mais c'est le **legacy** — Phase 2b est l'opportunité de faire propre).

## 6. À la fin de la session — checklist

- [ ] `git status` propre
- [ ] `pnpm studio:typecheck` ✅ clean
- [ ] `pnpm studio:build` ✅ ok
- [ ] `eurio-api` container up + healthz 200 + endpoint smoke ok
- [ ] `ROADMAP.md` §Tracking mis à jour avec les composables refactorés
- [ ] `DECISIONS.md` mis à jour si déviations
- [ ] Ce fichier `HANDOFF-NEXT-SESSION.md` réécrit avec le prochain chunk
      (Phase 2c review-queue OU 2d training, selon priorité)
- [ ] Commit final `feat(sources): Phase 2b data-layer-unification — sources READ`
- [ ] (Optionnel) push vers Codeberg

Bonne session ! 🚀
