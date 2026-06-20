# Hand-off — reprise data-layer unification

> **Pour qui** : Claude Code (ou humain) qui reprend le chantier
> data-layer-unification après la session 2026-06-20 (Phase 2b ✅).
>
> **À lire d'abord** :
> 1. [`VISION.md`](./VISION.md) — la cible et les 3 principes
> 2. [`ARCHITECTURE.md`](./ARCHITECTURE.md) — pattern layered backend
> 3. [`ROADMAP.md`](./ROADMAP.md) — état d'avancement par phase
> 4. [`DECISIONS.md`](./DECISIONS.md) — décisions clés (D-01 → D-09)
> 5. Ce doc — par où démarrer concrètement

## 1. État au 2026-06-20 (post Phase 2b)

### Infra prod sur le VPS (`nixos`)

| Service | URL | État |
|---|---|---|
| Authentik (IDP) | `https://authentik.musubi.dev` | ✅ |
| eurio-api (FastAPI) | `https://eurio-api.musubi.dev` | ✅ image lean, sources layered |
| admin-vps (panel léger) | `https://eurio-admin.musubi.dev` | ✅ déployé |
| MinIO | `https://eurio-s3.musubi.dev` | ✅ (bucket `eurio-db` à supprimer en Phase 5) |
| eurio-review (legacy) | container `eurio-review:8048` | ✅ tourne, à éteindre plus tard |

### Code state — branche `sources-jo-wikipedia`

Commits récents par ordre antéchronologique :

```
<commit Phase 2b>  feat(sources): Phase 2b data-layer-unification — sources READ
de212985           docs(data-unification): hub doc + architecture layered + hand-off
fca3d167           feat(coins): Phase 2a — coins via eurio-api
3fc89d0d           feat(eurio-api): Phase 1 — orphan tables migrated
3eeabc40           docs(data-unification): plan d'implémentation 6 phases
```

### Studio-local en chiffres

- `pnpm studio:typecheck` ✅ **100% clean** (état maintenu en Phase 2b)
- `pnpm studio:build` ✅ ok
- Composables refactorés : 7 (Phase 2a) + 9 (Phase 2b) = **16**
- Composables restants à refactorer : ~13 (cf. ROADMAP §Tracking)

### eurio-api endpoints live (vérifié 2026-06-20)

- `/auth/*` (OIDC + cookie)
- `/me`, `/users`, `/me/tokens` (auth/RBAC)
- `/review/*` (C4)
- `/confusion-map/*`, `/audit/sets` (Phase 1)
- `/coins/*` (Phase 2a)
- **NOUVEAU** `/sources/*` + `/source-runs/*` (Phase 2b, layered) :
  - liste/status/detail : `/sources`, `/sources/status`, `/sources/{id}`
  - runs : `/sources/{id}/runs`, `/source-runs/{run_id}` et ses 6 sous-vues
  - eBay : `/sources/ebay/{quota-status, marketplace-map, filter-config, freshness-groups}`
- `/sets/*`, `/operations/*`, `/peer_arbitration/*` (mont via `_CANDIDATES` legacy)

## 2. Prochain chunk : Phase 2c — Review queue READ

### 2.1 Objectif

Porter sur `eurio-api` les endpoints **read-only** `review_queue` que
studio-local utilise (5773 rows dans la table, c'est le chantier d'admin
le plus utilisé après les sources).

### 2.2 Choix architectural à trancher en début de session

Le chunk C4 a déjà introduit un domaine `/review/*` (cf.
`serving/review_routes.py`) qui sert les workflows **peer arbitration** /
audits validation. Le domaine `/review-queue/*` (legacy, dans
`review/review_queue_routes.py` actuellement skippé sur lean image car
dep cv2) est distinct. Question :

- **Option A** — Préfixe `/review-queue/*` et garder les deux domaines
  séparés (legacy + C4). Simple, mais on garde la duplication
  conceptuelle.
- **Option B** — Unifier sous `/review/*` (refactor des routes C4 pour
  cohabiter avec les nouvelles routes review_queue). Plus propre à
  terme, mais plus d'effort.

Recommandation : **Option A** pour Phase 2c (préfixe `/review-queue/`),
puis Option B comme task séparé après Phase 2e.

### 2.3 Sub-tasks (ordre d'exécution)

**Sub 1 — Domain skeleton (~30min)**

- `mkdir -p ml/serving/review_queue/`
- Créer `__init__.py`, `models.py`, `repository.py`, `service.py`,
  `router.py` selon le pattern Phase 2b
- Câbler dans `server_serve.py` : `app.include_router(review_queue_router)`
- Smoke : `curl … /review-queue/healthcheck` → 200

**Sub 2 — Endpoints (~3-4h)**

Lister d'abord les endpoints réellement consommés par studio-local —
`grep -rn '/review-queue\|/review/' admin/packages/studio-local/src` puis
porter chaque endpoint selon le pattern (models / repository / router /
smoke). Estimer ~30min par endpoint simple.

Voir `serving/review_routes.py` (legacy C4, garde-fou sur ce qui existe
déjà) et `review/review_queue_routes.py` (legacy, à porter, dépend de
cv2 → ne PAS l'importer, repartir des requêtes SQL).

**Sub 3 — Refactor composables studio-local (~1h)**

À refactorer (cf. ROADMAP §Tracking) :
- `useReviewApi.ts` (le gros)
- `useLotReview.ts`
- `useTextSignals.ts`
- `useDinoSuggestions.ts`

Pattern Phase 2b : `fetch(\`\${ML_API}/...\`)` → `eurioApi.get<T>(...)`.

**Sub 4 — Commit + docs (~10min)**

- MAJ `ROADMAP.md` Phase 2c → ✅, MAJ Tracking
- MAJ `DECISIONS.md` si déviations (cf. D-09 comme template)
- Réécrire ce fichier pour la prochaine session (cible Phase 2d Training)
- `git commit -m "feat(review-queue): Phase 2c data-layer-unification"`

### 2.4 Pitfalls connus (mis à jour Phase 2b)

- **NE PAS** importer `review.review_queue_routes` directement — il a
  des deps cv2 au top-level. Lire son SQL en référence, le porter à plat.
- **NE PAS** oublier `Depends(require_scope("review:read"))` sur chaque
  endpoint.
- **NE PAS** copier le shape d'erreur custom (`Throw RunFunnelError`) si
  ce n'est pas nécessaire — réutiliser le pattern `EurioApiError` du
  client `eurio-api.ts`.
- **NE PAS** changer le shape JSON entre legacy `localhost:8042` et
  nouveau eurio-api sans MAJ correspondante côté composable.

## 3. Commandes utiles pour reprendre

### Setup machine

```bash
ssh dontpanic@vps
cd /opt/eurio
direnv reload
git pull

# Vérif containers
docker ps --filter name=eurio-api

# Vérif endpoints critiques
curl -sS -o /dev/null -w "%{http_code}\n" https://eurio-api.musubi.dev/healthz
PAT='<un-PAT-owner>'
curl -sS -H "Authorization: Bearer $PAT" \
  https://eurio-api.musubi.dev/sources/status | jq '.sources[0].id'  # → "numista_match"
```

### Rebuild eurio-api après modif backend

```bash
cd /opt/eurio/infra/eurio-api
sops exec-env /opt/eurio/secrets/dev.env "docker compose up -d --build"
sleep 4
docker logs --tail 30 eurio-api 2>&1 | grep -iE "mont|skip|migration|error"
```

### Smoke test endpoints sources (Phase 2b)

```bash
PAT='<un-PAT-owner>'
H="Authorization: Bearer $PAT"
B='https://eurio-api.musubi.dev'

# Sources level
curl -sS -H "$H" "$B/sources" | jq 'length'                       # → 11
curl -sS -H "$H" "$B/sources/status" | jq '.sources|length'       # → 8
curl -sS -H "$H" "$B/sources/ebay" | jq '.label'                  # → "eBay Browse"
curl -sS -H "$H" "$B/sources/ebay/runs?limit=2" | jq 'length'     # → 2

# Run level (run_id globalement unique)
RID=$(curl -sS -H "$H" "$B/sources/ebay/runs?limit=1" | jq -r '.[0].id')
curl -sS -H "$H" "$B/source-runs/$RID" | jq '.status'
curl -sS -H "$H" "$B/source-runs/$RID/funnel" | jq '.steps|length'  # → 9
curl -sS -H "$H" "$B/source-runs/$RID/breakdown" | jq '.per_eurio|length'
```

### Studio-local en dev (côté Mac/PC)

```bash
cd <chemin>/admin/packages/studio-local
cp .env.example .env.local  # si pas déjà fait
# ajouter VITE_EURIO_API_BASE + VITE_EURIO_PAT
pnpm dev   # http://localhost:5173
```

## 4. Notes sur la Phase 2b livrée (lecture rapide)

### Architecture du nouveau domaine `serving/sources/`

```
ml/serving/sources/
├── __init__.py            # export router
├── models.py              # 24 Pydantic schemas (filter / response / domaine)
├── repository.py          # SQL pur — sqlite3 stdlib
├── service.py             # registry statique + business logic status/detail
└── router.py              # 15 endpoints, tous Depends(require_scope("sources:read"))
```

Le dependency `serving.deps.db_connection()` (créé en Phase 2b) est
partagé — tous les nouveaux domaines doivent l'utiliser.

### Pattern à reproduire (canonique pour Phase 2c+)

1. **models.py** : un Pydantic model par shape (réutiliser quand possible)
2. **repository.py** : fonctions reçoivent `conn: sqlite3.Connection`,
   retournent des objets Pydantic ou primitifs ; lèvent des exceptions
   typées (`RunNotFound`, etc.) — pas de `HTTPException`
3. **service.py** : seulement si business logic non-triviale (registry,
   agrégation multi-repo). Sinon le router appelle repository directement.
4. **router.py** : signature `def handler(principal, conn, params)`,
   try/except → `HTTPException`. **PAS** de SQL ici.

### Travail en différé (à reprendre quand pertinent)

- Endpoints **write/trigger** `/sources/*` : `POST /sources/{id}/runs`,
  retry-downloads, crop-pending, rescue-discarded — restent sur ML local
  jusqu'à Phase 6.
- File-serving `/sources/{id}/{raws,assets}/.../file` : reste sur ML local
  (les fichiers ne sont pas synchronisés sur le VPS).
- `/sources/{id}/images` · `/quotes` · `/coverage` : non portés Phase 2b,
  composables `fetchSourceImages` / `fetchSourceQuotes` / `fetchSourceCoverage`
  continuent d'utiliser `ML_API` (legacy localhost:8042). À porter en 2c ou 2e
  selon priorité produit.
- `/source-runs/{run_id}/log` : porté mais retourne un placeholder car
  `ml/state/run_logs/` n'est pas livré dans l'image lean (cf. D-09).
- Quota live Numista / delta prix eBay : non porté (cf. D-09, mock fallback
  côté front fait le job pour l'instant).

## 5. À la fin de la session — checklist

- [ ] `git status` propre
- [ ] `pnpm studio:typecheck` ✅ clean
- [ ] `pnpm studio:build` ✅ ok
- [ ] `eurio-api` container up + healthz 200 + endpoints Phase 2c smoke ok
- [ ] `ROADMAP.md` §Tracking mis à jour
- [ ] `DECISIONS.md` mis à jour si déviations
- [ ] Ce fichier `HANDOFF-NEXT-SESSION.md` réécrit pour Phase 2d
- [ ] Commit final `feat(review-queue): Phase 2c data-layer-unification`
- [ ] (Optionnel) push vers Codeberg

Bonne session ! 🚀
